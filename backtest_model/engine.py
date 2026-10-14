# -*- coding: utf-8 -*-
"""
==============================================================================
回测引擎 —— 去重建仓 / 日频等权组合 / 绩效指标 / 逐笔明细
==============================================================================

核心口径（与迁移来源 `three_factor_best_backtest.py` 完全一致）：

* 建仓 : 信号日 T **收盘价**买入；同一只股票在持有期内不重复建仓（去重），
         期满后的下一个信号日才允许再次建仓
* 平仓 : T + horizon 个交易日的**收盘价**卖出（停牌自动顺延到下一有报价日）
* 权重 : 每个交易日对所有在持标的**等权**（日度再平衡）
* 成本 : 某日新开仓 n_open 只、平仓 n_close 只、总持仓 h 只（等权 1/h），
         则当日成本率 = (n_open + n_close) / h × cost/2
"""

import numpy as np
import pandas as pd

from . import settings as S


# ═════════════════════════════════════════════════════════════════════════
# 去重建仓
# ═════════════════════════════════════════════════════════════════════════

def build_trades(sig, panel, horizon):
    """把「状态型」信号转成互不重叠的交易。

    同一只股票在持有期 [T, T+horizon] 内只建仓一次；期满后的下一个信号日
    才允许再次建仓。数据末端不足 horizon 个交易日的信号直接剔除（未平仓）。

    Returns:
        (trades DataFrame[stock_code, signal_date, in_pos, out_pos, hold_days],
         skipped 因数据不足被剔除的信号数)
    """
    rows, skipped = [], 0
    for code, g in sig.groupby('stock_code', sort=False):
        j = panel.col.get(code)
        if j is None:
            skipped += len(g)
            continue
        seq = panel.pos_seq[j]
        if len(seq) == 0:
            skipped += len(g)
            continue
        last_out = -1
        col = '_sig_ts' if '_sig_ts' in g.columns else 'signal_date'
        vals = (g[col].to_numpy() if col == '_sig_ts'
                else pd.to_datetime(g[col]).to_numpy())
        for tsv in sorted(pd.unique(vals)):
            ts = pd.Timestamp(tsv)
            p0 = panel.cal_pos.get(ts)
            if p0 is None:
                continue
            k = int(np.searchsorted(seq, p0))
            if k >= len(seq) or seq[k] != p0:
                continue                      # 该日无报价（停牌/未上市）
            if p0 <= last_out:
                continue                      # 仍在持有期内 → 去重
            if k + horizon >= len(seq):
                skipped += 1
                continue                      # 数据不足，未平仓
            p1 = int(seq[k + horizon])
            if p1 <= p0:
                continue
            rows.append((code, ts.strftime('%Y-%m-%d'), p0, p1))
            last_out = p1
    t = pd.DataFrame(rows, columns=['stock_code', 'signal_date',
                                    'in_pos', 'out_pos'])
    t['hold_days'] = t['out_pos'] - t['in_pos']
    return t, skipped


# ═════════════════════════════════════════════════════════════════════════
# 日频等权组合回测
# ═════════════════════════════════════════════════════════════════════════

def run_backtest(panel, trades, cost=S.DEF_COST):
    """日频等权组合回测（每日对所有在持标的等权）。

    Returns:
        dict(nav, net, hold_cnt, open_cnt, close_cnt, n_stock, years, n_trade)
    """
    T = len(panel.calendar)
    cols = sorted(set(trades['stock_code'])) if len(trades) else []
    ci = {c: i for i, c in enumerate(cols)}
    n = len(cols)

    W = np.zeros((T, n), dtype=np.float32)
    open_cnt = np.zeros(T)
    close_cnt = np.zeros(T)
    for r in trades.itertuples():
        j = ci[r.stock_code]
        a, b = int(r.in_pos) + 1, int(r.out_pos)
        if b < a:
            continue
        W[a:b + 1, j] = 1.0
        open_cnt[a] += 1.0
        close_cnt[b] += 1.0

    Rsub = (panel.R[:, [panel.col[c] for c in cols]] if n
            else np.zeros((T, 0)))
    hold_cnt = W.sum(axis=1)
    den = np.maximum(hold_cnt, 1.0)
    gross = np.where(hold_cnt > 0, (Rsub * W).sum(axis=1) / den, 0.0)

    unit = np.where(hold_cnt > 0, 1.0 / den, 0.0)
    fee = (open_cnt + close_cnt) * unit * (cost / 2.0)

    net = gross - fee
    nav = np.empty(T)
    nav[0] = 1.0
    nav[1:] = np.cumprod(1.0 + net[1:])

    span = (panel.calendar[-1] - panel.calendar[0]).days / 365.25
    return {
        'nav': nav, 'net': net, 'hold_cnt': hold_cnt,
        'open_cnt': open_cnt, 'close_cnt': close_cnt, 'n_stock': n,
        'years': max(span, 1e-9),
        'n_trade': len(trades),
    }


# ═════════════════════════════════════════════════════════════════════════
# 绩效指标
# ═════════════════════════════════════════════════════════════════════════

