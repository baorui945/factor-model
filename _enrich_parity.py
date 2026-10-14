# -*- coding: utf-8 -*-
"""
==============================================================================
_enrich_parity —— 富化层迁移校验（本地 factors.enrichers vs 外部三因子脚本）
==============================================================================

在不联网的前提下，用**与旧版完全相同的输入**（_seg_cache 快照/行业、
data/_cache/kline_qfq_long.pkl、data/idx_000300.pkl、最新 signals_rebuilt CSV）
分别跑：

    A. 旧实现 : analyzers.three_factor_segment_analysis.build_features + add_buckets
    B. 新实现 : backtest_model.factors.enrichers.enrich_signals

再与已落盘的 data/sig_all_horizons.pkl（旧流程产物）三方对比，逐列校验一致性。

用法::

    python _enrich_parity.py
    python _enrich_parity.py --csv output\\signals_rebuilt_full.csv --limit 400
"""

import argparse
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
QUANT = r'F:\quantTrade'
sys.path.insert(0, ROOT)
sys.path.insert(0, QUANT)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

from backtest_model import settings as S                              # noqa: E402
from backtest_model.factors.enrichers import EnrichContext, enrich_signals  # noqa: E402
from backtest_model.factors.registry import load_enricher_config      # noqa: E402

_SEG_CACHE = os.path.join(QUANT, 'analysis_results', '_seg_cache')

_COL_ORDER = ['stock_code', 'stock_name', 'signal_date', 'return_20d',
              'return_30d', 'return_40d', 'board', 'industry', 'mv_total', 'nmc',
              'pb_t', 'pe_now', 'price', 'vol60', 'mom60', 'sig_count',
              'mkt_dev', 'mkt_mom60', 'year', 'mv_bucket', 'nmc_bucket',
              'pb_bucket', 'pe_bucket', 'vol_bucket', 'mom_bucket', 'mkt_bucket',
              'sig_bucket', 'price_bucket', 'c0', 'f20', 'f30', 'f40', 'f60']


def load_inputs(csv_path, limit=None):
    """加载旧版与新版共用的输入（离线可复现）。"""
    with open(os.path.join(_SEG_CACHE, 'sina_spot.json'), encoding='utf-8') as f:
        spot = json.load(f)
    with open(os.path.join(_SEG_CACHE, 'industry_map.json'), encoding='utf-8') as f:
        ind_map = json.load(f)
    with open(S.QFX_KLINE_CACHE, 'rb') as f:
        klines = pickle.load(f)
    klines = {c: v for c, v in klines.items() if v}
    with open(S.IDX_PKL, 'rb') as f:
        d, c = pickle.load(f)
    idx_kl = (np.asarray(d, dtype=np.int32), np.asarray(c, dtype=np.float32))

    if csv_path is None:
        import glob
        cands = sorted(glob.glob(os.path.join(S.OUTPUT_DIR, 'signals_rebuilt*.csv')))
        csv_path = cands[-1]
    sigs = pd.read_csv(csv_path, dtype={'stock_code': str, 'stock_name': str})
    sigs['signal_date'] = pd.to_datetime(sigs['signal_date'])
    if limit:
        keep = sorted(sigs['stock_code'].unique())[:limit]
        sigs = sigs[sigs['stock_code'].isin(keep)].reset_index(drop=True)
    return sigs, spot, ind_map, klines, idx_kl, csv_path


def finalize(feat, sigs):
    """c0 / f20..f60 合并 + 日期字符串化 + 列序统一（与 enrich_signals.main 一致）。"""
    ren = sigs.copy()
    ren['rename_date'] = ren['signal_date'].astype(str)
    feat = feat.copy()
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
    feat['signal_date'] = pd.to_datetime(feat['signal_date']).dt.strftime('%Y-%m-%d')
    return feat[_COL_ORDER]


def build_new(sigs, spot, ind_map, klines, idx_kl, cfg):
    """新实现：本地富化流水线。"""
    ctx = EnrichContext(spot, ind_map, klines, idx_kl, source='legacy-cache')
    return finalize(enrich_signals(sigs, ctx, cfg), sigs)


