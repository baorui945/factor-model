# -*- coding: utf-8 -*-
"""
==============================================================================
backtest_model —— 三因子买点「最优组合」策略级回测模型
==============================================================================

从 `quantTrade/analyzers/three_factor_best_backtest.py` 迁移而来的**自包含**
工程版本，只依赖：本项目 `data/` 下的信号池与指数文件 + MySQL `backward_daily`。

模块划分::

    settings       —— 路径与回测默认参数
    data           —— 信号加载 / 价格抓取与缓存 / 沪深300 / 价格面板
    engine         —— 去重建仓、日频等权回测、绩效指标、逐笔明细
    combos         —— 六个对比组合（ALL/A/S1/S2/S3/S4）定义
    analysis       —— 绩效总览 / 年度月度 / 参数敏感性 / 因子分层 / 净值曲线 / 说明
    excel_report   —— 多 Sheet Excel 导出（含涨跌着色）
    charts         —— 6 面板回测图

对外最简用法::

    from backtest_model import run

    run.main(['--horizons', '20,30,40,60', '--chart'])

说明：子模块采用**惰性导入**（`__getattr__`），避免 `python -m backtest_model.run`
时的重复导入告警。
"""

import importlib

__all__ = ['settings', 'data', 'engine', 'factors', 'combos', 'analysis',
           'excel_report', 'charts', 'run']


def __getattr__(name):
    if name in __all__:
        return importlib.import_module('.' + name, __name__)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
