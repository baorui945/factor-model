# -*- coding: utf-8 -*-
"""
==============================================================================
结果构建 —— 绩效总览 / 年度月度 / 参数敏感性 / 因子分层 / 净值曲线 / 回测说明
==============================================================================

全部函数只做「从回测结果计算表格」，不含任何绘图与 Excel 细节，
便于单测与复用。
"""

import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config                                                # noqa: E402

from . import settings as S                                  # noqa: E402
from . import engine as E                                    # noqa: E402
from .factors import evaluate_rules, load_config             # noqa: E402
from .combos import combo_defs, combo_readme, BEST_KEY       # noqa: E402


def _round(v, nd=3):
    """float -> 保留 nd 位；非 float 原样返回。"""
    return round(v, nd) if isinstance(v, float) else v


def _mtime(path):
    """文件最后修改时间（分钟精度），用于回测说明表记录数据快照。"""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M')


# ═════════════════════════════════════════════════════════════════════════
# 组合 × 持有期 网格回测
# ═════════════════════════════════════════════════════════════════════════

def run_grid(panel, sig, horizons, cost, verbose=True):
    """对每个组合 × 每个持有期跑回测。

    Returns:
        res    : {(key, h): backtest dict}
        trades : {key: {h: trades DataFrame}}
        sigs   : {key: 过滤后的信号 DataFrame}
        meta   : {key: (名称, 说明)}
    """
    res, trades, sigs, meta = {}, {}, {}, {}
    for key, name, filt, desc in combo_defs():
        sub = sig[filt(sig)].copy()
        sigs[key] = sub
        meta[key] = (name, desc)
        trades[key] = {}
        for h in horizons:
            tr, sk = E.build_trades(sub, panel, h)
            trades[key][h] = tr
            r = E.run_backtest(panel, tr, cost)
            if len(tr):
                r['first_in'] = panel.calendar[int(tr['in_pos'].min())]
                r['last_out'] = panel.calendar[int(tr['out_pos'].max())]
            else:
                r['first_in'] = r['last_out'] = pd.NaT
            r['n_sig'] = len(sub)
            r['n_skip'] = sk
            r['avg_hold'] = (float(r['hold_cnt'][r['hold_cnt'] > 0].mean())
                             if (r['hold_cnt'] > 0).any() else 0.0)
            r['max_hold'] = int(r['hold_cnt'].max())
            r['active_days'] = int((r['hold_cnt'] > 0).sum())
            r['wavg_ret'] = float((tr['out_pos'] - tr['in_pos']).mean()) \
                if len(tr) else 0.0
            res[(key, h)] = r
            if verbose:
                m = E.perf_metrics(r['nav'], panel.calendar, r['years'],
                                   r['hold_cnt'])
                print(f'  {key:<4} H{h:<3} 信号{r["n_sig"]:>5} → 交易{r["n_trade"]:>5}  '
                      f'年化{m["年化收益(%)"]:>7.2f}%  回撤{m["最大回撤(%)"]:>7.2f}%  '
                      f'夏普{m["夏普"]:>5.2f}  持仓均值{r["avg_hold"]:>5.2f}  '
                      f'资金利用率{m["资金利用率(%)"]:>5.1f}%', flush=True)
    return res, trades, sigs, meta


# ═════════════════════════════════════════════════════════════════════════
# 绩效总览
# ═════════════════════════════════════════════════════════════════════════

