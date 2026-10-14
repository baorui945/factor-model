# -*- coding: utf-8 -*-
"""
==============================================================================
run_update_factors —— 富化数据每周刷新（外网 → MySQL → 信号富化）
==============================================================================

把「行业 / 市值 / PE / PB / 前复权日线 / vol60 / mom60 / 指数」从外网抓取后
写入本工程自己的库表（`config/enrichers.json` → ``tables``），此后
`enrich_signals.py` 直接读表，**不再依赖外部工程** `F:\\quantTrade\\analyzers`。

写入的三张表
------------
``factor_spot``        个股快照：行业 / 市值 / PE / PB / 现价（每只一行）
``factor_qfq_daily``   前复权日线收盘 + vol60 + mom60（每只每日一行）
``factor_index_daily`` 指数日线（沪深300，用于大盘环境）

用法
----
    # 全量刷新（快照 + 前复权日线 + 指数）
    python run_update_factors.py

    # 只刷快照（很快，秒级）
    python run_update_factors.py --only spot

    # 只刷前复权日线（较慢，3300 只 × 2800 根 ≈ 数分钟抓取 + 数分钟写库）
    python run_update_factors.py --only kline

    # 计划任务用：距上次刷新不足 7 天则直接跳过
    python run_update_factors.py --if-stale

    # 查看库表现状 / 快速验证
    python run_update_factors.py --status
    python run_update_factors.py --limit 300

Windows 计划任务（每周一 02:00）
--------------------------------
    schtasks /Create /TN "ABM_UpdateFactors" /SC WEEKLY /D MON /ST 02:00 ^
        /TR "cmd /c cd /d F:\\ai_backtest_model && scripts\\update_factors_weekly.bat"
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

import config                                                    # noqa: E402
from backtest_model import settings as S                         # noqa: E402
from backtest_model.factors.enrichers import network             # noqa: E402
from backtest_model.factors.enrichers.metrics import (           # noqa: E402
    board_of, compute_metrics)
from backtest_model.factors.enrichers.store import (             # noqa: E402
    FactorStore, date_iso, to_f32, to_float)
from backtest_model.factors.registry import load_enricher_config  # noqa: E402


def build_parser():
    ap = argparse.ArgumentParser(
        prog='run_update_factors',
        description='富化数据每周刷新（外网 → MySQL：快照 / 前复权日线 / 指数）')
    ap.add_argument('--only', choices=['all', 'spot', 'kline', 'index'],
                    default='all', help='只刷新指定部分（默认 all）')
    ap.add_argument('--universe', choices=['db', 'spot'], default='db',
                    help='日线股票池来源：db=后复权日线表去重代码 / spot=实时快照')
    ap.add_argument('--limit', type=int, default=None, help='只处理前 N 只（快速验证）')
    ap.add_argument('--workers', type=int, default=None, help='抓取并发数')
    ap.add_argument('--datalen', type=int, default=None, help='每只抓取日线根数')
    ap.add_argument('--batch-size', type=int, default=None, help='写库批大小')
    ap.add_argument('--refresh', action='store_true', help='忽略本地 pkl 缓存重抓日线')
    ap.add_argument('--if-stale', action='store_true',
                    help='距上次刷新不足 max_age_days 天时直接跳过（供计划任务）')
    ap.add_argument('--status', action='store_true', help='只打印库表现状后退出')
    ap.add_argument('--no-index-pkl', action='store_true',
                    help='刷新指数时不同步改写 data/idx_000300.pkl')
    return ap


# ═════════════════════════════════════════════════════════════════════════
# 股票池 / 新鲜度
# ═════════════════════════════════════════════════════════════════════════

def db_universe():
    """后复权日线表去重代码（与 rebuild/enrich 的信号来源一致）。"""
    import pymysql
    cn = pymysql.connect(**config.get_db_config(),
                         cursorclass=pymysql.cursors.Cursor)
    try:
        cur = cn.cursor()
        cur.execute(f'SELECT DISTINCT stock_code FROM {config.TABLE_BACKWARD_DAILY}')
        return sorted(str(r[0]).zfill(6) for r in cur.fetchall())
    finally:
        cn.close()


def last_update():
    """读取上次刷新时间戳（``None`` 表示从未刷新）。"""
    if not os.path.isfile(S.WEEKLY_STAMP):
        return None
    try:
        with open(S.WEEKLY_STAMP, encoding='utf-8') as f:
            return json.load(f)
    except Exception:                                    # noqa: BLE001
        return None


def is_stale(max_age_days):
    """距上次刷新是否已达到 ``max_age_days`` 天。"""
    info = last_update()
    if not info or not info.get('updated_at'):
        return True
    try:
        t = datetime.fromisoformat(info['updated_at'])
    except ValueError:
        return True
    return (datetime.now() - t).total_seconds() / 86400.0 >= max_age_days


def write_stamp(payload):
    """写入刷新时间戳（供 ``--if-stale`` 判断）。"""
    os.makedirs(os.path.dirname(S.WEEKLY_STAMP), exist_ok=True)
    data = dict(payload)
    data['updated_at'] = datetime.now().isoformat(timespec='seconds')
    with open(S.WEEKLY_STAMP, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return S.WEEKLY_STAMP


# ═════════════════════════════════════════════════════════════════════════
# 三部分刷新
# ═════════════════════════════════════════════════════════════════════════

def update_spot(store, limit=None):
    """刷新 `factor_spot`（行业 / 市值 / PE / PB / 现价）。"""
    print('─' * 74)
    print('  ① 个股快照：行业 / 市值 / PE / PB / 现价')
    print('─' * 74)
    spot = network.fetch_spot()
    print(f'[spot] 抓取快照 {len(spot)} 只')
    ind_map = network.fetch_industry_map()
    print(f'[industry] 行业分类 {len(ind_map)} 只')

    codes = sorted(spot)
    if limit:
        codes = codes[:limit]
    today = date.today().isoformat()
    rows = []
    for code in codes:
        m = spot[code]
        rows.append((code, m.get('name') or '', ind_map.get(code),
                     board_of(code), to_float(m.get('per')), to_float(m.get('pb')),
                     to_float(m.get('mktcap')), to_float(m.get('nmc')),
                     to_float(m.get('price')), today))
    n = store.upsert_spot(rows)
    print(f'[spot] 已写入 {n:,} 行 -> {store.tables["spot"]}')
    return n


def update_kline(store, codes, workers, datalen, batch_size, refresh=False):
    """刷新 `factor_qfq_daily`（前复权收盘 + vol60 + mom60）。"""
    from backtest_model.factors.enrichers.context import fetch_klines_network

    print('─' * 74)
    print(f'  ② 前复权日线 + vol60/mom60：{len(codes):,} 只 × 最多 {datalen} 根')
    print('─' * 74)
    klines = fetch_klines_network(codes, datalen=datalen, workers=workers,
                                  refresh=refresh)
    flush_rows = max(batch_size * 20, 100_000)
    buf, total, done, ok, t0 = [], 0, 0, 0, time.perf_counter()

    for code in sorted(klines):
        v = klines.get(code)
        done += 1
        if v is None:
            continue
        ok += 1
        dates, closes = v[0], v[1]
        vol, mom = compute_metrics(closes)
        for j in range(len(dates)):
            buf.append((code, date_iso(dates[j]), to_f32(closes[j]),
                        None if vol[j] != vol[j] else float(vol[j]),
                        None if mom[j] != mom[j] else float(mom[j])))
        if len(buf) >= flush_rows:
            total += store.upsert_qfq(buf, batch_size)
            buf = []
            dt = time.perf_counter() - t0
            print(f'  [qfq] {done}/{len(klines)} 只  已写 {total:,} 行  '
                  f'{done / max(dt, .1):.1f} 只/s', flush=True)

    if buf:
        total += store.upsert_qfq(buf, batch_size)
    print(f'[qfq] 有效 {ok:,}/{len(klines):,} 只，写入 {total:,} 行 -> '
          f'{store.tables["qfq_daily"]}  用时 {time.perf_counter() - t0:.0f}s')
    return total


def update_index(store, index_code='000300', datalen=2800, batch_size=5000,
                 write_pkl=True):
    """刷新 `factor_index_daily`（沪深300）；可选同步改写本地指数 pkl。"""
    import pickle
    print('─' * 74)
    print(f'  ③ 指数日线：{index_code}')
    print('─' * 74)
    kl = network.fetch_index_series(index_code, datalen)
    if kl is None:
        print(f'[index] {index_code} 抓取失败，跳过')
        return 0
    dates, closes = kl
    rows = [(str(index_code), date_iso(d), to_f32(c)) for d, c in zip(dates, closes)]
    n = store.upsert_index(rows, batch_size)
    print(f'[index] 已写入 {n:,} 行 -> {store.tables["index_daily"]}  '
          f'({date_iso(int(dates[0]))} ~ {date_iso(int(dates[-1]))})')

    if write_pkl:
        os.makedirs(os.path.dirname(S.IDX_PKL), exist_ok=True)
        if os.path.isfile(S.IDX_PKL) and not os.path.isfile(
                S.IDX_PKL.replace('.pkl', '.bak_old.pkl')):
            import shutil
            shutil.copy2(S.IDX_PKL, S.IDX_PKL.replace('.pkl', '.bak_old.pkl'))
        with open(S.IDX_PKL, 'wb') as f:
            pickle.dump((np.asarray(dates, dtype=np.int32),
                         np.asarray(closes, dtype=np.float32)), f, protocol=4)
        print(f'[index] 已同步本地指数 -> {os.path.relpath(S.IDX_PKL, ROOT)}')
    return n


# ═════════════════════════════════════════════════════════════════════════
# 主流程
# ═════════════════════════════════════════════════════════════════════════

def print_status(store):
    """打印库表现状 + 上次刷新时间。"""
    try:
        st = store.stats()
    except Exception as e:                               # noqa: BLE001
        print(f'❌ 富化库不可用：{type(e).__name__}: {e}')
        return 1
    print('=' * 74)
    print('  富化库现状')
    print('=' * 74)
    for key, label in (('spot', '个股快照 factor_spot'),
                       ('qfq', '前复权日线 factor_qfq_daily'),
                       ('index', '指数日线 factor_index_daily')):
        s = st[key]
        print(f'  {label:<30} {s["rows"]:>10,} 行'
              f'  {s["min_date"] or "-"} ~ {s["max_date"] or "-"}')
    info = last_update()
    print(f'  上次刷新: {info.get("updated_at") if info else "（从未刷新）"}')
    if info:
        print(f'  刷新详情: {json.dumps(info.get("counts", {}), ensure_ascii=False)}')
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_enricher_config()
    upd = cfg.get('update', {})
    workers = args.workers or int(upd.get('workers', 8))
    datalen = args.datalen or int(upd.get('kline_datalen', 2800))
    batch = args.batch_size or int(upd.get('batch_size', 5000))
    index_code = str(upd.get('index_code', '000300'))
    max_age = int(upd.get('max_age_days', 7))

    S.ensure_dirs()
    os.makedirs(S.ENRICH_CACHE_DIR, exist_ok=True)
    store = FactorStore()

    if args.status:
        try:
            return print_status(store)
        finally:
            store.close()

    if args.if_stale and not is_stale(max_age):
        info = last_update() or {}
        print(f'⏭   距上次刷新（{info.get("updated_at")}）不足 {max_age} 天，'
              f'本次跳过（--if-stale）')
        return 0

    t0 = time.perf_counter()
    print('=' * 74)
    print('  富化数据刷新 —— 外网 → MySQL')
    print('=' * 74)
    print(f'  部分   : {args.only}')
    print(f'  股票池 : {args.universe}')
    print(f'  并发   : {workers}   日线长度: {datalen}   批大小: {batch}')
    print(f'  库表   : {config.get_factor_tables()}')
    print('=' * 74)

    try:
        store.ensure_tables()
    except Exception as e:                               # noqa: BLE001
        print(f'❌ 建表失败：{type(e).__name__}: {e}')
        return 2

    counts = {}
    try:
        if args.only in ('all', 'spot'):
            counts['spot'] = update_spot(store, limit=args.limit)

        if args.only in ('all', 'kline'):
            if args.universe == 'spot':
                codes = sorted(network.fetch_spot())
            else:
                codes = db_universe()
            if args.limit:
                codes = codes[:args.limit]
            if not codes:
                print('⚠️  股票池为空，跳过日线刷新')
            else:
                counts['qfq'] = update_kline(store, codes, workers, datalen,
                                             batch, refresh=args.refresh)

        if args.only in ('all', 'index'):
            counts['index'] = update_index(store, index_code, datalen, batch,
                                           write_pkl=not args.no_index_pkl)
    finally:
        store.close()

    write_stamp({'parts': args.only, 'counts': counts, 'workers': workers,
                 'datalen': datalen, 'tables': config.get_factor_tables()})

    print('=' * 74)
    print(f'✅ 刷新完成  用时 {time.perf_counter() - t0:.0f}s  '
          f'{json.dumps(counts, ensure_ascii=False)}')
    print(f'   时间戳 -> {os.path.relpath(S.WEEKLY_STAMP, ROOT)}'
          f'（--if-stale 依据，每 {max_age} 天视为过期）')
    print('=' * 74)
    print('下一步：python rebuild_signals.py  →  python enrich_signals.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())

