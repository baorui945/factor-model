# -*- coding: utf-8 -*-
"""
_parity_report.py —— 新旧信号池对拍明细（重叠区间差异的分布）

    python _parity_report.py [新池 pkl] [旧池 pkl]

默认：data/sig_all_horizons.pkl  vs  data/sig_all_horizons.orig_20261011.pkl
"""

import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))


def keys(df: pd.DataFrame) -> set:
    d = df[['stock_code', 'signal_date']].copy()
    d['stock_code'] = d['stock_code'].astype(str).str.zfill(6)
    d['signal_date'] = d['signal_date'].astype(str)
    return set(map(tuple, d.to_numpy()))


def load_keys(path: str):
    d = pd.read_pickle(path)
    k = keys(d)
    return d, k


def main(argv):
    new_p = os.path.join(ROOT, 'data', 'sig_all_horizons.pkl')
    old_p = os.path.join(ROOT, 'data', 'sig_all_horizons.pre_tdx_20261011.pkl')
    if len(argv) > 1:
        new_p = argv[1]
    if len(argv) > 2:
        old_p = argv[2]

    new_d, kn = load_keys(new_p)
    old_d, ko = load_keys(old_p)
    print(f'新池 {os.path.basename(new_p)} : {len(kn):,} 条 / {new_d.stock_code.nunique()} 只 '
          f'{str(new_d.signal_date.min())[:10]} ~ {str(new_d.signal_date.max())[:10]}')
    print(f'旧池 {os.path.basename(old_p)} : {len(ko):,} 条 / {old_d.stock_code.nunique()} 只 '
          f'{str(old_d.signal_date.min())[:10]} ~ {str(old_d.signal_date.max())[:10]}')
    print(f'交集  : {len(kn & ko):,}')
    print()

    lo = str(old_d.signal_date.min())[:10]
    hi = str(old_d.signal_date.max())[:10]
    codes = set(old_d.stock_code.astype(str).str.zfill(6))
    nn = pd.DataFrame(sorted(kn), columns=['stock_code', 'signal_date'])
    span = nn[(nn.stock_code.isin(codes)) & (nn.signal_date >= lo) &
              (nn.signal_date <= hi)]
    print(f'重叠窗口（旧池有该股 且 {lo} ~ {hi}）新信号: {len(span):,}')
    ex = span[~span.apply(tuple, axis=1).isin(ko)]
    mis = pd.DataFrame(sorted(ko - kn), columns=['stock_code', 'signal_date'])
    mis = mis[(mis.stock_code.isin(set(nn.stock_code))) &
              (mis.signal_date >= str(new_d.signal_date.min())[:10])]
    print(f'  新多出: {len(ex):,}（占窗口内 {len(ex) / max(len(span), 1):.2%}）')
    print(f'  新多出 按年: {ex.signal_date.str[:4].value_counts().sort_index().to_dict()}')
    print(f'  新多出 涉及股票: {ex.stock_code.nunique()} 只')
    print(f'  旧有但新无（限新池日期区间）: {len(mis):,}')
    print(f'  旧有但新无 按月: {mis.signal_date.str[:7].value_counts().sort_index().to_dict()}')
    print()
    print('新多出 样例:')
    print(ex.head(10).to_string(index=False))
    print('旧有但新无 样例:')
    print(mis.head(10).to_string(index=False))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
