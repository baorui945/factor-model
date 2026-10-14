# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.pipeline —— 富化流水线（信号 → 富化特征表）
==============================================================================

把「已生成的信号 + 富化上下文」编排成富化特征表，等价于旧脚本的
``add_buckets(build_features(sigs, spot, ind_map, klines, idx_kl))``：

    sigs (stock_code / signal_date / return_20d|30d|40d)
      └── load_context() 取得 ctx（库表 or 网络）
            └── build_features() 跑全部已注册富化器
                  └── add_buckets() 追加分档列

列集合与顺序由 ``_COL_ORDER`` 在调用方统一 reindex，故本模块只保证
**列名与取值**与旧版逐位一致。
"""

import numpy as np
import pandas as pd

from ..registry import load_enricher_config
from .base import Enricher, build_enrichers
from .buckets import add_buckets


def resolve_enrichers(config=None):
    """按配置构造 (group 级富化器, frame 级富化器)。"""
    cfg = config or load_enricher_config()
    params = dict(cfg.get('update', {}))
    ens = build_enrichers(cfg.get('enrichers', []), params)
    group = [e for e in ens if getattr(e, 'scope', 'group') == 'group']
    frame = [e for e in ens if getattr(e, 'scope', 'group') == 'frame']
    return group, frame


def build_features(sigs, ctx, config=None):
    """为每条信号补齐富化列（逐位对齐旧版 `build_features`）。

    Args:
        sigs: 信号表（需含 ``stock_code`` / ``stock_name`` / ``signal_date`` /
              ``return_20d`` / ``return_30d`` / ``return_40d``）。
        ctx:  `EnrichContext`。
        config: `config/enrichers.json`；None 时自动加载。

    Returns:
        富化特征表（含 ``mkt_dev`` / ``year`` 等帧级列，但**不含**分档列）。
    """
    cfg = config or load_enricher_config()
    group_ens, frame_ens = resolve_enrichers(cfg)

    ctx.sig_count = sigs['stock_code'].value_counts().to_dict()

    has_name = 'stock_name' in sigs.columns
    rows = []
    for code, grp in sigs.groupby('stock_code', sort=False):
        out = {
            'stock_code': code,
            'stock_name': grp['stock_name'].iloc[0] if has_name else '',
            'signal_date': grp['signal_date'].to_numpy(),
            'return_20d': grp['return_20d'].to_numpy(dtype=np.float64),
            'return_30d': grp['return_30d'].to_numpy(dtype=np.float64),
            'return_40d': grp['return_40d'].to_numpy(dtype=np.float64),
        }
        for en in group_ens:
            en.enrich(ctx, code, grp, out)
        rows.append(pd.DataFrame(out))

    feat = pd.concat(rows, ignore_index=True)
    for en in frame_ens:
        en.enrich_frame(ctx, sigs, feat)
    return feat


def enrich_signals(sigs, ctx, config=None, with_buckets=True):
    """完整富化：`build_features` + 分档。"""
    cfg = config or load_enricher_config()
    feat = build_features(sigs, ctx, cfg)
    return add_buckets(feat, cfg) if with_buckets else feat
