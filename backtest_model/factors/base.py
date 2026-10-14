# -*- coding: utf-8 -*-
"""
==============================================================================
factors.base —— 数值型因子协议 + 规则求值器
==============================================================================

本模块是「回测层因子模块化」的基础，定义：

* FeatureFactor  : 数值型因子描述对象（流通市值 / 波动率 / 动量 / 大盘偏离 /
                   估值…），由注册表统一管理，参与 组合筛选 / 参数敏感性 /
                   因子分层。
* evaluate_rule / evaluate_rules : 把 `config/factors.json` 中的规则
                   （如 ``{"factor": "nmc", "op": "<", "value": 20}``）
                   翻译成布尔掩码（布尔 Series）。

设计目标：新增 / 替换因子或调整阈值时**只改配置**，不改回测代码。
"""

import pandas as pd


class FeatureFactor:
    """数值型因子描述对象。

    Attributes:
        name:        因子键（默认同时是信号表的列名）。
        column:      信号表中的实际列名。
        label:       中文名（用于分层维度 / 说明）。
        description: 因子口径说明。
        buckets:     默认分层档位 ``[(lo, hi, tag), ...]``（左闭右开），
                     仅作为内置默认值；实际分层档位以配置为准。
    """

    def __init__(self, name, label, description='', buckets=None, column=None):
        self.name = name
        self.column = column or name
        self.label = label
        self.description = description
        self.buckets = list(buckets or [])

    def __repr__(self):
        return f'<FeatureFactor {self.name} ({self.label})>'


def _norm_inclusive(inclusive):
    """把配置里的 inclusive 归一为 pandas.Series.between 可接受的值。"""
    if inclusive in ('both', 'left', 'right', 'neither'):
        return inclusive
    return 'left'


def evaluate_rule(df, rule):
    """对单个规则求值，返回布尔 Series。

    规则格式::

        {"factor": "nmc",   "op": "<",       "value": 20}
        {"factor": "vol60", "op": "between", "value": [0.25, 0.35],
         "inclusive": "left"}                 # left / both / right / neither
    """
    col = rule['factor']
    op = rule['op']
    val = rule.get('value')
    s = df[col]
    if op == '<':
        return s < val
    if op == '<=':
        return s <= val
    if op == '>':
        return s > val
    if op == '>=':
        return s >= val
    if op == '==':
        return s == val
    if op == '!=':
        return s != val
    if op == 'between':
        lo, hi = val
        return s.between(lo, hi,
                         inclusive=_norm_inclusive(rule.get('inclusive')))
    raise ValueError(f'未知算子: {op!r}（规则 {rule}）')


def evaluate_rules(df, rules):
    """对规则列表做 AND 求值，返回布尔 Series（空列表 => 全部 True）。"""
    mask = pd.Series(True, index=df.index)
    for rule in rules or []:
        mask &= evaluate_rule(df, rule)
    return mask