def perf_metrics(nav, calendar, years, hold_cnt=None):
    """由日频净值算核心绩效指标；`hold_cnt` 不为空时附持仓日统计。

    口径提示：空仓日收益记 0，因此年化/夏普反映「资金实际在策略里的表现」。
    """
    ret = nav[1:] / nav[:-1] - 1.0
    total = nav[-1] - 1.0
    cagr = nav[-1] ** (1.0 / years) - 1.0 if years > 0 else np.nan
    sd = ret.std(ddof=1)
    vol = sd * np.sqrt(S.TRADING_DAYS)
    sharpe = (ret.mean() / sd * np.sqrt(S.TRADING_DAYS)) if sd > 0 else np.nan
    dd = nav / np.maximum.accumulate(nav) - 1.0
    mdd = float(dd.min())
    calmar = cagr / abs(mdd) if mdd < 0 else np.nan
    mdd_len, cur = 0, 0
    for x in dd:
        cur = cur + 1 if x < 0 else 0
        mdd_len = max(mdd_len, cur)
    out = {
        '总收益(%)': total * 100,
        '年化收益(%)': cagr * 100,
        '年化波动(%)': vol * 100,
        '夏普': sharpe,
        '最大回撤(%)': mdd * 100,
        'Calmar': calmar,
        '回撤时长(交易日)': mdd_len,
        '日胜率含空仓(%)': (ret > 0).mean() * 100,
        '日均收益(bp)': ret.mean() * 1e4,
        '样本年数': round(years, 2),
    }
    if hold_cnt is not None:
        act = np.asarray(hold_cnt[1:]) > 0
        out['持仓日胜率(%)'] = ((ret[act] > 0).mean() * 100) if act.any() else np.nan
        out['资金利用率(%)'] = act.mean() * 100
        out['持仓日均收益(bp)'] = (ret[act].mean() * 1e4) if act.any() else np.nan
    else:
        out['持仓日胜率(%)'] = np.nan
        out['资金利用率(%)'] = np.nan
        out['持仓日均收益(bp)'] = np.nan
    return out


def period_returns(nav, calendar, freq):
    """按 freq='YE'/'ME' 聚合区间收益（小数）。"""
    s = pd.Series(nav, index=pd.DatetimeIndex(calendar))
    g = s.resample(freq)
    first, last = g.first(), g.last()
    r = (last / first - 1.0)
    r[first.isna()] = np.nan
    return r


def years_of(calendar) -> float:
    """样本区间对应的年数（用于年化）。"""
    cal = pd.DatetimeIndex(calendar)
    return max((cal[-1] - cal[0]).days / 365.25, 1e-9)


# ═════════════════════════════════════════════════════════════════════════
# 逐笔明细
# ═════════════════════════════════════════════════════════════════════════

def trades_detail(panel, trades, cost=S.DEF_COST):
    """把去重后的交易展开成逐笔明细（含毛/净收益、期间最大浮盈浮亏）。"""
    cal = panel.calendar
    rows = []
    half = cost / 2.0
    for r in trades.itertuples():
        j = panel.col[r.stock_code]
        p0, p1 = int(r.in_pos), int(r.out_pos)
        c_in = panel.Pclose[p0, j]
        c_out = panel.Pclose[p1, j]
        seg = panel.Pclose[p0 + 1:p1 + 1, j]
        gross = c_out / c_in - 1.0
        mfe = (np.nanmax(seg) / c_in - 1.0) if len(seg) else np.nan
        mae = (np.nanmin(seg) / c_in - 1.0) if len(seg) else np.nan
        net = (1.0 - half) * (1.0 + gross) * (1.0 - half) - 1.0
        # 信号日次日开盘买入、到期次日开盘卖出（T+1 开盘口径）
        o_in_pos = min(p0 + 1, len(cal) - 1)
        o_out_pos = min(p1 + 1, len(cal) - 1)
        o_in = panel.Popen[o_in_pos, j]
        o_out = panel.Popen[o_out_pos, j]
        oret = (o_out / o_in - 1.0) if (o_in and o_in > 0) else np.nan
        rows.append({
            '股票代码': str(r.stock_code),
            '买入日': cal[p0].strftime('%Y-%m-%d'),
            '卖出日': cal[p1].strftime('%Y-%m-%d'),
            '持有交易日': int(r.hold_days),
            '买入价': round(float(c_in), 3),
            '卖出价': round(float(c_out), 3),
            '毛收益(%)': round(gross * 100, 2),
            '净收益(%)': round(net * 100, 2),
            '期间最大浮盈(%)': round(float(mfe) * 100, 2) if mfe == mfe else np.nan,
            '期间最大浮亏(%)': round(float(mae) * 100, 2) if mae == mae else np.nan,
            'T+1开盘口径(%)': round(oret * 100, 2) if oret == oret else np.nan,
        })
    return pd.DataFrame(rows)


def dedup_returns(panel, sub, h):
    """去重建仓后每笔交易的**毛收益率**序列（对照信号级 vs 交易级）。

    Returns:
        (np.ndarray 毛收益率, trades DataFrame)
    """
    tr, _ = build_trades(sub, panel, h)
    if not len(tr):
        return np.array([]), tr
    j = np.array([panel.col[c] for c in tr['stock_code']])
    p0 = tr['in_pos'].to_numpy(dtype=int)
    p1 = tr['out_pos'].to_numpy(dtype=int)
    cin = panel.Pclose[p0, j]
    cout = panel.Pclose[p1, j]
    with np.errstate(invalid='ignore', divide='ignore'):
        r = cout / cin - 1.0
    return r[np.isfinite(r)], tr


