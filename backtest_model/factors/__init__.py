# -*- coding: utf-8 -*-
"""
==============================================================================
factors —— 可配置、模块化的因子体系
==============================================================================

统一管理「数值型因子」（用于组合筛选 / 参数敏感性 / 因子分层），并把
组合、阈值、分层档位等全部外置到 `config/factors.json`。

对外接口::

    from backtest_model.factors import (
        FeatureFactor, register_feature,           # 扩展新因子
        numeric_columns, all_features,             # 因子清单
        evaluate_rule, evaluate_rules,             # 规则求值
        load_config,                               # 读取配置
    )

新增一个因子::

    from backtest_model.factors import FeatureFactor, register_feature

    register_feature(FeatureFactor('turnover', '换手率', '20 日换手率'))

再在 `config/factors.json` 的组合 / 分层里引用 ``"factor": "turnover"`` 即可。

说明：`builtin` 在导入链末端加载，以触发内置因子的注册。
"""

from .base import FeatureFactor, evaluate_rule, evaluate_rules
from .registry import (register_feature, get_feature, all_features,
                       feature_names, numeric_columns, load_config,
                       load_signal_config, load_enricher_config,
                       default_config_path, default_signal_path,
                       default_enricher_path)
from .indicators import calculate_indicators
from .gates import GateFactor, register_gate, build_gates, all_gates
from .model import ThreeFactorModel
from .scanner import scan_stock
from .db import MarketDB
from .enrichers import (Enricher, register_enricher, build_enrichers,
                        FactorStore, EnrichContext, load_context,
                        build_features, enrich_signals)
from . import builtin                                        # noqa: F401  触发注册

__all__ = [
    # 数值型因子（回测层）
    'FeatureFactor', 'evaluate_rule', 'evaluate_rules',
    'register_feature', 'get_feature', 'all_features', 'feature_names',
    'numeric_columns', 'load_config', 'load_signal_config',
    'load_enricher_config', 'default_config_path', 'default_signal_path',
    'default_enricher_path',
    # 判定型闸门（信号生成层）
    'GateFactor', 'register_gate', 'build_gates', 'all_gates',
    'calculate_indicators', 'ThreeFactorModel', 'scan_stock', 'MarketDB',
    # 富化器（数据层）
    'Enricher', 'register_enricher', 'build_enrichers',
    'FactorStore', 'EnrichContext', 'load_context',
    'build_features', 'enrich_signals',
]
