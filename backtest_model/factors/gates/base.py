# -*- coding: utf-8 -*-
"""
==============================================================================
factors.gates.base —— 判定型闸门（Gate）基类 + 注册表
==============================================================================

闸门（Gate）：输入一个已算好指标的行情窗口 DataFrame，输出
``(passed: bool, detail: dict)``。三因子模型的 F1 / F2 / F3 即三个闸门。

新增闸门::

    from backtest_model.factors.gates import GateFactor, register_gate

    @register_gate
    class GateF4(GateFactor):
        key = 'F4'
        label = '自定义闸门'
        def check(self, df):
            ...
            return True, {'passed': True, 'f4_1_detail': '...'}

再在 `config/signal.json` 的 `gates` 段加入 ``{"key": "F4", "enabled": true,
"params": {...}}`` 即可，扫描 / 回测逻辑无需改动。
"""

_REGISTRY = {}


class GateFactor:
    """判定型闸门基类。

    Attributes:
        key:   闸门键（如 'F1'）。
        label: 中文名（说明用）。
        params: 合并后的参数字典（指标参数 + 本闸门专属参数）。
    """

    key = ''
    label = ''

    def __init__(self, params=None):
        self.params = dict(params or {})

    def check(self, df):
        raise NotImplementedError

    def __repr__(self):
        return f'<GateFactor {self.key} ({self.label})>'


def register_gate(cls):
    """注册一个闸门类（按注册顺序保留）。"""
    if not getattr(cls, 'key', ''):
        raise ValueError('闸门类必须定义非空 key')
    _REGISTRY[cls.key] = cls
    return cls


def get_gate(key):
    return _REGISTRY[key]


def all_gates():
    return list(_REGISTRY.values())


def build_gates(indicator_params, gate_specs):
    """按配置构造已启用的闸门实例（保序）。

    Args:
        indicator_params: 指标参数（如 ma_long / macd_slow），供闸门读取。
        gate_specs:       `config/signal.json` 的 gates 段
                          ``[{"key", "enabled", "params"}, ...]``。
    """
    gates = []
    for spec in gate_specs or []:
        if not spec.get('enabled', True):
            continue
        cls = _REGISTRY.get(spec['key'])
        if cls is None:
            raise KeyError(f'未注册的闸门: {spec["key"]!r}（可选: {list(_REGISTRY)}）')
        params = {**indicator_params, **spec.get('params', {})}
        gates.append(cls(params))
    return gates