def build_perf_table(res, meta, panel, nav_base, horizons, cost):
    """绩效总览：行 = 组合 × 持有期，列 = 核心指标（首行为沪深300 基准）。"""
    rows = []
    for (key, h), r in res.items():
        if key != 'ALL' and h not in horizons:
            continue
        m = E.perf_metrics(r['nav'], panel.calendar, r['years'], r['hold_cnt'])
        rows.append({
            '组合': f'{key} · {meta[key][0]}',
            '持有期(交易日)': h,
            '原始信号数': r['n_sig'],
            '去重交易笔数': r['n_trade'],
            '因数据不足剔除': r['n_skip'],
            '涉及股票数': r['n_stock'],
            '平均持仓只数': round(r['avg_hold'], 2),
            '最大持仓只数': r['max_hold'],
            '有持仓天数': r['active_days'],
            '首次建仓': (r['first_in'].strftime('%Y-%m-%d')
                     if r['first_in'] == r['first_in'] else ''),
            '末次平仓': (r['last_out'].strftime('%Y-%m-%d')
                     if r['last_out'] == r['last_out'] else ''),
            **{k: _round(v) for k, v in m.items()},
        })
    t = pd.DataFrame(rows)
    # 基准行
    base_m = E.perf_metrics(nav_base, panel.calendar, E.years_of(panel.calendar))
    bm = {'组合': 'Z · 沪深300基准', '持有期(交易日)': '-',
          '原始信号数': '-', '去重交易笔数': '-', '因数据不足剔除': '-',
          '涉及股票数': '-', '平均持仓只数': '-', '最大持仓只数': '-',
          '有持仓天数': len(panel.calendar),
          '首次建仓': panel.calendar[0].strftime('%Y-%m-%d'),
          '末次平仓': panel.calendar[-1].strftime('%Y-%m-%d')}
    bm.update({k: _round(v) for k, v in base_m.items()})
    return pd.concat([pd.DataFrame([bm]), t], ignore_index=True)


# ═════════════════════════════════════════════════════════════════════════
# 年度 / 月度收益
# ═════════════════════════════════════════════════════════════════════════

def build_annual(res, meta, panel, nav_base, horizons):
    """年度收益：行 = 组合（主持有期），列 = 年份。"""
    years = sorted({d.year for d in panel.calendar})
    rows = []
    for key, (name, _) in meta.items():
        h = horizons[0]
        r = res[(key, h)]
        rr = E.period_returns(r['nav'], panel.calendar, 'YE')
        row = {'组合': f'{key} · {name}', '持有期': h}
        for y in years:
            ts = pd.Timestamp(f'{y}-12-31')
            row[str(y)] = round(float(rr.get(ts, np.nan)) * 100, 2) \
                if ts in rr.index else np.nan
        rows.append(row)
    rr = E.period_returns(nav_base, panel.calendar, 'YE')
    row = {'组合': 'Z · 沪深300基准', '持有期': '-'}
    for y in years:
        ts = pd.Timestamp(f'{y}-12-31')
        row[str(y)] = round(float(rr.get(ts, np.nan)) * 100, 2) \
            if ts in rr.index else np.nan
    rows.append(row)
    return pd.DataFrame(rows)


def build_monthly(res, meta, panel, nav_base, horizons):
    """月度收益：行 = 组合，列 = YYYY-MM（宽表，便于透视）。"""
    cols = pd.period_range(panel.calendar[0], panel.calendar[-1],
                           freq='M').astype(str)
    rows = []
    for key, (name, _) in meta.items():
        r = res[(key, horizons[0])]
        s = pd.Series(r['nav'], index=pd.DatetimeIndex(panel.calendar))
        m = s.resample('ME').last() / s.resample('ME').first() - 1.0
        m.index = m.index.to_period('M').astype(str)
        row = {'组合': f'{key} · {name}'}
        for c in cols:
            v = m.get(c, np.nan)
            row[c] = round(float(v) * 100, 2) if v == v else np.nan
        rows.append(row)
    s = pd.Series(nav_base, index=pd.DatetimeIndex(panel.calendar))
    m = s.resample('ME').last() / s.resample('ME').first() - 1.0
    m.index = m.index.to_period('M').astype(str)
    row = {'组合': 'Z · 沪深300基准'}
    for c in cols:
        v = m.get(c, np.nan)
        row[c] = round(float(v) * 100, 2) if v == v else np.nan
    rows.append(row)
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════
# 参数敏感性 / 因子分层
# ═════════════════════════════════════════════════════════════════════════

