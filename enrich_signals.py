# -*- coding: utf-8 -*-
"""
==============================================================================
信号富化层 —— 为重建后的三因子信号补齐因子列，产出 sig_all_horizons.pkl
==============================================================================

输入：`rebuild_signals.py` 产出的信号 CSV（stock_code / signal_date /
      return_20d|30d|40d|60d）。
输出：`data/sig_all_horizons.pkl`（列结构与旧版完全一致）。

数据来源（**不再依赖外部工程**）
--------------------------------
优先读取本工程自己的富化库表（由 `run_update_factors.py` **每周刷新一次**）：

    factor_spot       行业 / 市值 / PE / PB / 现价（个股快照）
    factor_qfq_daily  前复权日线收盘 + vol60 + mom60
    factor_index_daily指数日线（沪深300，缺失时沿用 data/idx_000300.pkl）

库表缺票时自动回退外网抓取（新浪 / 东财），落盘断点缓存于
`data/_cache/kline_qfq_long.pkl`。

富化口径（与主工程 `analyzers/three_factor_segment_analysis.py` 逐字一致）
--------------------------------------------------------------------------
* 板块 board      : 代码前缀判定
* 行业 industry   : 东财 F10（回退新浪）快照，每周随库表更新
* 总/流通市值、PB : 新浪**当前快照** × `前复权价(t)/前复权价(now)` 折算
                    （隐含「信号日至今股本未变」，长历史下误差见 README 说明）
* vol60 / mom60   : 前复权收盘的 60 日年化波动 / 60 日动量
* mkt_dev/mkt_mom60: 沪深300 相对 MA60 偏离 / 60 日动量
* c0 / f20..f60   : 直接取信号 CSV 的 signal_close / return_Nd

用法
----
    # ① 先每周刷新富化库（快照 + 前复权日线 + vol60/mom60）
    python run_update_factors.py --if-stale

    # ② 只预热「长历史前复权日线」缓存（可与其他任务并行跑）
    python enrich_signals.py --fetch-only

    # ③ 完整富化（优先读库表）
    python enrich_signals.py --signals output\\signals_rebuilt_full.csv

    # 无库表时只走外网（等价旧行为）
    python enrich_signals.py --from-network
"""

import argparse
import os
import pickle
import shutil
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

from backtest_model import settings as S                              # noqa: E402
from backtest_model.factors.enrichers import (                        # noqa: E402
    EnrichContext, load_context, enrich_signals, fetch_klines_network)
from backtest_model.factors.registry import load_enricher_config      # noqa: E402

_DATALEN = 2800            # 前复权日线长度：覆盖 2015-04 起

_COL_ORDER = ['stock_code', 'stock_name', 'signal_date', 'return_20d',
              'return_30d', 'return_40d', 'board', 'industry', 'mv_total', 'nmc',
              'pb_t', 'pe_now', 'price', 'vol60', 'mom60', 'sig_count',
              'mkt_dev', 'mkt_mom60', 'year', 'mv_bucket', 'nmc_bucket',
              'pb_bucket', 'pe_bucket', 'vol_bucket', 'mom_bucket', 'mkt_bucket',
              'sig_bucket', 'price_bucket', 'c0', 'f20', 'f30', 'f40', 'f60']


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog='enrich_signals',
        description='为重建后的三因子信号补齐因子列（产出 sig_all_horizons.pkl）')
    ap.add_argument('--signals', default=None, help='重建信号 CSV，默认取最新一份')
    ap.add_argument('--out', default=S.SIG_PKL,
                    help=f'输出 pkl，默认 {os.path.relpath(S.SIG_PKL, ROOT)}')
    ap.add_argument('--workers', type=int, default=None, help='前复权日线并发数')
    ap.add_argument('--datalen', type=int, default=None, help='前复权日线长度')
    ap.add_argument('--source', choices=['auto', 'store', 'network'],
                    default='auto',
                    help='数据来源：auto=库表优先+网络兜底（默认）/ store=只读库 / network=只走网络')
    ap.add_argument('--from-network', action='store_true',
                    help='等价 --source network（只走外网，忽略库表）')
    ap.add_argument('--refresh-kline', action='store_true', help='忽略缓存重抓日线')
    ap.add_argument('--fetch-only', action='store_true', help='只预热日线缓存后退出')
    ap.add_argument('--no-write', action='store_true', help='只跑富化、不写 pkl')
    return ap


def pick_signals(path=None) -> str:
    """选取信号 CSV（默认 output 下最新一份 signals_rebuilt_*.csv）。"""
    if path:
        return path
    import glob
    cands = sorted(glob.glob(os.path.join(S.OUTPUT_DIR, 'signals_rebuilt*.csv')))
    if not cands:
        raise FileNotFoundError('未找到 output/signals_rebuilt*.csv，请先跑 rebuild_signals.py')
    return cands[-1]


def load_signals_csv(csv_path) -> pd.DataFrame:
    """加载重建信号 CSV（口径与旧版 `TSA.load_signals` 一致）。"""
    df = pd.read_csv(csv_path, dtype={'stock_code': str, 'stock_name': str})
    df['signal_date'] = pd.to_datetime(df['signal_date'])
    return df


