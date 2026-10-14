# -*- coding: utf-8 -*-
"""
==============================================================================
factors.registry —— 因子注册表 + factors.json 配置加载
==============================================================================

* 因子注册表：`register_feature` / `get_feature` / `all_features`，新增数值型
  因子只需实现一个 `FeatureFactor` 并在 `builtin.py`（或自定义模块）注册。
* 配置加载：读取并缓存 `config/factors.json`（组合 / 敏感性 / 分层 / 说明
  全部由该文件驱动），`reload=True` 可强制重读。
"""

import json
import os

from .. import settings as S
from .base import FeatureFactor

_FEATURES = {}                 # {name: FeatureFactor}
_CONFIG_CACHE = None
_CONFIG_PATH = None
_SIGNAL_CACHE = None
_SIGNAL_PATH = None
_ENRICH_CACHE = None
_ENRICH_PATH = None


def register_feature(factor):
    """注册一个数值型因子（FeatureFactor 实例），返回该因子。"""
    if not isinstance(factor, FeatureFactor):
        raise TypeError('register_feature 需要 FeatureFactor 实例')
    _FEATURES[factor.name] = factor
    return factor


def get_feature(name):
    """按因子键取因子。"""
    return _FEATURES[name]


def all_features():
    """按注册顺序返回全部数值型因子。"""
    return list(_FEATURES.values())


def feature_names():
    """全部因子键（注册顺序）。"""
    return list(_FEATURES.keys())


def numeric_columns():
    """全部数值型因子对应的列名（供信号加载时 to_numeric）。"""
    return [f.column for f in _FEATURES.values()]


def default_config_path():
    """`config/factors.json` 默认路径。"""
    return S.FACTOR_CONFIG


def load_config(path=None, reload=False):
    """加载并缓存 `config/factors.json`。

    Args:
        path:   配置路径，默认 `settings.FACTOR_CONFIG`。
        reload: 为 True 时忽略缓存强制重读。
    """
    global _CONFIG_CACHE, _CONFIG_PATH
    path = path or _CONFIG_PATH or default_config_path()
    if _CONFIG_CACHE is None or reload or path != _CONFIG_PATH:
        with open(path, 'r', encoding='utf-8') as f:
            _CONFIG_CACHE = json.load(f)
        _CONFIG_PATH = path
    return _CONFIG_CACHE


def default_enricher_path():
    """`config/enrichers.json` 默认路径。"""
    return S.ENRICHER_CONFIG


def load_enricher_config(path=None, reload=False):
    """加载并缓存 `config/enrichers.json`（富化表名 + 抓取参数 + 富化器清单）。

    Args:
        path:   配置路径，默认 `settings.ENRICHER_CONFIG`。
        reload: 为 True 时忽略缓存强制重读。
    """
    global _ENRICH_CACHE, _ENRICH_PATH
    path = path or _ENRICH_PATH or default_enricher_path()
    if _ENRICH_CACHE is None or reload or path != _ENRICH_PATH:
        with open(path, 'r', encoding='utf-8') as f:
            _ENRICH_CACHE = json.load(f)
        _ENRICH_PATH = path
    return _ENRICH_CACHE


def default_signal_path():
    """`config/signal.json` 默认路径。"""
    return S.SIGNAL_CONFIG


def load_signal_config(path=None, reload=False):
    """加载并缓存 `config/signal.json`（指标参数 + 闸门清单）。

    Args:
        path:   配置路径，默认 `settings.SIGNAL_CONFIG`。
        reload: 为 True 时忽略缓存强制重读。
    """
    global _SIGNAL_CACHE, _SIGNAL_PATH
    path = path or _SIGNAL_PATH or default_signal_path()
    if _SIGNAL_CACHE is None or reload or path != _SIGNAL_PATH:
        with open(path, 'r', encoding='utf-8') as f:
            _SIGNAL_CACHE = json.load(f)
        _SIGNAL_PATH = path
    return _SIGNAL_CACHE
