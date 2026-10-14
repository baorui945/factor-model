# -*- coding: utf-8 -*-
"""
==============================================================================
factors.gates.f2 —— 因子2：MA7 与 MA21 的排列关系（趋势方向）
==============================================================================

* F2-1: 最近 W 个交易日内 MA7 由下向上穿过 MA21（金叉）
* F2-2: 金叉后最近 K 个交易日 MA7 持续运行在 MA21 上方
* F2-3: 最新 MA7 / MA21 均为向上斜率
* F2-4: 金叉后 MA7 与 MA21 的差值逐步扩大

参数（config/signal.json → gates[F2].params）：f2_golden_cross_window /
f2_above_ma_days / f2_slope_check_days。
"""

import numpy as np

from .base import GateFactor, register_gate


@register_gate
class GateF2(GateFactor):
    key = 'F2'
    label = '趋势方向（MA7/MA21 排列）'

    def check(self, df):
        p = self.params
        gc_window = p.get('f2_golden_cross_window', 10)
        above_days = p.get('f2_above_ma_days', 5)
        ma_long = p.get('ma_long', 21)

        detail = {'passed': False, 'f2_1': False, 'f2_2': False,
                  'f2_3': False, 'f2_4': False,
                  'f2_1_detail': '', 'f2_2_detail': '',
                  'f2_3_detail': '', 'f2_4_detail': '',
                  'golden_cross_idx': None}
        if df.empty or len(df) < ma_long + gc_window:
            detail['f2_1_detail'] = '数据不足'
            return False, detail

        ma7 = df['ma7'].values.astype(np.float64)
        ma21 = df['ma21'].values.astype(np.float64)
        n = len(df)

        # F2-1: 金叉检测
        gc = None
        for i in range(max(ma_long, n - gc_window), n):
            if ma7[i - 1] <= ma21[i - 1] and ma7[i] > ma21[i]:
                gc = i
                break
        if gc is not None:
            detail['f2_1'] = True
            detail['golden_cross_idx'] = gc
            detail['f2_1_detail'] = (
                f'在最近{gc_window}日内检测到MA7金叉MA21 (位置: 第{gc + 1}日) ✅')
        else:
            detail['f2_1_detail'] = f'最近{gc_window}日内未检测到MA7金叉MA21 ❌'
            return False, detail

        # F2-2: 金叉后持续在 MA21 上方
        if n - gc >= above_days:
            all_above = np.all(ma7[-above_days:] > ma21[-above_days:])
        else:
            all_above = np.all(ma7[gc:] > ma21[gc:])
        if all_above:
            detail['f2_2'] = True
            detail['f2_2_detail'] = f'金叉后最近{above_days}个交易日MA7持续在MA21上方 ✅'
        else:
            detail['f2_2_detail'] = f'金叉后最近{above_days}个交易日MA7未持续在MA21上方 ❌'
            return False, detail

        # F2-3: 斜率向上
        ma7_up = ma7[-1] > ma7[-2] if n >= 2 else False
        ma21_up = ma21[-1] > ma21[-2] if n >= 2 else False
        detail['f2_3_detail'] = (f"MA7向上斜率: {'✅' if ma7_up else '❌'}, "
                                 f"MA21向上斜率: {'✅' if ma21_up else '❌'}")
        if ma7_up and ma21_up:
            detail['f2_3'] = True
        else:
            return False, detail

        # F2-4: 差值逐步扩大
        if gc < n - 1:
            spread = (ma7[gc:] - ma21[gc:]) / ma21[gc:]
            if len(spread) >= 2:
                expanding = spread[-1] > spread[0]
                inc_ratio = np.sum(np.diff(spread) > 0) / max(1, len(spread) - 1)
                expanding = expanding and inc_ratio >= 0.5
            else:
                expanding = True
        else:
            expanding = True
        if expanding:
            detail['f2_4'] = True
            detail['f2_4_detail'] = '金叉后MA7与MA21差值逐步扩大 ✅'
        else:
            detail['f2_4_detail'] = '金叉后MA7与MA21差值未扩大，或出现收窄 ❌'
            return False, detail

        detail['passed'] = True
        return True, detail