def build_sensitivity(panel, sig, horizons, cost):
    """阈值扰动敏感性：固定另两个因子，扰动目标阈值，看回测绩效。

    扰动档位由 `config/factors.json` 的 `sensitivity` 段驱动
    （默认 13 档：流通市值 5 档 / 60日波动 4 档 / 60日动量 4 档）。
    """
    h = horizons[0]
    rows = []
    for spec in load_config().get('sensitivity', []):
        sub = sig[evaluate_rules(sig, spec.get('rules', []))]
        tr, _sk = E.build_trades(sub, panel, h)
        r = E.run_backtest(panel, tr, cost)
        m = E.perf_metrics(r['nav'], panel.calendar, r['years'], r['hold_cnt'])
        rr, _ = E.dedup_returns(panel, sub, h)
        rows.append({
            '扰动条件': spec['name'], '原始信号数': len(sub),
            '去重交易笔数': len(tr), '涉及股票数': r['n_stock'],
            '平均持仓只数': round(float(r['hold_cnt'][r['hold_cnt'] > 0].mean())
                              if (r['hold_cnt'] > 0).any() else 0.0, 2),
            '年化收益(%)': round(m['年化收益(%)'], 2),
            '最大回撤(%)': round(m['最大回撤(%)'], 2),
            '夏普': round(m['夏普'], 2) if m['夏普'] == m['夏普'] else np.nan,
            '日胜率含空仓(%)': round(m['日胜率含空仓(%)'], 2),
            '单笔平均(%)': round(float(rr.mean()) * 100, 2) if len(rr) else np.nan,
            '单笔胜率(%)': round(float((rr > 0).mean()) * 100, 2) if len(rr) else np.nan,
        })
    return pd.DataFrame(rows)


def build_factor_layers(panel, sig, h):
    """单因子分档：信号级 20 日收益 + 去重后交易级收益对照。

    分层维度与档位由 `config/factors.json` 的 `layers` 段驱动（默认 3 个维度：
    流通市值 / 60日波动率 / 60日动量；每个维度固定另外两个因子以避免交叉污染）。
    """
    rows = []
    for grp in load_config().get('layers', []):
        col = grp['factor']
        base = evaluate_rules(sig, grp.get('fixed_rules', []))
        for lo, hi, tag in grp['buckets']:
            sub = sig[base & (sig[col] >= lo) & (sig[col] < hi)]
            v = sub['f20'].dropna().to_numpy()
            rr, tr = E.dedup_returns(panel, sub, h)
            rows.append({
                '分层维度': grp['dimension'], '分档': tag,
                '固定条件': grp.get('fixed_text', ''),
                '信号数': len(sub), '去重交易笔数': len(tr),
                '信号级20日平均(%)': round(float(v.mean()) * 100, 2) if len(v) else np.nan,
                '信号级20日胜率(%)': round(float((v > 0).mean()) * 100, 2) if len(v) else np.nan,
                '交易级20日平均(%)': round(float(rr.mean()) * 100, 2) if len(rr) else np.nan,
                '交易级20日胜率(%)': round(float((rr > 0).mean()) * 100, 2) if len(rr) else np.nan,
            })
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════
# 净值曲线 / 回测说明
# ═════════════════════════════════════════════════════════════════════════

def build_nav_curve(panel, res, meta, nav_base, horizons):
    """净值曲线：日期 + 各组合净值 + 沪深300 + 持仓只数 + S1 当日收益。"""
    h = horizons[0]
    d = {'日期': [x.strftime('%Y-%m-%d') for x in panel.calendar]}
    for key, (name, _) in meta.items():
        d[f'{key} · {name}'] = np.round(res[(key, h)]['nav'], 5)
    d['Z · 沪深300'] = np.round(nav_base, 5)
    for key in ('A', BEST_KEY):
        d[f'{key} 持仓只数'] = res[(key, h)]['hold_cnt'].astype(int)
    d[f'{BEST_KEY} 当日收益(%)'] = np.round(res[(BEST_KEY, h)]['net'] * 100, 3)
    return pd.DataFrame(d)


