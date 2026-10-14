# -*- coding: utf-8 -*-
"""
==============================================================================
数据层 —— 信号池 / 后复权价格 / 沪深300 / 价格面板
==============================================================================

* 信号池   : `data/sig_all_horizons.pkl`（工程内重建资产，由 `rebuild_signals.py`
             + `enrich_signals.py` 在 `backward_tdx_daily` 上重扫富化）
* 价格     : MySQL `TABLE_BACKWARD_DAILY`（后复权 open/close），本地 parquet 缓存
* 基准     : `data/idx_000300.pkl`（沪深300 收盘）
"""

import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pymysql

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config                                                # noqa: E402
from . import settings as S                                  # noqa: E402
from .factors import numeric_columns                         # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# 信号池
# ═════════════════════════════════════════════════════════════════════════

def load_signals():
    """加载信号底表，统一因子为数值型并补出 year / _sig_ts 列。"""
    if not os.path.isfile(S.SIG_PKL):
        raise FileNotFoundError(
            f'缺少信号底表: {S.SIG_PKL}\n'
            f'请从原工程复制 sig_all_horizons.pkl 到 {S.DATA_DIR}')
    d = pd.read_pickle(S.SIG_PKL)
    d = d.copy()
    d['stock_code'] = d['stock_code'].astype(str).str.zfill(6)
    d['signal_date'] = d['signal_date'].astype(str)
    for c in numeric_columns():
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['year'] = d['signal_date'].str[:4].astype(int)
    d['_sig_ts'] = pd.to_datetime(d['signal_date'], errors='coerce')
    return d


# ═════════════════════════════════════════════════════════════════════════
# 沪深300 基准
# ═════════════════════════════════════════════════════════════════════════

def load_index():
    """加载沪深300 收盘（返回 DataFrame: trade_date, idx_close）。"""
    if not os.path.isfile(S.IDX_PKL):
        raise FileNotFoundError(f'缺少指数底表: {S.IDX_PKL}')
    d, c = pd.read_pickle(S.IDX_PKL)
    idx = pd.DataFrame({
        'trade_date': pd.to_datetime([str(int(x)) for x in d], format='%Y%m%d'),
        'idx_close': np.asarray(c, dtype='float64'),
    })
    return idx.sort_values('trade_date').reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════════════
# 后复权价格（MySQL + parquet 缓存）
# ═════════════════════════════════════════════════════════════════════════

def fetch_prices(codes, start=S.DEF_START, refresh=False, chunk=250):
    """从 `config.TABLE_BACKWARD_DAILY` 拉取后复权 open/close。

    结果缓存到 `data/_cache/bt_daily_px.parquet`；当缓存已覆盖全部请求代码时
    直接命中缓存（`refresh=True` 强制重拉）。
    """
    if os.path.isfile(S.PX_CACHE) and not refresh:
        px = pd.read_parquet(S.PX_CACHE)
        have = set(px['stock_code'].unique())
        if set(codes).issubset(have):
            print(f'[价格] 命中缓存 {S.PX_CACHE}  {len(px):,} 行 / {len(have)} 只')
            return px
        print('[价格] 缓存缺少部分股票，重新拉取')

    codes = sorted(set(codes))
    table = config.TABLE_BACKWARD_DAILY
    cn = pymysql.connect(**config.get_db_config(),
                         cursorclass=pymysql.cursors.DictCursor)
    cur = cn.cursor()
    q = (f"SELECT stock_code, trade_date, open_price, close_price "
         f"FROM {table} WHERE trade_date >= %s AND stock_code IN ({{}})")
    frames = []
    t0 = datetime.now()
    nblk = (len(codes) - 1) // chunk + 1
    for i in range(0, len(codes), chunk):
        ch = codes[i:i + chunk]
        cur.execute(q.format(','.join(['%s'] * len(ch))), [start] + ch)
        f = pd.DataFrame(cur.fetchall())
        if not f.empty:
            frames.append(f)
        print(f'  [价格] 块 {i // chunk + 1:>2}/{nblk}  {len(f):>6} 行  '
              f'累计 {sum(len(x) for x in frames):>8,}', flush=True)
    cn.close()

    if not frames:
        raise RuntimeError(f'未从 {table} 拉到任何价格数据（start={start}）')

    px = pd.concat(frames, ignore_index=True)
    px['stock_code'] = px['stock_code'].astype(str).str.zfill(6)
    px['trade_date'] = pd.to_datetime(px['trade_date'])
    for c in ('open_price', 'close_price'):
        px[c] = pd.to_numeric(px[c], errors='coerce').astype('float64')
    px = px.dropna(subset=['close_price'])
    px = px.sort_values(['stock_code', 'trade_date']).reset_index(drop=True)
    os.makedirs(S.CACHE_DIR, exist_ok=True)
    px.to_parquet(S.PX_CACHE, index=False)
    print(f'[价格] 已缓存 {S.PX_CACHE}  {len(px):,} 行 / '
          f'{px["stock_code"].nunique()} 只  用时 {(datetime.now() - t0).seconds}s')
    return px


# ═════════════════════════════════════════════════════════════════════════
# 价格面板
# ═════════════════════════════════════════════════════════════════════════

class PanelData:
    """后复权价格宽表 + 交易日历 + 个股有效交易日位置索引（停牌用前值填充）。"""

    def __init__(self, px, calendar):
        self.calendar = pd.DatetimeIndex(calendar)
        self.cal_pos = {d: i for i, d in enumerate(self.calendar)}

        pc = px.pivot(index='trade_date', columns='stock_code',
                      values='close_price').reindex(self.calendar)
        po = px.pivot(index='trade_date', columns='stock_code',
                      values='open_price').reindex(self.calendar)
        self.codes = [str(c) for c in pc.columns]
        self.col = {c: i for i, c in enumerate(self.codes)}

        raw = pc.to_numpy('float64')
        self.valid = ~np.isnan(raw)
        self.Pclose = pc.ffill().to_numpy('float64')
        self.Popen = po.ffill().to_numpy('float64')

        r = np.zeros_like(self.Pclose)
        with np.errstate(invalid='ignore', divide='ignore'):
            r[1:] = self.Pclose[1:] / self.Pclose[:-1] - 1.0
        self.R = np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)

        # 每只股票「有报价」的日历位置（升序），用于停牌安全的 N 日推进
        self.pos_seq = [np.flatnonzero(self.valid[:, j])
                        for j in range(len(self.codes))]


def build_panel(signals, start=S.DEF_START, refresh=False):
    """一站式构建价格面板。

    Args:
        signals: 信号底表（需含 `stock_code`）。
        start:   价格起始日。
        refresh: 为 True 时强制重拉价格缓存（数据更新后必须置 True）。

    Returns:
        (panel, index_df, nav_base) —— panel 为 `PanelData`；
        交易取自沪深300 的交易日，并截取到 `start` ~ 价格数据末日；
        nav_base 为归一化到 1.0 的沪深300 净值。
    """
    px = fetch_prices(signals['stock_code'].unique(), start, refresh=refresh)
    idx = load_index()
    cal = idx.loc[(idx['trade_date'] >= start) &
                  (idx['trade_date'] <= px['trade_date'].max()),
                  'trade_date'].reset_index(drop=True)
    panel = PanelData(px, cal)
    base = idx.set_index('trade_date')['idx_close'].reindex(cal).ffill()
    nav_base = (base / base.iloc[0]).to_numpy(dtype='float64')
    return panel, idx, nav_base

