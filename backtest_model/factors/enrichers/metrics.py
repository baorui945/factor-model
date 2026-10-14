# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.metrics —— 富化派生量（上市板 / 60日波动 / 60日动量 / 大盘环境）
==============================================================================

口径与 `F:\\quantTrade\\analyzers\\three_factor_segment_analysis.py` **逐字一致**：

* ``board_of``      代码前缀 → 上市板
* ``compute_metrics`` 60 日年化波动 vol60 与 60 日动量 mom60（逐位复刻原公式，
                     以保证重建的 ``sig_all_horizons.pkl`` 与旧版完全对齐）
* ``index_regime``  沪深300 相对 MA60 偏离 / 60 日动量

原公式（原脚本 `build_features` 内）::

    lo = max(0, p - 60)
    seg = closes[lo:p + 1]
    if len(seg) >= 21:                       # 至少 20 个对数收益
        rr = np.diff(np.log(seg))
        vol60 = rr.std(ddof=1) * np.sqrt(252.0)
    if lo < p:
        mom60 = closes[p] / closes[lo] - 1.0
"""

import numpy as np

TRADING_DAYS = 252.0
VOL_WINDOW = 60
VOL_MIN_OBS = 21          # len(seg) >= 21


def board_of(code):
    """按代码前缀判定上市板。"""
    code = str(code)
    if code.startswith(('688', '689')):
        return '科创板'
    if code.startswith(('300', '301')):
        return '创业板'
    if code.startswith(('43', '83', '87', '88', '92')):
        return '北交所'
    if code.startswith(('600', '601', '603', '605')):
        return '沪市主板'
    if code.startswith(('000', '001', '002', '003')):
        return '深市主板'
    return '其他'


def compute_metrics(closes):
    """对整条前复权收盘序列计算 vol60 / mom60（逐位复刻原公式）。

    Args:
        closes: 前复权收盘价序列（**float32** 来自 `network.fetch_kline`，
                或已落库回读的同精度序列）。

    Returns:
        ``(vol60, mom60)`` 两个 float64 数组，长度与 ``closes`` 相同，
        未定义处为 NaN。
    """
    c = np.asarray(closes, dtype=np.float64)
    n = len(c)
    vol = np.full(n, np.nan, dtype=np.float64)
    mom = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return vol, mom

    logc = np.log(c)                             # 原式 np.log(seg) 的等价预处理
    with np.errstate(invalid='ignore', divide='ignore'):
        for p in range(n):
            lo = p - VOL_WINDOW
            if lo < 0:
                lo = 0
            if p - lo + 1 >= VOL_MIN_OBS:
                rr = logc[lo + 1:p + 1] - logc[lo:p]   # == np.diff(np.log(seg))
                vol[p] = rr.std(ddof=1) * np.sqrt(TRADING_DAYS)
            if lo < p:
                mom[p] = c[p] / c[lo] - 1.0
    return vol, mom


def metric_at(closes, pos):
    """只算某个位置的 (vol60, mom60)（**完全不预计算整条序列**，用于富化快路径）。

    ``pos`` 为 ``closes`` 中的下标；口径与 `compute_metrics` 在 ``pos`` 处一致。
    """
    c = np.asarray(closes, dtype=np.float64)
    p = int(pos)
    lo = p - VOL_WINDOW
    if lo < 0:
        lo = 0
    vol = np.nan
    mom = np.nan
    if p - lo + 1 >= VOL_MIN_OBS:
        rr = np.diff(np.log(c[lo:p + 1]))
        vol = float(rr.std(ddof=1) * np.sqrt(TRADING_DAYS))
    if lo < p:
        mom = float(c[p] / c[lo] - 1.0)
    return vol, mom


def index_regime(idx_kl, day_ints):
    """沪深300 相对 MA60 的偏离 + 60 日动量。

    Args:
        idx_kl:   ``(dates, closes)`` 或 None。
        day_ints: 目标交易日（YYYYMMDD 整数数组）。

    Returns:
        ``(dev, mom)``，长度与 ``day_ints`` 相同。
    """
    if idx_kl is None:
        n = len(day_ints)
        return np.full(n, np.nan), np.full(n, np.nan)
    idates, iclose = idx_kl
    pos = np.searchsorted(idates, day_ints)
    pos_c = np.clip(pos, 0, len(idates) - 1)
    valid = idates[pos_c] == day_ints

    dev = np.full(len(day_ints), np.nan)
    mom = np.full(len(day_ints), np.nan)
    for i in range(len(day_ints)):
        if not valid[i]:
            continue
        p = int(pos_c[i])
        lo = max(0, p - 59)
        dev[i] = iclose[p] / iclose[lo:p + 1].mean() - 1.0
        lo60 = max(0, p - 60)
        mom[i] = iclose[p] / iclose[lo60] - 1.0
    return dev, mom
