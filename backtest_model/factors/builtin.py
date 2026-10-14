# -*- coding: utf-8 -*-
"""
==============================================================================
factors.builtin —— 内置数值型因子
==============================================================================

注册信号池中现成的因子列：

    nmc      流通市值（亿元）        —— 小市值过滤
    vol60    60 日年化波动率         —— 趋势强弱
    mom60    60 日动量               —— 趋势方向
    mkt_dev  沪深300 相对 MA60 偏离   —— 择时
    pb_t     市净率                  —— 低估值过滤

注册顺序与信号加载时 `to_numeric` 的列顺序保持一致。
新增因子时，可在此追加一行 `register_feature(...)`，或在自定义模块中注册。
"""

from .base import FeatureFactor
from .registry import register_feature

register_feature(FeatureFactor('nmc', '流通市值', '流通市值（亿元）'))
register_feature(FeatureFactor('vol60', '60日波动率', '60 日年化波动率'))
register_feature(FeatureFactor('mom60', '60日动量', '60 日动量'))
register_feature(FeatureFactor('mkt_dev', '大盘择时', '沪深300 相对 MA60 偏离'))
register_feature(FeatureFactor('pb_t', '市净率', '市净率 PB'))
