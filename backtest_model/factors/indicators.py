# -*- coding: utf-8 -*-
"""
==============================================================================
factors.indicators —— 技术指标计算（参数化）
==============================================================================

按配置参数计算信号侧所需指标，结果与主工程口径逐位一致：

* SMA(ma_short) / SMA(ma_long)         —— 收盘价滚动均值（min_periods=1）
* MACD(macd_fast, macd_slow, macd_signal)：ema 递推（y0=x0），
  dif = ema_fast - ema_slow；dea = ema(dif)；macd = (dif - dea) * 2

参数来自 `config/signal.json` 的 `indicators` 段。
"""

import numpy as np
import pandas as pd


def calc_ema(prices, period):
    """EMA 递推实现（y0 = x0），与主工程 `calculate_ema` 完全一致。"""
    prices = np.asarray(prices, dtype=np.float64)
    if prices.size == 0:
        return prices
    alpha = 2.0 / (period + 1)
    ema = np.empty_like(prices)
    ema[0] = prices[0]
    for i in range(1, prices.size):
        ema[i] = prices[i] * alpha + ema[i - 1] * (1 - alpha)
    return ema


def calculate_indicators(df, macd=(30, 89, 9), ma=(7, 21)):
    """为 df 追加 dif / dea / macd / ma7 / ma21 五列，返回新的 DataFrame。

    Args:
        df:  含 `close_price` 的行情 DataFrame。
        macd: (fast, slow, signal)。
        ma:   (short, long)。
    """
    if df.empty:
        return df

    fast, slow, signal = macd
    ma_s, ma_l = ma
    close = df['close_price'].to_numpy(np.float64)
    n = len(df)

    if n >= slow:
        dif = calc_ema(close, fast) - calc_ema(close, slow)
        dea = calc_ema(dif, signal)
        macd_bar = (dif - dea) * 2.0
    else:
        dif = np.full(n, np.nan)
        dea = np.full(n, np.nan)
        macd_bar = np.full(n, np.nan)

    close_s = pd.Series(close)
    ma7 = close_s.rolling(window=ma_s, min_periods=1).mean().to_numpy()
    ma21 = close_s.rolling(window=ma_l, min_periods=1).mean().to_numpy()

    data = {col: df[col].to_numpy(copy=False) for col in df.columns}
    data['dif'] = dif
    data['dea'] = dea
    data['macd'] = macd_bar
    data['ma7'] = ma7
    data['ma21'] = ma21
    return pd.DataFrame(data)
