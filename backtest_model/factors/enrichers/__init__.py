# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers —— 信号富化（数据层，可插拔）
==============================================================================

为信号补齐「上下文属性」列（上市板 / 行业 / 市值 / PB / 波动 / 动量 / 大盘环境），
数据来源统一收敛到 `FactorStore`（MySQL 三表，由 `run_update_factors.py`
**每周刷新**），网络抓取仅作兜底，从此不再依赖外部工程
`F:\\quantTrade\\analyzers`。

对外接口::

    from backtest_model.factors.enrichers import (
        Enricher, register_enricher,      # 扩展新富化器
        FactorStore,                      # 富化库读写（快照 / 前复权日线 / 指数）
        load_context, EnrichContext,      # 组装数据来源
        build_features, enrich_signals,   # 富化主流程
        fetch_spot, fetch_industry_map,   # 网络抓取（兜底）
    )

新增富化器::

    from backtest_model.factors.enrichers import Enricher, register_enricher

    @register_enricher
    class TurnoverEnricher(Enricher):
        key, label, columns = 'turnover', '换手率', ('turnover',)
        def enrich(self, ctx, code, grp, out):
            out['turnover'] = np.full(len(grp), np.nan)

再在 `config/enrichers.json` 的 ``enrichers`` 段加入
``{"key": "turnover", "enabled": true}`` 即可。
"""

from .base import (Enricher, register_enricher, get_enricher, all_enrichers,
                   enricher_keys, build_enrichers)
from .metrics import board_of, compute_metrics, metric_at, index_regime
from .network import (fetch_spot, fetch_industry_map, fetch_kline,
                      fetch_all_klines, fetch_index_series, sina_symbol,
                      safe_float)
from .store import (FactorStore, to_f32, to_float, date_iso, day_int)
from .context import (EnrichContext, load_context, load_index_series,
                      fetch_klines_network)
from .buckets import add_buckets, BUCKET_COLUMNS
from .pipeline import build_features, enrich_signals, resolve_enrichers
from . import builtin                                          # noqa: F401  触发注册

__all__ = [
    # 富化器协议
    'Enricher', 'register_enricher', 'get_enricher', 'all_enrichers',
    'enricher_keys', 'build_enrichers', 'resolve_enrichers',
    # 富化库
    'FactorStore', 'to_f32', 'to_float', 'date_iso', 'day_int',
    # 数据来源
    'EnrichContext', 'load_context', 'load_index_series', 'fetch_klines_network',
    # 网络抓取（兜底）
    'fetch_spot', 'fetch_industry_map', 'fetch_kline', 'fetch_all_klines',
    'fetch_index_series', 'sina_symbol', 'safe_float',
    # 派生量 / 分档 / 流水线
    'board_of', 'compute_metrics', 'metric_at', 'index_regime',
    'add_buckets', 'BUCKET_COLUMNS', 'build_features', 'enrich_signals',
]
