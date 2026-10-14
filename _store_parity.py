# -*- coding: utf-8 -*-
"""
==============================================================================
_store_parity —— 富化库落库 / 回读 精度校验（FactorStore 硬校验）
==============================================================================

校验 `factors.enrichers.store.FactorStore` 的落库→回读链路是否**零损失**，
从而保证把富化数据沉淀进 MySQL 后，`sig_all_horizons.pkl` 不漂移。

步骤（取 40 只有信号的股票，用 _seg_cache 快照/行业 + kline_qfq_long.pkl）：

    ① 内存路径富化            → 基准结果 base
    ② 写入 factor_spot / factor_qfq_daily
    ③ 回读 spot / klines 与原始输入逐位比对（重点：float32 收盘往返）
    ④ 用 load_context(source='store') 重新富化 → 与 base 逐列比对
    ⑤ 再测 use_stored_metrics=True 快路径（直接用库里的 vol60/mom60）
    ⑥ **自动清理**本次写入的测试行（库表恢复为空，等首次正式刷新）

用法::

    python _store_parity.py
"""

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

from backtest_model import settings as S                                  # noqa: E402
from backtest_model.factors.enrichers import (EnrichContext, enrich_signals,  # noqa: E402
                                              load_context)
from backtest_model.factors.enrichers.metrics import board_of, compute_metrics  # noqa: E402
from backtest_model.factors.enrichers.store import (FactorStore, date_iso,  # noqa: E402
                                                    to_f32, to_float)
from backtest_model.factors.registry import load_enricher_config          # noqa: E402

SEG = r'F:\quantTrade\analysis_results\_seg_cache'
N_CODES = 40


def main():
    with open(os.path.join(SEG, 'sina_spot.json'), encoding='utf-8') as f:
        spot = json.load(f)
    with open(os.path.join(SEG, 'industry_map.json'), encoding='utf-8') as f:
        ind_map = json.load(f)
    with open(S.QFX_KLINE_CACHE, 'rb') as f:
        klines = {c: v for c, v in pickle.load(f).items() if v}

    # 抽 N 只股票的信号（用最新 CSV 中出现的票，保证有信号可富化）
    import glob
    csv = sorted(glob.glob(os.path.join(S.OUTPUT_DIR, 'signals_rebuilt*.csv')))[-1]
    sigs = pd.read_csv(csv, dtype={'stock_code': str, 'stock_name': str})
    sigs['signal_date'] = pd.to_datetime(sigs['signal_date'])
    codes = [c for c in sorted(sigs['stock_code'].unique()) if c in klines][:N_CODES]
    sigs = sigs[sigs['stock_code'].isin(codes)].reset_index(drop=True)
    print(f'测试股票 {len(codes)} 只 / 信号 {len(sigs)} 条')

    cfg = load_enricher_config()
    idx = pickle.load(open(S.IDX_PKL, 'rb'))
    idx_kl = (np.asarray(idx[0], dtype=np.int32), np.asarray(idx[1], dtype=np.float32))

    # ① 旧路径（内存）结果作为基准
    ctx_mem = EnrichContext(spot, ind_map, {c: klines[c] for c in codes},
                            idx_kl, source='memory')
    base = enrich_signals(sigs, ctx_mem, cfg)

    # ② 落库
    store = FactorStore()
    store.ensure_tables()
    today = '2026-10-12'
    spot_rows = [(c, spot.get(c, {}).get('name', ''), ind_map.get(c),
                  board_of(c), to_float(spot.get(c, {}).get('per')),
                  to_float(spot.get(c, {}).get('pb')),
                  to_float(spot.get(c, {}).get('mktcap')),
                  to_float(spot.get(c, {}).get('nmc')),
                  to_float(spot.get(c, {}).get('price')), today)
                 for c in codes]
    qfq_rows = []
    for c in codes:
        d, cl = klines[c]
        vol, mom = compute_metrics(cl)
        for j in range(len(d)):
            qfq_rows.append((c, date_iso(d[j]), to_f32(cl[j]),
                             None if vol[j] != vol[j] else float(vol[j]),
                             None if mom[j] != mom[j] else float(mom[j])))
    print(f'写入 spot {store.upsert_spot(spot_rows):,} 行 / '
          f'qfq {store.upsert_qfq(qfq_rows, 5000):,} 行')

    # ③ 回读并逐位比对原始输入
    spot2 = store.load_spot()
    kl2 = store.load_klines(codes)
    bad = 0
    for c in codes:
        if str(spot2.get(c, {}).get('nmc')) != str(to_float(spot[c]['nmc'])):
            bad += 1
        d0, c0 = klines[c]
        d1, c1 = kl2[c][:2]
        if not np.array_equal(np.asarray(d0, dtype=np.int64), d1):
            bad += 1
        if not np.array_equal(np.asarray(c0, dtype=np.float32), c1):
            bad += 1
    print(f'回读原始输入不一致项 = {bad}')

    # ④ 用库表组装 ctx 再富化，与基准逐列比对
    ctx_db = load_context(codes, source='store')
    print('ctx_db:', ctx_db)
    new = enrich_signals(sigs, ctx_db, cfg)
    problems = []
    for col in base.columns:
        x, y = base[col], new[col]
        if x.dtype.kind in 'if' and y.dtype.kind in 'if':
            xa, ya = x.to_numpy('float64'), y.to_numpy('float64')
            if (np.isnan(xa) != np.isnan(ya)).any():
                problems.append(f'{col}: NaN 位置不同')
            else:
                k = ~np.isnan(xa)
                if k.any() and float(np.abs(xa[k] - ya[k]).max()) > 0:
                    problems.append(f'{col}: 最大差 '
                                    f'{float(np.abs(xa[k] - ya[k]).max()):.3e}')
        elif list(x.fillna('_').astype(str)) != list(y.fillna('_').astype(str)):
            problems.append(f'{col}: 取值不同')
    print('富化列差异:', problems if problems else '✅ 逐列完全一致')

    # ⑤ 另测 stored metrics 快路径是否等价
    ctx_db2 = load_context(codes, source='store')
    ctx_db2.use_stored_metrics = True
    new2 = enrich_signals(sigs, ctx_db2, cfg)
    d = float(np.nanmax(np.abs(new2['vol60'].to_numpy('float64')
                               - base['vol60'].to_numpy('float64'))))
    d2 = float(np.nanmax(np.abs(new2['mom60'].to_numpy('float64')
                                - base['mom60'].to_numpy('float64'))))
    print(f'stored-metrics 快路径: vol60 max|diff|={d:.3e}  mom60 max|diff|={d2:.3e}')

    # ⑥ 清理测试数据（保持库表为空，等首次正式刷新）
    cn = store.connect(verbose=False)
    with cn.cursor() as cur:
        cur.execute(f'DELETE FROM {store.tables["spot"]} WHERE stock_code IN '
                    f'({",".join(["%s"] * len(codes))})', codes)
        cur.execute(f'DELETE FROM {store.tables["qfq_daily"]} WHERE stock_code IN '
                    f'({",".join(["%s"] * len(codes))})', codes)
    cn.commit()
    print('测试数据已清理；当前库表:', store.stats())
    store.close()
    return 1 if (bad or problems) else 0


if __name__ == '__main__':
    sys.exit(main())
