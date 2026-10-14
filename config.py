# -*- coding: utf-8 -*-
"""
==============================================================================
统一配置加载模块（工程内自包含，不依赖任何外部工程）
==============================================================================

从同目录下的 `.env` 文件加载数据库连接信息与数据表名，供全工程统一使用。

用法::

    import config

    db = config.get_db_config()          # MySQL 连接字典
    url = config.get_sqlalchemy_url()    # SQLAlchemy 连接 URL
    tbl = config.get_table_names()       # 数据表名映射

优先级：**环境变量 > .env 文件 > 内置默认值**（`os.environ.setdefault`）。
"""

import os
from typing import Dict

_ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')

if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE, 'r', encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith('#') or '=' not in _line:
                continue
            _key, _, _value = _line.partition('=')
            _key = _key.strip()
            _value = _value.strip().strip('"').strip("'")
            if _key:
                os.environ.setdefault(_key, _value)


def _get(key: str, default: str = '') -> str:
    """读取配置项（环境变量优先）。"""
    return os.environ.get(key, default)


# ═════════════════════════════════════════════════════════════════════════
# 数据库连接
# ═════════════════════════════════════════════════════════════════════════

def get_db_config() -> Dict[str, object]:
    """
    获取 MySQL 数据库连接配置字典。

    Returns:
        {'host', 'port', 'user', 'password', 'database', 'charset'}
    """
    return {
        'host': _get('DB_HOST', 'localhost'),
        'port': int(_get('DB_PORT', '3306')),
        'user': _get('DB_USER', 'root'),
        'password': _get('DB_PASSWORD', ''),
        'database': _get('DB_NAME', 'stock_db'),
        'charset': _get('DB_CHARSET', 'utf8mb4'),
    }


def get_db_config_with_cursor(cursorclass: object) -> Dict[str, object]:
    """获取含 `cursorclass` 的连接配置（直接传给 pymysql.connect）。"""
    cfg = get_db_config()
    cfg['cursorclass'] = cursorclass
    return cfg


def get_sqlalchemy_url() -> str:
    """获取 SQLAlchemy 连接 URL。"""
    cfg = get_db_config()
    return (
        f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
        f"@{cfg['host']}:{cfg['port']}/{cfg['database']}"
        f"?charset={cfg['charset']}"
    )


# ═════════════════════════════════════════════════════════════════════════
# 数据表名
# ═════════════════════════════════════════════════════════════════════════

# 本工程只关心日线与月线两张后复权表
TABLE_BACKWARD_DAILY = _get('TABLE_BACKWARD_DAILY', 'backward_daily')
TABLE_BACKWARD_MONTHLY = _get('TABLE_BACKWARD_MONTHLY', 'backward_monthly')

# 信号富化数据表（由 run_update_factors.py 每周从外网刷新，供 enrich_signals.py 读取）
#   factor_spot      : 个股快照（行业 / 市值 / PE / PB / 现价）—— 每周快照
#   factor_qfq_daily : 前复权日线收盘 + vol60 / mom60 —— 每周重写（前复权随权息整体平移）
#   factor_index_daily: 指数日线（沪深300），可选
TABLE_FACTOR_SPOT = _get('TABLE_FACTOR_SPOT', 'factor_spot')
TABLE_FACTOR_QFQ_DAILY = _get('TABLE_FACTOR_QFQ_DAILY', 'factor_qfq_daily')
TABLE_FACTOR_INDEX_DAILY = _get('TABLE_FACTOR_INDEX_DAILY', 'factor_index_daily')


def get_table_names() -> Dict[str, str]:
    """获取本工程使用的数据表名映射。"""
    return {
        'backward_daily': TABLE_BACKWARD_DAILY,      # 日线后复权表
        'backward_monthly': TABLE_BACKWARD_MONTHLY,  # 月线后复权表
        'factor_spot': TABLE_FACTOR_SPOT,            # 富化：个股快照
        'factor_qfq_daily': TABLE_FACTOR_QFQ_DAILY,  # 富化：前复权日线 + 波动/动量
        'factor_index_daily': TABLE_FACTOR_INDEX_DAILY,  # 富化：指数日线
    }


def get_factor_tables() -> Dict[str, str]:
    """获取信号富化三表的表名映射（供 factors.enrichers.store 使用）。"""
    return {
        'spot': TABLE_FACTOR_SPOT,
        'qfq_daily': TABLE_FACTOR_QFQ_DAILY,
        'index_daily': TABLE_FACTOR_INDEX_DAILY,
    }


def describe() -> str:
    """返回人类可读的配置摘要（隐去密码），便于启动时打印与排查。"""
    cfg = get_db_config()
    return (f"MySQL {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']}"
            f"  |  表: {TABLE_BACKWARD_DAILY} / {TABLE_BACKWARD_MONTHLY}"
            f"  |  .env: {'已加载' if os.path.exists(_ENV_FILE) else '未找到(用默认值)'}")
