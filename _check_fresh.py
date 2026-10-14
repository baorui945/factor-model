# -*- coding: utf-8 -*-
"""
_check_fresh.py —— 数据新鲜度体检：DB 表 vs 本地缓存/信号池/指数

    python _check_fresh.py

输出各项的最新日期，用来判断「要不要重跑整条链路」：
    DB 表最新日 > 价格缓存最新日  → 需要 --refresh 重拉价格
    DB 表最新日 > 信号池最新日+60 → 需要重跑 rebuild_signals + enrich_signals
"""

import os
import sys

import pandas as pd
import pymysql

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config                                                   # noqa: E402
from backtest_model import settings as S                        # noqa: E402


def main() -> int:
    tbl = config.TABLE_BACKWARD_DAILY
    print(f'表        : {tbl}')
    print(f'.env      : {config.describe()}')
    print()

    cfg = config.get_db_config()
    con = pymysql.connect(**cfg)
    try:
        with con.cursor() as cur:
            cur.execute(f'SELECT COUNT(*), MIN(trade_date), MAX(trade_date) '
                        f'FROM `{tbl}`')
            n, dmin, dmax = cur.fetchone()
            cur.execute(f'SELECT COUNT(DISTINCT stock_code) FROM `{tbl}`')
            ncode = cur.fetchone()[0]
            cur.execute(f'SELECT COUNT(*) FROM `{tbl}` WHERE trade_date = %s',
                        (dmax,))
            nlast = cur.fetchone()[0]
    finally:
        con.close()
    print(f'[DB  ] {n:,} 行 / {ncode:,} 只  {dmin} ~ {dmax}'
          f'（末日 {nlast:,} 只）')

    if os.path.isfile(S.PX_CACHE):
        px = pd.read_parquet(S.PX_CACHE, columns=['stock_code', 'trade_date'])
        print(f'[价格] {len(px):,} 行 / {px["stock_code"].nunique():,} 只  '
              f'{px["trade_date"].min().date()} ~ {px["trade_date"].max().date()}')
    else:
        print('[价格] 缓存不存在')

    if os.path.isfile(S.SIG_PKL):
        sig = pd.read_pickle(S.SIG_PKL)
        sd = sig['signal_date'].astype(str)
        print(f'[信号] {len(sig):,} 条 / {sig["stock_code"].nunique():,} 只  '
              f'{sd.min()} ~ {sd.max()}')
    else:
        print('[信号] pkl 不存在')

    if os.path.isfile(S.IDX_PKL):
        d, _c = pd.read_pickle(S.IDX_PKL)
        print(f'[指数] {len(d):,} 根  {str(int(d[0]))} ~ {str(int(d[-1]))}')
    else:
        print('[指数] pkl 不存在')

    # ── 富化库（run_update_factors.py 每周刷新，见 README §12）──────────
    try:
        from backtest_model.factors.enrichers.store import FactorStore
        with FactorStore() as store:
            st = store.stats()
        for key, label in (('spot', '快照  '), ('qfq', '前复权'),
                           ('index', '指数  ')):
            s = st[key]
            print(f'[富化:{label}] {s["rows"]:>10,} 行  '
                  f'{s["min_date"] or "-"} ~ {s["max_date"] or "-"}')
        if os.path.isfile(S.WEEKLY_STAMP):
            import json
            with open(S.WEEKLY_STAMP, encoding='utf-8') as f:
                info = json.load(f)
            print(f'[富化:刷新] {info.get("updated_at")}')
        else:
            print('[富化:刷新] 从未刷新 —— 先跑 run_update_factors.py')
    except Exception as e:                               # noqa: BLE001
        print(f'[富化] 库表不可用（{type(e).__name__}: {e}）'
              f'—— 先跑 python run_update_factors.py')
    return 0


if __name__ == '__main__':
    sys.exit(main())
