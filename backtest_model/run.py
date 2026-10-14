# -*- coding: utf-8 -*-
"""
==============================================================================
回测主入口（CLI）—— 三因子买点「最优组合」策略级回测
==============================================================================

流程：加载信号 -> 抓价格建面板 -> 逐组合 × 持有期回测 -> 构建各表 ->
      导出多 Sheet Excel（+ 可选 6 面板净值图 + CSV 备份）。

用法::

    python run_backtest.py
    python run_backtest.py --horizons 20 --no-cost --out D:\\out.xlsx
    python run_backtest.py --chart                      # 额外输出净值图
    python run_backtest.py --refresh                    # 强制重拉价格缓存
"""

import argparse
import os
import sys
from datetime import datetime

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from . import settings as S
    from . import data as D
    from . import engine as E
    from . import analysis as A
    from . import excel_report as X
    from . import charts as CH
    from .combos import BEST_KEY
except ImportError:                                       # 直接以脚本运行
    from backtest_model import settings as S              # type: ignore
    from backtest_model import data as D                  # type: ignore
    from backtest_model import engine as E                # type: ignore
    from backtest_model import analysis as A              # type: ignore
    from backtest_model import excel_report as X          # type: ignore
    from backtest_model import charts as CH               # type: ignore
    from backtest_model.combos import BEST_KEY            # type: ignore


def build_parser() -> argparse.ArgumentParser:
    """构建回测命令行参数。"""
    ap = argparse.ArgumentParser(
        prog='backtest',
        description='三因子买点「最优组合」策略级回测（日频净值 + Excel 导出）')
    ap.add_argument('--horizons', default=S.DEF_HORIZONS,
                    help=f'持有期列表（交易日），第一个为主口径，默认 {S.DEF_HORIZONS}')
    ap.add_argument('--cost', type=float, default=S.DEF_COST,
                    help=f'双边成本（小数），默认 {S.DEF_COST}')
    ap.add_argument('--no-cost', action='store_true', help='关闭交易成本')
    ap.add_argument('--start', default=S.DEF_START, help=f'价格起始日，默认 {S.DEF_START}')
    ap.add_argument('--refresh', action='store_true', help='强制重拉价格缓存')
    ap.add_argument('--out', default=None, help='输出 xlsx 路径')
    ap.add_argument('--chart', action='store_true', help='额外输出 6 面板净值图 PNG')
    ap.add_argument('--png', default=None, help='PNG 输出路径')
    ap.add_argument('--quiet', action='store_true', help='不打印逐组合明细')
    return ap


