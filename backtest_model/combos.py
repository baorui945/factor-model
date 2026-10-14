# -*- coding: utf-8 -*-
"""
==============================================================================
组合定义 —— 由 `config/factors.json` 配置驱动（全部复用同一套回测引擎）
==============================================================================

组合规则不再写死在代码里，而是读取 `config/factors.json` 的 `combos` 段。
新增 / 替换因子或调整阈值，只需改配置，无需改本文件。

每条规则形如::

    {"factor": "nmc",   "op": "<",       "value": 20}
    {"factor": "vol60", "op": "between", "value": [0.25, 0.35]}

可用因子的定义见 `backtest_model/factors/builtin.py`。
"""

from .factors import evaluate_rules, load_config


def combo_defs():
    """返回 [(key, 名称, 过滤函数, 说明)] —— 过滤函数入参为因子表 DataFrame。"""
    defs = []
    for c in load_config().get('combos', []):
        rules = c.get('rules', [])
        defs.append((
            c['key'],
            c['name'],
            (lambda d, _r=rules: evaluate_rules(d, _r)),
            c.get('desc', ''),
        ))
    return defs


def combo_names() -> dict:
    """返回 {key: 名称}。"""
    return {k: n for k, n, _f, _d in combo_defs()}


def combo_readme(key):
    """返回组合在「回测说明」中的口径描述（可缺省，缺省返回空串）。"""
    for c in load_config().get('combos', []):
        if c['key'] == key:
            return c.get('readme', '')
    return ''


#: 最优组合的键（用于逐笔明细 / 图表高亮）
BEST_KEY = load_config().get('best_key', 'S1')
