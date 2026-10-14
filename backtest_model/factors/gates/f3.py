# -*- coding: utf-8 -*-
"""
==============================================================================
factors.gates.f3 —— 因子3：MACD 红绿柱的动能关系（多空力量）
==============================================================================

* F3-1: MACD 柱线由绿翻红（最近 R 根K线内从负转正，且当前为红柱）
* F3-2: 红柱持续放大（连续 K 日放大）
* F3-3: 最近 W 个交易日内 DIF 由下向上穿过 DEA（金叉）
* F3-4: 金叉位置在零轴附近或零轴下方（DIF<0 或 DEA<0，或 |DIF|/|DEA|<0.5）
* F3-5: 无顶背离（股价创阶段新高时 MACD 柱同步放大）

参数（config/signal.json → gates[F3].params）：f3_red_bar_days /
f3_increasing_days / f3_golden_cross_window。
"""

import numpy as np

from .base import GateFactor, register_gate


@register_gate
class GateF3(GateFactor):
    key = 'F3'
    label = '多空力量（MACD 红绿柱）'

    def check(self, df):
        p = self.params
        red_bar_days = p.get('f3_red_bar_days', 3)
        inc_days = p.get('f3_increasing_days', 2)
        gc_window = p.get('f3_golden_cross_window', 10)
        macd_slow = p.get('macd_slow', 89)

        detail = {'passed': False, 'f3_1': False, 'f3_2': False,
                  'f3_3': False, 'f3_4': False, 'f3_5': False,
                  'f3_1_detail': '', 'f3_2_detail': '', 'f3_3_detail': '',
                  'f3_4_detail': '', 'f3_5_detail': '',
                  'dif_dea_golden_cross_idx': None}
        if (df.empty or 'macd' not in df.columns
                or 'dif' not in df.columns or 'dea' not in df.columns):
            detail['f3_1_detail'] = 'MACD指标数据不足'
            return False, detail
        if len(df) < macd_slow + 5:
            detail['f3_1_detail'] = f'数据不足（需要至少{macd_slow + 5}条）'
            return False, detail

        macd = df['macd'].values.astype(np.float64)
        dif = df['dif'].values.astype(np.float64)
        dea = df['dea'].values.astype(np.float64)
        close = df['close_price'].values.astype(np.float64)
        n = len(df)

        # F3-1: 由绿翻红
        last_macd = macd[-red_bar_days:]
        turned_positive = any(last_macd[i - 1] <= 0 and last_macd[i] > 0
                              for i in range(1, len(last_macd)))
        all_positive = np.all(last_macd > 0)
        current_is_red = macd[-1] > 0
        if (turned_positive or all_positive) and current_is_red:
            detail['f3_1'] = True
            detail['f3_1_detail'] = (
                f"MACD柱线已由绿翻红，当前为红柱 ✅ "
                f"(最近{red_bar_days}日: {', '.join([f'{v:.4f}' for v in last_macd])})")
        else:
            detail['f3_1_detail'] = (
                f"MACD柱线未满足由绿翻红条件 ❌ "
                f"(最近{red_bar_days}日: {', '.join([f'{v:.4f}' for v in last_macd])})")
            return False, detail

        # F3-2: 红柱持续放大（连续 inc_days 日放大）
        if n >= inc_days + 1:
            red_increasing = bool(np.all(macd[-inc_days - 1:-1] < macd[-inc_days:]))
        else:
            red_increasing = True
        tail = macd[-(inc_days + 1):]
        tail_txt = ' → '.join(f'{v:.4f}' for v in tail)
        if red_increasing:
            detail['f3_2'] = True
            detail['f3_2_detail'] = f'红柱持续放大 ✅ ({tail_txt})'
        else:
            detail['f3_2_detail'] = f'红柱未持续放大 ❌ ({tail_txt})'
            return False, detail

        # F3-3: DIF 金叉 DEA
        gc = None
        for i in range(max(macd_slow, n - gc_window), n):
            if dif[i - 1] <= dea[i - 1] and dif[i] > dea[i]:
                gc = i
                break
        if gc is not None:
            detail['f3_3'] = True
            detail['dif_dea_golden_cross_idx'] = gc
            detail['f3_3_detail'] = (
                f"最近{gc_window}日内DIF金叉DEA ✅ "
                f"(位置: 第{gc + 1}日, DIF={dif[gc]:.4f}, DEA={dea[gc]:.4f})")
        else:
            detail['f3_3_detail'] = f'最近{gc_window}日内未检测到DIF金叉DEA ❌'
            return False, detail

        # F3-4: 金叉位置在零轴附近或零轴下方
        dif_c = dif[gc]
        dea_c = dea[gc]
        below_zero = dif_c < 0 or dea_c < 0
        near_zero = abs(dif_c) < 0.5 or abs(dea_c) < 0.5
        if below_zero or near_zero:
            detail['f3_4'] = True
            detail['f3_4_detail'] = (
                f"金叉位置合理 ✅ (DIF={dif_c:.4f}, DEA={dea_c:.4f}, "
                f"位于{'零轴下方' if below_zero else '零轴附近'})")
        else:
            detail['f3_4_detail'] = (
                f"金叉位置偏高 ❌ (DIF={dif_c:.4f}, DEA={dea_c:.4f}, 远离零轴上方)")
            return False, detail

        # F3-5: 无顶背离
        lookback_div = min(60, n - 1)
        rc = close[-lookback_div:]
        rm = macd[-lookback_div:]
        max_idx = int(np.argmax(rc))
        no_div = True
        div_txt = ''
        if max_idx >= len(rc) - 10:
            exclude = set(range(max(0, max_idx - 2), min(len(rc), max_idx + 3)))
            sp_idx, sp_price = -1, 0
            for i in range(len(rc)):
                if i in exclude:
                    continue
                if rc[i] > sp_price:
                    sp_price = rc[i]
                    sp_idx = i
            if sp_idx >= 0:
                if rm[max_idx] < rm[sp_idx]:
                    no_div = False
                    div_txt = (f"检测到顶背离 ❌: 股价 {sp_price:.2f}→{rc[max_idx]:.2f} (新高), "
                               f"但MACD柱 {rm[sp_idx]:.4f}→{rm[max_idx]:.4f} (减弱)")
                else:
                    div_txt = (f"无顶背离 ✅: 股价新高时MACD柱同步放大 "
                               f"({rm[sp_idx]:.4f}→{rm[max_idx]:.4f})")
            else:
                div_txt = '未找到次高点，无法检测背离 ✅'
        else:
            div_txt = '近期股价未创新高，无顶背离风险 ✅'

        detail['f3_5_detail'] = div_txt
        if no_div:
            detail['f3_5'] = True
        else:
            return False, detail

        detail['passed'] = True
        return True, detail