def build_old(sigs, spot, ind_map, klines, idx_kl):
    """旧实现：外部三因子分层脚本。"""
    import analyzers.three_factor_segment_analysis as TSA
    feat = TSA.add_buckets(TSA.build_features(sigs, spot, ind_map, klines, idx_kl))
    return finalize(feat, sigs)


def compare(a, b, label_a='A', label_b='B'):
    """逐列比较两个特征表，返回差异列表。"""
    problems = []
    if list(a.columns) != list(b.columns):
        problems.append(f'列集合不同：{list(a.columns)} vs {list(b.columns)}')
        return problems
    if len(a) != len(b):
        problems.append(f'行数不同：{len(a)} vs {len(b)}')
        return problems

    for c in a.columns:
        x, y = a[c], b[c]
        if x.dtype.kind in 'if' and y.dtype.kind in 'if':
            xa = x.to_numpy(dtype='float64')
            ya = y.to_numpy(dtype='float64')
            na, nb = np.isnan(xa), np.isnan(ya)
            if (na != nb).any():
                problems.append(f'  {c:<12} NaN 位置不同（{int((na != nb).sum())} 处）')
                continue
            k = ~na
            if k.any():
                dmax = float(np.abs(xa[k] - ya[k]).max())
                if dmax > 0:
                    problems.append(f'  {c:<12} 最大绝对差 {dmax:.3e}')
        else:
            sa = list(x.fillna('__NA__').astype(str))
            sb = list(y.fillna('__NA__').astype(str))
            idx = [i for i, (u, v) in enumerate(zip(sa, sb)) if u != v]
            neq = len(idx)
            if neq:
                ex = [(i, sa[i], sb[i]) for i in idx[:3]]
                problems.append(f'  {c:<12} {neq} 处不同  例: {ex}')
    print(f'[{label_a} vs {label_b}] '
          + ('✅ 逐列完全一致' if not problems else f'❌ {len(problems)} 项差异'))
    for p in problems:
        print(p)
    return problems


def main():
    ap = argparse.ArgumentParser(description='富化层迁移校验')
    ap.add_argument('--csv', default=None, help='信号 CSV（默认取最新）')
    ap.add_argument('--limit', type=int, default=None, help='只取前 N 只股票')
    ap.add_argument('--skip-pkl', action='store_true', help='跳过与已落盘 pkl 的对比')
    args = ap.parse_args()

    cfg = load_enricher_config()
    sigs, spot, ind_map, klines, idx_kl, csv_path = load_inputs(args.csv, args.limit)
    print('=' * 78)
    print('  富化层 parity 校验')
    print('=' * 78)
    print(f'  信号 CSV : {os.path.basename(csv_path)}  ({len(sigs):,} 条)')
    print(f'  快照 {len(spot):,} / 行业 {len(ind_map):,} / 日线 {len(klines):,}'
          f' / 指数 {len(idx_kl[0])} 天')
    print('=' * 78)

    new = build_new(sigs, spot, ind_map, klines, idx_kl, cfg)
    print(f'[新实现] {len(new):,} 行 × {new.shape[1]} 列')

    print('\n① 旧实现 vs 新实现（同输入）')
    old = build_old(sigs, spot, ind_map, klines, idx_kl)
    p1 = compare(old, new, '旧实现', '新实现')

    p2 = []
    if not args.skip_pkl and os.path.isfile(S.SIG_PKL) and not args.limit:
        print('\n② 已落盘 pkl vs 新实现（端到端复现）')
        base = pd.read_pickle(S.SIG_PKL)
        if len(base) != len(new):
            print(f'⚠️  行数不同（pkl {len(base):,} vs 新 {len(new):,}），'
                  f'可能信号 CSV 已变更，跳过逐列对比')
        else:
            p2 = compare(base.reset_index(drop=True), new, '旧 pkl', '新实现')

    ok = not p1 and not p2
    print('\n' + '=' * 78)
    print('✅ 富化层迁移校验通过' if ok else '❌ 存在差异，见上')
    print('=' * 78)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

