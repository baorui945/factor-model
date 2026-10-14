# -*- coding: utf-8 -*-
"""
==============================================================================
净值图 —— 6 面板回测总览
==============================================================================

① 各组合净值   ② S1 不同持有期   ③ 风险收益散点
④ 年度收益     ⑤ S1 逐笔收益分布 ⑥ 每日持仓只数
"""

import os

import numpy as np
import pandas as pd

from . import engine as E

_PANEL_COLORS = {'ALL': '#9AA0A6', 'A': '#F58518', 'S1': '#4C78A8',
                 'S2': '#B279A2', 'S3': '#54A24B', 'S4': '#E45756'}
_HORIZON_COLORS = {20: '#4C78A8', 30: '#F58518', 40: '#54A24B', 60: '#E45756'}


def plot_backtest(panel, res, meta, nav_base, trades, horizons, cost, out_png):
    """绘制并保存 6 面板回测图，返回 PNG 路径。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei',
                                       'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False

    cal = panel.calendar
    h0 = horizons[0]

    fig = plt.figure(figsize=(17.5, 10.5))
    fig.suptitle(f'三因子买点「最优组合」策略级回测（信号日收盘建仓 · 等权日度组合 · '
                 f'双边成本 {cost:.2%}）', fontsize=15, fontweight='bold')

    # ① 各组合净值（主持有期）
    ax = fig.add_subplot(2, 3, 1)
    for key, (name, _) in meta.items():
        ax.plot(cal, res[(key, h0)]['nav'], color=_PANEL_COLORS[key], lw=1.4,
                label=f'{key} {name}')
    ax.plot(cal, nav_base, color='k', ls='--', lw=1.4, label='沪深300')
    ax.axhline(1.0, color='gray', lw=.7)
    ax.set_title(f'① 各组合净值（持有 {h0} 日）', fontsize=11)
    ax.set_ylabel('净值'); ax.legend(fontsize=7.5); ax.grid(alpha=.3)

    # ② 最优组合 S1 各持有期
    ax = fig.add_subplot(2, 3, 2)
    for h in horizons:
        ax.plot(cal, res[('S1', h)]['nav'], color=_HORIZON_COLORS.get(h, 'gray'),
                lw=1.4, label=f'持有 {h} 日')
    ax.plot(cal, nav_base, color='k', ls='--', lw=1.4, label='沪深300')
    ax.axhline(1.0, color='gray', lw=.7)
    ax.set_title('② 最优组合 S1：不同持有期', fontsize=11)
    ax.legend(fontsize=8); ax.grid(alpha=.3)

    # ③ 风险收益散点
    ax = fig.add_subplot(2, 3, 3)
    for (key, h), r in res.items():
        m = E.perf_metrics(r['nav'], cal, r['years'], r['hold_cnt'])
        ax.scatter(m['最大回撤(%)'], m['年化收益(%)'],
                   color=_PANEL_COLORS[key], s=70 if h == h0 else 30,
                   edgecolor='k', linewidth=.4, zorder=3)
        if h == h0:
            ax.annotate(key, (m['最大回撤(%)'], m['年化收益(%)']),
                        fontsize=9, xytext=(4, 4), textcoords='offset points')
    bm_ = E.perf_metrics(nav_base, cal, E.years_of(cal))
    ax.scatter(bm_['最大回撤(%)'], bm_['年化收益(%)'], color='k', marker='*',
               s=180, zorder=4, label='沪深300')
    ax.axhline(0, color='gray', lw=.7); ax.axvline(0, color='gray', lw=.7)
    ax.set_xlabel('最大回撤 %'); ax.set_ylabel('年化收益 %')
    ax.set_title('③ 风险收益（圆=各持有期，粗圆=主持有期）', fontsize=11)
    ax.grid(alpha=.3); ax.legend(fontsize=8)

    # ④ 年度收益
    ax = fig.add_subplot(2, 3, 4)
    years = sorted({d.year for d in cal})
    keys4 = ['ALL', 'A', 'S1', 'S3', 'S4']
    w = .8 / (len(keys4) + 1)
    xs = np.arange(len(years))
    for i, key in enumerate(keys4):
        rr = E.period_returns(res[(key, h0)]['nav'], cal, 'YE')
        vals = [float(rr.get(pd.Timestamp(f'{y}-12-31'), np.nan)) * 100
                for y in years]
        ax.bar(xs + (i - len(keys4) / 2) * w, vals, w,
               color=_PANEL_COLORS[key], label=key)
    rr = E.period_returns(nav_base, cal, 'YE')
    ax.bar(xs + (len(keys4) / 2) * w,
           [float(rr.get(pd.Timestamp(f'{y}-12-31'), np.nan)) * 100
            for y in years], w, color='k', label='沪深300')
    ax.axhline(0, color='k', lw=.8)
    ax.set_xticks(xs); ax.set_xticklabels(years)
    ax.set_title(f'④ 年度收益 %（持有 {h0} 日）', fontsize=11)
    ax.legend(fontsize=7.5); ax.grid(axis='y', alpha=.3)

    # ⑤ S1 逐笔收益分布
    ax = fig.add_subplot(2, 3, 5)
    tr = trades['S1'][h0]
    if len(tr):
        det = E.trades_detail(panel, tr, cost=0.0)
        g = det['毛收益(%)'].to_numpy()
        ax.hist(g, bins=28, color='#4C78A8', edgecolor='white', alpha=.9)
        ax.axvline(0, color='k', lw=1)
        ax.axvline(g.mean(), color='#E45756', lw=1.6, ls='--',
                   label=f'均值 {g.mean():.2f}%')
        ax.axvline(np.median(g), color='#54A24B', lw=1.6, ls=':',
                   label=f'中位 {np.median(g):.2f}%')
        ax.set_title(f'⑤ S1 逐笔毛收益分布（{len(tr)} 笔 · 胜率 '
                     f'{(g > 0).mean() * 100:.1f}%）', fontsize=11)
        ax.set_xlabel('毛收益 %'); ax.set_ylabel('笔数'); ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=.3)

    # ⑥ 持仓只数
    ax = fig.add_subplot(2, 3, 6)
    ax.plot(cal, res[('S1', h0)]['hold_cnt'], color='#4C78A8', lw=1.1,
            label=f'S1 (持有{h0}日)')
    ax.plot(cal, res[('A', h0)]['hold_cnt'], color='#F58518', lw=1.0,
            alpha=.8, label=f'A (持有{h0}日)')
    ax.set_title('⑥ 每日持仓只数（资金利用率）', fontsize=11)
    ax.set_ylabel('只'); ax.legend(fontsize=8); ax.grid(alpha=.3)

    fig.tight_layout(rect=(0, 0, 1, 0.965))
    os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
    fig.savefig(out_png, dpi=110)
    plt.close(fig)
    return out_png
