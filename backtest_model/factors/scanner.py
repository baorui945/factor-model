# -*- coding: utf-8 -*-
"""
==============================================================================
factors.scanner —— 滚动扫描：对单只股票逐日应用三因子模型产出信号
==============================================================================

从第 `scan_window` 个交易日起，逐日以窗口末尾为「当前交易日」送模型判定；
命中则记录该信号与后续 N 日（default 20/30/40/60）收益。与主工程
`ThreeFactorBacktester.backtest_stock` 口径一致。
"""

import numpy as np
import pandas as pd


def scan_stock(model, df, stock_code='', stock_name='', scan_window=360,
               forward_periods=(20, 30, 40, 60)):
    """扫描单只股票，返回信号列表（每项含 stock_code/name/date/close/returns）。"""
    signals = []
    if df is None or df.empty:
        return signals

    n = len(df)
    max_fwd = max(forward_periods)
    if n < scan_window + max_fwd:
        return signals

    close = df['close_price'].values.astype(np.float64)
    dates = df['trade_date'].values
    name = stock_name or str(df.iloc[-1].get('stock_name', '') or stock_code)

    for i in range(scan_window - 1, n - max_fwd):
        window = df.iloc[i - scan_window + 1: i + 1]
        if not model.analyze_pattern(window).get('pattern_detected'):
            continue
        entry_close = float(close[i])
        if entry_close <= 0:
            continue
        returns = {p: float(close[i + p]) / entry_close - 1.0
                   for p in forward_periods}
        signals.append({
            'stock_code': stock_code,
            'stock_name': name,
            'signal_date': pd.Timestamp(dates[i]).strftime('%Y-%m-%d'),
            'signal_close': entry_close,
            'returns': returns,
        })
    return signals
