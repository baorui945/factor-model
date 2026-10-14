# -*- coding: utf-8 -*-
"""
==============================================================================
settings —— 路径与回测默认参数（全局唯一来源）
==============================================================================

工程内所有路径都以本文件为基准，保证脚本在任意工作目录下运行都指向正确位置。
"""

import os

# ── 工程根目录 ────────────────────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 数据目录 ──────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(ROOT_DIR, 'data')
CACHE_DIR = os.path.join(DATA_DIR, '_cache')       # 价格缓存
SIG_PKL = os.path.join(DATA_DIR, 'sig_all_horizons.pkl')   # 三因子信号池
IDX_PKL = os.path.join(DATA_DIR, 'idx_000300.pkl')         # 沪深300 收盘
PX_CACHE = os.path.join(CACHE_DIR, 'bt_daily_px.parquet')  # 后复权价格缓存

# ── 因子 / 组合配置 ───────────────────────────────────────────────────────
FACTOR_CONFIG = os.path.join(ROOT_DIR, 'config', 'factors.json')  # 因子与组合配置（唯一扩展点）
SIGNAL_CONFIG = os.path.join(ROOT_DIR, 'config', 'signal.json')   # 信号侧指标 + 闸门配置
ENRICHER_CONFIG = os.path.join(ROOT_DIR, 'config', 'enrichers.json')  # 信号富化配置（表名/抓取/富化器）

# ── 富化中间缓存 ─────────────────────────────────────────────────────────
ENRICH_CACHE_DIR = os.path.join(CACHE_DIR, 'enrich')
QFX_KLINE_CACHE = os.path.join(CACHE_DIR, 'kline_qfq_long.pkl')  # 旧版长历史前复权日线缓存
WEEKLY_STAMP = os.path.join(ENRICH_CACHE_DIR, 'last_update.json')  # 每周刷新时间戳

# ── 输出目录 ──────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(ROOT_DIR, 'output')
CHART_DIR = os.path.join(OUTPUT_DIR, 'charts')

# ── 回测默认参数 ──────────────────────────────────────────────────────────
DEF_HORIZON = 20            # 持有交易日数（主口径）
DEF_HORIZONS = '20,30,40,60'  # 默认扫描的持有期列表
DEF_COST = 0.002            # 双边合计成本（建仓 0.10% + 平仓 0.10%）
# 价格起始日：对齐新表 backward_tdx_daily 的历史起点（2015-09-01），
# 信号最早约 2017-02（滚动 360 根窗口需要 360 个交易日预热）。
DEF_START = '2015-09-01'
TRADING_DAYS = 252          # 年化交易日数

# ── Excel 表头样式（与既有分析脚本保持一致）──────────────────────────────
HEADER_FILL = '366092'
HEADER_FONT = 'FFFFFF'


def ensure_dirs() -> None:
    """确保数据/输出目录存在。"""
    for d in (DATA_DIR, CACHE_DIR, OUTPUT_DIR, CHART_DIR):
        os.makedirs(d, exist_ok=True)