def build_readme(panel, res, meta, horizons, cost, refresh=False):
    """回测说明表：口径、规则、参数、S1 关键指标与口径提示。"""
    h = horizons[0]
    r = res[(BEST_KEY, h)]
    m = E.perf_metrics(r['nav'], panel.calendar, r['years'], r['hold_cnt'])
    rows = [
        ('回测对象', load_config().get(
            'readme_object',
            '三因子买点信号（F1 趋势强弱=vol60 / F2 趋势方向=mom60 / '
            'F3 多空力量=MACD(30,89,9) hist）筛选出的「最优组合」')),
        ('信号来源', f'{os.path.relpath(S.SIG_PKL, S.ROOT_DIR)}'
                 '（由 rebuild_signals.py + enrich_signals.py 在 '
                 f'{config.TABLE_BACKWARD_DAILY} 上重扫并富化生成）'),
        ('价格来源', f'MySQL {config.TABLE_BACKWARD_DAILY} 后复权'
                 '（open/close），信号日收盘价建仓、T+N 收盘价平仓'),
        ('价格快照', f'{"强制重拉" if refresh else "命中本地缓存"}'
                 f' · {os.path.basename(S.PX_CACHE)}'
                 + (f' · 文件时间 {_mtime(S.PX_CACHE)}'
                    if os.path.isfile(S.PX_CACHE) else '')),
        ('建仓规则', '同一只股票在持有期 [T, T+N] 内只建仓一次（去重）；'
                 '期满后的下一个信号日才允许再次建仓'),
        ('持有期', f'{h} 个交易日（可在 --horizons 中切换 20/30/40/60）'),
        ('权重', '每个交易日对所有在持标的等权（日度再平衡，等价于每日把'
               '全部资金均分到当前持仓）'),
        ('交易成本', f'建仓 0.10% + 平仓 0.10% = 双边 {cost:.2%}'
                 + ('（已关闭）' if cost == 0 else '')),
        ('基准', '沪深300（同期买入持有）'),
        ('回测区间', f'{panel.calendar[0].date()} ~ {panel.calendar[-1].date()}'
                 f'（{len(panel.calendar)} 个交易日 / {r["years"]:.2f} 年）'),
        ('样本股票', f'{len(panel.codes)} 只（信号池涉及的全部个股）'),
        ('', ''),
        (f'── 最优组合 {BEST_KEY} 口径 ──',
         combo_readme(BEST_KEY) or '流通市值 nmc < 20 亿  且  '
         '25% ≤ 60日年化波动 vol60 < 35%  且  '
         '−10% ≤ 60日动量 mom60 < 0'),
        ('S1 原始信号', f'{r["n_sig"]} 条'),
        ('S1 去重交易', f'{r["n_trade"]} 笔（因数据末端不足 N 日剔除 {r["n_skip"]} 条）'),
        ('S1 涉及股票', f'{r["n_stock"]} 只'),
        ('S1 平均持仓', f'{r["avg_hold"]:.2f} 只 / 最大 {r["max_hold"]} 只 / '
                    f'有持仓 {r["active_days"]} 天'),
        ('S1 总收益', f'{m["总收益(%)"]:.2f}%'),
        ('S1 年化收益', f'{m["年化收益(%)"]:.2f}%'),
        ('S1 最大回撤', f'{m["最大回撤(%)"]:.2f}%'),
        ('S1 夏普', f'{m["夏普"]:.2f}'),
        ('S1 日均收益', f'{m["日均收益(bp)"]:.2f} bp'),
        ('', ''),
        ('⚠ 口径提示 1', '本口径为「等权日度组合」，空仓日收益记 0，'
                    '因此年化/夏普反映的是「资金实际在策略里的表现」，'
                    '而非只在持仓日的胜率。'),
        ('⚠ 口径提示 2', '最优组合 S1 信号稀疏（平均持仓仅 '
                    f'{r["avg_hold"]:.2f} 只），资金利用率低；'
                    '若要组合化实盘，宜用组合 A 或放宽阈值。'),
        ('⚠ 口径提示 3', '原报告《600354_三因子信号日线收益规律.md》中的 '
                    '20 日 +3.x% 是「信号级平均收益」，'
                    '本表「交易级」列才是去重后可按笔执行的收益。'),
        ('⚠ 口径提示 4', '样本内回测，最优组合经过多重比较筛选，'
                    '存在选择性偏差，请以「参数敏感性」表的稳健性为准。'),
        ('⚠ 口径提示 5', '未计冲击成本与涨跌停不可成交；ALL 组合几乎复制'
                    '沪深300，仅作对照，不可直接复刻。'),
    ]
    return pd.DataFrame(rows, columns=['项目', '内容'])



