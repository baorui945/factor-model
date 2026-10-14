# -*- coding: utf-8 -*-
"""
==============================================================================
闸门对拍 —— 本地 factors 三因子模型 vs 主工程 ThreeFactorModelAnalyzer
==============================================================================

离线纯逻辑对拍（不连数据库）：对随机行情窗口分别用本地闸门模型与主工程
分析器做 F1 / F2 / F3 判定及整体 pattern 判定，逐条比对。

    python _gate_parity.py

两边判定结果须逐条一致（当前 800 组窗口下 F1/F2/F3 各 800/800）。
依赖主工程 `F:\\quantTrade\\analyzers`（仅用判定逻辑，不访问数据库）。
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

QUANT = r'F:\quantTrade'
sys.path.insert(0, QUANT)
from analyzers.three_factor_model_analyzer import ThreeFactorModelAnalyzer  # noqa: E402

from backtest_model.factors import ThreeFactorModel  # noqa: E402

ext = ThreeFactorModelAnalyzer(config={}, max_workers=1)
assert (ext.macd_fast, ext.macd_slow, ext.macd_signal) == (30, 89, 9)
assert (ext.ma_short, ext.ma_long) == (7, 21)
native = ThreeFactorModel()
assert native.macd == (30, 89, 9) and native.ma == (7, 21), (native.macd, native.ma)
assert [g.key for g in native.gates] == ['F1', 'F2', 'F3']
print('参数/闸门 ok:', native.macd, native.ma, [g.key for g in native.gates])


def make_df(n, seed):
    r = np.random.default_rng(seed)
    close = 10.0 * np.exp(np.cumsum(r.normal(0.0005, 0.03, n)))
    high = close * (1 + np.abs(r.normal(0, 0.01, n)))
    low = close * (1 - np.abs(r.normal(0, 0.01, n)))
    openp = close * (1 + r.normal(0, 0.005, n))
    return pd.DataFrame({
        'trade_date': pd.bdate_range('2018-01-01', periods=n),
        'open_price': openp, 'high_price': high, 'low_price': low,
        'close_price': close})


# 1) 指标逐位一致
d0 = make_df(420, 7)
ia = native.calculate_all_indicators(d0)
ib = ext.calculate_all_indicators(d0)
for c in ('dif', 'dea', 'macd', 'ma7', 'ma21'):
    assert np.allclose(ia[c].to_numpy(), ib[c].to_numpy(), equal_nan=True), c
print('指标计算逐位一致 ok')

# 2) 判定结果一致（随机窗口，含多样行情以覆盖各分支）
rng = np.random.default_rng(20261012)


def make_regime(n, seed):
    r = np.random.default_rng(seed)
    kind = int(r.integers(0, 5))
    if kind == 0:
        drift, vol = 0.004, 0.015          # 稳健上行
    elif kind == 1:
        drift, vol = 0.002, 0.030          # 上行+大波动
    elif kind == 2:
        drift, vol = -0.002, 0.020         # 下行
    elif kind == 3:
        drift, vol = 0.0, 0.025            # 震荡
    else:
        drift, vol = 0.003, 0.010          # 慢牛
    ret = r.normal(drift, vol, n)
    close = 10.0 * np.exp(np.cumsum(ret))
    high = close * (1 + np.abs(r.normal(0, 0.008, n)))
    low = close * (1 - np.abs(r.normal(0, 0.008, n)))
    openp = close * (1 + r.normal(0, 0.004, n))
    return pd.DataFrame({
        'trade_date': pd.bdate_range('2018-01-01', periods=n),
        'open_price': openp, 'high_price': high, 'low_price': low,
        'close_price': close})


N = 800
stats = {'F1': [0, 0], 'F2': [0, 0], 'F3': [0, 0]}   # [match, ext_pos]
mismatch = {'F1': 0, 'F2': 0, 'F3': 0, 'pattern': 0}
for k in range(N):
    n = int(rng.integers(120, 420))
    df = make_regime(n, 5000 + k)
    if len(df) < native.ma_long + 5:
        continue
    di = ext.calculate_all_indicators(df.copy())
    ext_checks = {'F1': ext.check_factor1, 'F2': ext.check_factor2, 'F3': ext.check_factor3}
    nat_checks = {g.key: g for g in native.gates}
    for key in ('F1', 'F2', 'F3'):
        e_ok, _ = ext_checks[key](di)
        n_ok, _ = nat_checks[key].check(di)
        if bool(e_ok) == bool(n_ok):
            stats[key][0] += 1
        else:
            mismatch[key] += 1
        stats[key][1] += int(bool(e_ok))
    a = bool(native.analyze_pattern(df)['pattern_detected'])
    b = bool(ext.analyze_pattern(df)['pattern_detected'])
    if a != b:
        mismatch['pattern'] += 1

for key in ('F1', 'F2', 'F3'):
    print('  %s  match=%d  ext_pos=%d' % (key, stats[key][0], stats[key][1]))
print('  pattern mismatch=%d' % mismatch['pattern'])
assert sum(mismatch.values()) == 0, mismatch
print('PHASE2 PARITY PASS')
