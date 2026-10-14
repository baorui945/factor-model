# -*- coding: utf-8 -*-
"""
==============================================================================
factors.gates.f1 —— 因子1：K线与均线的位置关系（趋势强弱）
==============================================================================

* F1-1: 最近 N 根K线收盘价同时站上 MA7 与 MA21
* F1-2: 最近 M 根K线内回调最低价未跌破 MA21 的阈值比例
* F1-3: 最新收盘价距 MA21 的涨幅落在 [min, max] 区间

参数（config/signal.json → gates[F1].params）：f1_close_above_ma_days /
f1_lookback_days / f1_ma21_allow_deviation / f1_close_to_ma21_min / _max。
"""

import numpy as np

from .base import GateFactor, register_gate


@register_gate
class GateF1(GateFactor):
    key = 'F1'
    label = '趋势强弱（K线与均线位置）'

    def check(self, df):
        p = self.params
        above_days = p.get('f1_close_above_ma_days', 3)
        lookback_days = p.get('f1_lookback_days', 10)
        dev = p.get('f1_ma21_allow_deviation', 0.98)
        cmin = p.get('f1_close_to_ma21_min', 0.03)
        cmax = p.get('f1_close_to_ma21_max', 0.15)
        ma_long = p.get('ma_long', 21)

        detail = {'passed': False, 'f1_1': False, 'f1_2': False, 'f1_3': False,
                  'f1_1_detail': '', 'f1_2_detail': '', 'f1_3_detail': ''}
        if df.empty or len(df) < ma_long + above_days:
            detail['f1_1_detail'] = '数据不足'
            return False, detail

        close = df['close_price'].values.astype(np.float64)
        ma7 = df['ma7'].values.astype(np.float64)
        ma21 = df['ma21'].values.astype(np.float64)
        low = df['low_price'].values.astype(np.float64)
        n = len(df)

        # F1-1
        last_close = close[-above_days:]
        above_ma7 = np.all(last_close > ma7[-above_days:])
        above_ma21 = np.all(last_close > ma21[-above_days:])
        if above_ma7 and above_ma21:
            detail['f1_1'] = True
            detail['f1_1_detail'] = f'最近{above_days}日收盘价均站上MA7和MA21 ✅'
        else:
            detail['f1_1_detail'] = (
                f'最近{above_days}日收盘价未同时站上均线 '
                f"(MA7:{'✅' if above_ma7 else '❌'} MA21:{'✅' if above_ma21 else '❌'})")
            return False, detail

        # F1-2
        lookback = min(lookback_days, n)
        low_lb = low[-lookback:]
        ma21_lb = ma21[-lookback:]
        below = any(low_lb[i] < ma21_lb[i] * dev for i in range(lookback))
        if not below:
            detail['f1_2'] = True
            detail['f1_2_detail'] = (
                f'最近{lookback}日内回调最低价均未跌破MA21的{dev:.0%}阈值 '
                f'(最低比={np.min(low_lb / ma21_lb):.4f}) ✅')
        else:
            detail['f1_2_detail'] = f'最近{lookback}日内有跌破MA21的{dev:.0%}阈值的情况 ❌'
            return False, detail

        # F1-3
        latest_close = close[-1]
        latest_ma21 = ma21[-1]
        if latest_ma21 > 0:
            pct = (latest_close - latest_ma21) / latest_ma21
            if cmin <= pct <= cmax:
                detail['f1_3'] = True
                detail['f1_3_detail'] = (
                    f'收盘价距MA21涨幅={pct * 100:.2f}% '
                    f'(在{cmin * 100:.0f}%~{cmax * 100:.0f}%区间内) ✅')
            else:
                detail['f1_3_detail'] = (
                    f'收盘价距MA21涨幅={pct * 100:.2f}% '
                    f'(不在{cmin * 100:.0f}%~{cmax * 100:.0f}%区间内) ❌')
                return False, detail
        else:
            detail['f1_3_detail'] = 'MA21为0，无法计算 ❌'
            return False, detail

        detail['passed'] = True
        return True, detail
