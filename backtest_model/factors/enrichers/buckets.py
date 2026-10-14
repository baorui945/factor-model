# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.buckets —— 富化列分档（bucket）
==============================================================================

把连续富化列切成离散档位（供因子分层 / 交叉统计用）。档位边界与标签由
`config/enrichers.json` → ``buckets`` 提供，**默认值与旧版一致**，
列名沿用旧版（``mv_bucket`` / ``nmc_bucket`` / …）以保持信号池
``sig_all_horizons.pkl`` 的列集合不变。
"""

import numpy as np
import pandas as pd

from ..registry import load_enricher_config

#: (源列, 分档列名) —— 列名与旧版 `add_buckets` 完全一致
BUCKET_COLUMNS = [
    ('mv_total', 'mv_bucket'),
    ('nmc', 'nmc_bucket'),
    ('pb_t', 'pb_bucket'),
    ('pe_now', 'pe_bucket'),
    ('vol60', 'vol_bucket'),
    ('mom60', 'mom_bucket'),
    ('mkt_dev', 'mkt_bucket'),
    ('sig_count', 'sig_bucket'),
    ('price', 'price_bucket'),
]


def _cut(series, bins, labels):
    """左闭右开分档（与旧版 `_cut` 一致）。"""
    return pd.cut(series, bins=bins, labels=labels, right=False)


def _pe_series(pe, spec):
    """PE 分档（亏损 / 非正单独成档，与旧版 `_pe_bucket_series` 一致）。"""
    edges = [float(b) for b in spec['bins']]
    labels = list(spec['labels'])
    loss = spec.get('loss_label', '亏损(PE<=0)')

    def _one(v):
        if pd.isna(v):
            return np.nan
        if v <= edges[0]:
            return loss
        for k in range(len(labels)):
            if v < edges[k + 1]:
                return labels[k]
        return labels[-1]

    return pe.map(_one)


def add_buckets(feat, config=None):
    """为核心富化列追加分档列（原地返回）。

    Args:
        feat:   富化后的信号表。
        config: `config/enrichers.json`（或 ``buckets`` 段）；None 时自动加载。
    """
    cfg = config if isinstance(config, dict) else load_enricher_config()
    specs = cfg.get('buckets', cfg)

    out_cols = []
    for col, bucket in BUCKET_COLUMNS:
        spec = specs.get(col)
        if spec is None or col not in feat.columns:
            continue
        if col == 'pe_now':
            feat[bucket] = _pe_series(feat[col], spec)
        else:
            feat[bucket] = _cut(feat[col],
                                [float(b) for b in spec['bins']],
                                list(spec['labels']))
        out_cols.append(bucket)

    # 统一转 object，避免 categorical 新增类别 / 分组异常
    for c in out_cols:
        feat[c] = feat[c].astype(object)
    return feat
