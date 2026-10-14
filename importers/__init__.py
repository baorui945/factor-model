# -*- coding: utf-8 -*-
"""
数据导入子包 —— 只提供 **日线** 与 **月线** 两条通道
==============================================================================

    importers.common   —— 底层工具（连接/建表/upsert/baostock/文件解析）
    importers.base     —— 通用导入流程（网络源 + 文件源）
    importers.daily    —— 日线导入 CLI  -> backward_daily
    importers.monthly  —— 月线导入 CLI  -> backward_monthly

对外最简用法::

    from importers import daily, monthly

    daily.main(['--start', '2021-06-01', '--limit', '5'])
    monthly.main(['--limit', '5'])

说明：子模块采用**惰性导入**（`__getattr__`），既保证 `from importers import daily`
可用，又避免 `python -m importers.daily` 时的重复导入告警。
"""

import importlib

__all__ = ['common', 'base', 'daily', 'monthly']


def __getattr__(name):
    if name in __all__:
        return importlib.import_module('.' + name, __name__)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