def main(argv=None) -> int:
    """回测入口。"""
    args = build_parser().parse_args(argv)
    S.ensure_dirs()

    cost = 0.0 if args.no_cost else args.cost
    horizons = [int(x) for x in args.horizons.split(',') if x.strip()]
    h0 = horizons[0]

    print('=' * 76)
    print('  三因子买点「最优组合」策略级回测')
    print('=' * 76)

    sig = D.load_signals()
    print(f'[信号] {len(sig):,} 条 / {sig["stock_code"].nunique()} 只  '
          f'{sig["signal_date"].min()} ~ {sig["signal_date"].max()}')

    panel, _idx, nav_base = D.build_panel(sig, args.start, refresh=args.refresh)
    cal = panel.calendar
    print(f'[面板] {len(cal)} 交易日 × {len(panel.codes)} 只  '
          f'{cal[0].date()} ~ {cal[-1].date()}')

    print(f'\n【逐组合 × 持有期 回测】(成本 {cost:.2%})')
    res, trades, sigs, meta = A.run_grid(panel, sig, horizons, cost,
                                         verbose=not args.quiet)

    tt = A.build_perf_table(res, meta, panel, nav_base, horizons, cost)
    print('\n' + '=' * 150)
    print(f'【绩效总览】(主口径持有期 {h0} 日)')
    print('=' * 150)
    show = tt[['组合', '持有期(交易日)', '原始信号数', '去重交易笔数', '涉及股票数',
               '平均持仓只数', '总收益(%)', '年化收益(%)', '年化波动(%)', '夏普',
               '最大回撤(%)', 'Calmar', '资金利用率(%)', '持仓日胜率(%)',
               '日胜率含空仓(%)']]
    print(show.to_string(index=False))

    ann = A.build_annual(res, meta, panel, nav_base, horizons)
    print('\n【年度收益 %】')
    print(ann.to_string(index=False))

    print(f'\n【最优组合 {BEST_KEY} 逐笔交易 摘要】')
    tr = E.trades_detail(panel, trades[BEST_KEY][h0], cost)
    if len(tr):
        g = tr['毛收益(%)'].to_numpy()
        n = tr['净收益(%)'].to_numpy()
        print(f'  交易 {len(tr)} 笔 | 毛收益 均值 {g.mean():.2f}% 中位 {np.median(g):.2f}% '
              f'胜率 {(g > 0).mean() * 100:.1f}%')
        print(f'  净收益 均值 {n.mean():.2f}% | 最好 {g.max():.2f}% 最差 {g.min():.2f}% '
              f'| 盈亏比 {g[g > 0].mean() / abs(g[g < 0].mean()):.2f}')
        print(tr.sort_values('毛收益(%)', ascending=False).head(8).to_string(index=False))

    sens = A.build_sensitivity(panel, sig, horizons, cost)
    lay = A.build_factor_layers(panel, sig, h0)
    navc = A.build_nav_curve(panel, res, meta, nav_base, horizons)
    mon = A.build_monthly(res, meta, panel, nav_base, horizons)
    rd = A.build_readme(panel, res, meta, horizons, cost, refresh=args.refresh)

    year_cols = [c for c in ann.columns if c.isdigit()]
    mon_cols = [c for c in mon.columns if '-' in c]

    sheets = [
        ('回测说明', rd, {'cap': 90}),
        ('绩效总览', tt, {'cap': 30, 'freeze': 'A2',
                      'color': ('总收益(%)', '年化收益(%)', '夏普', '最大回撤(%)',
                                'Calmar', '资金利用率(%)', '持仓日胜率(%)',
                                '日胜率含空仓(%)', '日均收益(bp)')}),
        ('净值曲线', navc, {'cap': 22, 'freeze': 'B2',
                        'color': (f'{BEST_KEY} 当日收益(%)',)}),
        ('年度收益', ann, {'cap': 12, 'color': tuple(year_cols)}),
        ('月度收益', mon, {'cap': 11, 'color': tuple(mon_cols)}),
        ('交易明细', tr, {'cap': 20, 'freeze': 'A2', 'text': ('股票代码',),
                      'color': ('毛收益(%)', '净收益(%)', '期间最大浮盈(%)',
                                '期间最大浮亏(%)', 'T+1开盘口径(%)')}),
        ('参数敏感性', sens, {'cap': 22,
                        'color': ('年化收益(%)', '最大回撤(%)', '夏普',
                                  '日胜率含空仓(%)', '单笔平均(%)', '单笔胜率(%)')}),
        ('因子分层', lay, {'cap': 22,
                       'color': ('信号级20日平均(%)', '交易级20日平均(%)')}),
    ]

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = args.out or os.path.join(
        S.OUTPUT_DIR, f'three_factor_best_backtest_{ts}.xlsx')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    X.export_excel(sheets, out)
    print(f'\n✅ Excel 已保存: {out}')

    if args.chart or args.png:
        png = args.png or os.path.join(
            S.CHART_DIR, '三因子最优组合回测.png')
        CH.plot_backtest(panel, res, meta, nav_base, trades, horizons, cost, png)
        print(f'✅ 净值图已保存: {png}')

    base_out = os.path.splitext(out)[0]
    navc.to_csv(base_out + '_nav.csv', index=False, encoding='utf-8-sig')
    tr.to_csv(base_out + '_trades.csv', index=False, encoding='utf-8-sig')
    print(f'✅ CSV 备份: {base_out}_nav.csv / _trades.csv')
    return 0


if __name__ == '__main__':
    sys.exit(main())