def universe_codes() -> list:
    """后复权日线表全部代码（仅用于 --fetch-only 预热）。"""
    import pymysql
    import config
    cn = pymysql.connect(**config.get_db_config())
    try:
        cur = cn.cursor()
        cur.execute(f'SELECT DISTINCT stock_code FROM {config.TABLE_BACKWARD_DAILY}')
        return sorted(str(r[0]).zfill(6) for r in cur.fetchall())
    finally:
        cn.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_enricher_config()
    upd = cfg.get('update', {})
    workers = args.workers or int(upd.get('workers', 8))
    datalen = args.datalen or int(upd.get('kline_datalen', _DATALEN))
    source = 'network' if args.from_network else args.source

    S.ensure_dirs()
    os.makedirs(S.CACHE_DIR, exist_ok=True)

    have_signals = bool(args.signals) or (
        os.path.isdir(S.OUTPUT_DIR)
        and any(f.startswith('signals_rebuilt') for f in os.listdir(S.OUTPUT_DIR)))

    # ── --fetch-only：仅预热日线缓存 ───────────────────────────────────
    if args.fetch_only and not have_signals:
        codes = universe_codes()
        print(f'[预热] 全表股票池 {len(codes):,} 只')
        fetch_klines_network(codes, datalen=datalen, workers=workers,
                             refresh=args.refresh_kline)
        print('✅ --fetch-only：日线缓存已就绪，退出')
        return 0

    csv_path = pick_signals(args.signals)
    print('=' * 78)
    print('  信号富化 —— 重建三因子信号补齐因子列')
    print('=' * 78)
    print(f'  信号 CSV : {csv_path}')
    print(f'  输出 pkl : {args.out}')
    print(f'  数据来源 : {source}')
    print('=' * 78)

    sigs = load_signals_csv(csv_path)
    codes = sorted(sigs['stock_code'].unique())
    print(f'[信号] {len(sigs):,} 条 / {len(codes):,} 只  '
          f'{sigs["signal_date"].min().date()} ~ {sigs["signal_date"].max().date()}')

    ctx = load_context(codes, source=source, datalen=datalen, workers=workers,
                       refresh=args.refresh_kline,
                       index_code=str(upd.get('index_code', '000300')))
    print(f'[数据] {ctx}')
    if args.fetch_only:
        print('✅ --fetch-only：日线缓存已就绪，退出')
        return 0

    feat = enrich_signals(sigs, ctx, cfg)

    # 与旧版 pkl 对齐：c0 / f20..f60 直接用本次重建的前瞻收益（同口径）
    ren = sigs.copy()
    ren['rename_date'] = ren['signal_date'].astype(str)
    feat['rename_date'] = feat['signal_date'].astype(str)
    feat = feat.merge(
        ren[['stock_code', 'rename_date', 'signal_close', 'return_60d']],
        on=['stock_code', 'rename_date'], how='left')
    feat['c0'] = feat['signal_close']
    feat['f20'] = feat['return_20d']
    feat['f30'] = feat['return_30d']
    feat['f40'] = feat['return_40d']
    feat['f60'] = feat['return_60d']
    feat = feat.drop(columns=['rename_date', 'signal_close', 'return_60d'])
    # `signal_date` 统一为 'YYYY-MM-DD' 字符串（与旧版 pkl 的 .astype(str) 结果一致）
    feat['signal_date'] = pd.to_datetime(feat['signal_date']).dt.strftime('%Y-%m-%d')
    feat = feat[_COL_ORDER]

    print(f'[富化] 覆盖率：市值 {feat["mv_total"].notna().mean() * 100:.1f}%  '
          f'流通市值 {feat["nmc"].notna().mean() * 100:.1f}%  '
          f'PB {feat["pb_t"].notna().mean() * 100:.1f}%  '
          f'vol60 {feat["vol60"].notna().mean() * 100:.1f}%  '
          f'mkt_dev {feat["mkt_dev"].notna().mean() * 100:.1f}%')
    print('[富化] nmc 分布（亿元）: '
          + str({k: round(float(v), 1) for k, v in
                 feat['nmc'].describe(
                     percentiles=[.1, .25, .5, .75, .9]).items()}))
    print('[富化] 按年信号数: '
          + str(feat['year'].value_counts().sort_index().to_dict()))

    if args.no_write:
        print('（--no-write：未写入 pkl）')
        return 0

    if os.path.exists(args.out):
        bak = args.out.replace('.pkl', f'.pre_tdx_{time.strftime("%Y%m%d")}.pkl')
        if not os.path.exists(bak):
            shutil.copy2(args.out, bak)
            print(f'[备份] 旧信号池 -> {bak}')
    with open(args.out, 'wb') as f:
        pickle.dump(feat, f, protocol=4)
    print(f'✅ 已写入 {args.out}  {len(feat):,} 行 × {feat.shape[1]} 列')
    return 0


if __name__ == '__main__':
    sys.exit(main())

