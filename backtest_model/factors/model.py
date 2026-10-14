# -*- coding: utf-8 -*-
"""
==============================================================================
factors.model —— 三因子判定模型（由配置 + 已注册闸门组装）
==============================================================================

`ThreeFactorModel` 从 `config/signal.json` 读取指标参数与闸门清单，按顺序
运行已启用的闸门（默认 F1 → F2 → F3），任一失败即返回失败原因。其
`analyze_pattern()` 返回值与主工程 `ThreeFactorModelAnalyzer.analyze_pattern`
口径一致（关键字段 `pattern_detected`）。

新增 / 替换闸门：改 `config/signal.json` 并在 `factors/gates/` 注册实现即可，
本文件与扫描 / 回测代码无需改动。
"""

from .indicators import calculate_indicators
from .gates import build_gates
from .registry import load_signal_config


class ThreeFactorModel:
    """可配置的三因子判定模型。"""

    def __init__(self, signal_config=None):
        cfg = signal_config or load_signal_config()
        self.cfg = cfg
        ind = dict(cfg.get('indicators', {}))
        self.indicator_params = ind
        self.macd = (ind.get('macd_fast', 30), ind.get('macd_slow', 89),
                     ind.get('macd_signal', 9))
        self.ma = (ind.get('ma_short', 7), ind.get('ma_long', 21))
        self.min_bars = int(cfg.get('min_bars', 5))
        self.gates = build_gates(ind, cfg.get('gates', []))

    @property
    def macd_fast(self):
        return self.macd[0]

    @property
    def macd_slow(self):
        return self.macd[1]

    @property
    def macd_signal(self):
        return self.macd[2]

    @property
    def ma_short(self):
        return self.ma[0]

    @property
    def ma_long(self):
        return self.ma[1]

    def calculate_all_indicators(self, df):
        """计算 MACD + MA 指标（返回新 DataFrame）。"""
        return calculate_indicators(df, self.macd, self.ma)

    def analyze_pattern(self, df):
        """完整三因子判定。

        Returns:
            dict：`pattern_detected`（bool）、`fail_reason`（str）、
            各闸门明细（键为闸门小写名，如 'f1'）、`details`（当前值快照）。
        """
        result = {
            'pattern_detected': False,
            'fail_reason': '',
            'details': {
                'current_close': None, 'current_ma7': None, 'current_ma21': None,
                'current_dif': None, 'current_dea': None, 'current_macd': None,
                'trade_date': None,
            },
        }
        need = self.ma_long + self.min_bars
        if df.empty or len(df) < need:
            result['fail_reason'] = f'数据不足（需要至少{need}条）'
            return result

        df = self.calculate_all_indicators(df)
        if 'macd' not in df.columns or 'ma21' not in df.columns:
            result['fail_reason'] = '指标计算失败'
            return result

        latest = df.iloc[-1]
        d = result['details']
        d['current_close'] = float(latest['close_price'])
        d['current_ma7'] = float(latest.get('ma7', 0))
        d['current_ma21'] = float(latest.get('ma21', 0))
        d['current_dif'] = float(latest.get('dif', 0))
        d['current_dea'] = float(latest.get('dea', 0))
        d['current_macd'] = float(latest.get('macd', 0))
        d['trade_date'] = latest['trade_date']

        for gate in self.gates:
            passed, detail = gate.check(df)
            result[gate.key.lower()] = detail
            if not passed:
                sub = ' | '.join(v for k, v in detail.items()
                                 if k.endswith('_detail'))
                result['fail_reason'] = f'{gate.key}失败: {sub}'
                return result

        result['pattern_detected'] = True
        return result
