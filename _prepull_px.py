# -*- coding: utf-8 -*-
"""预热第 4 阶段价格缓存：从 TABLE_BACKWARD_DAILY 拉全表代码的后复权价。

独立小脚本，便于与信号重建并行执行；`build_panel` 之后可直接命中缓存
（缓存命中条件是「请求代码 ⊆ 已缓存代码」）。
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

from enrich_signals import universe_codes                     # noqa: E402
from backtest_model import data as D                          # noqa: E402
from backtest_model import settings as S                      # noqa: E402


def main() -> int:
    codes = universe_codes()
    print(f'[预热] 全表股票池 {len(codes):,} 只，起始日 {S.DEF_START}', flush=True)
    px = D.fetch_prices(codes, start=S.DEF_START, refresh=True)
    print(f'✅ 价格缓存就绪: {len(px):,} 行 / {px["stock_code"].nunique()} 只  '
          f'{px["trade_date"].min().date()} ~ {px["trade_date"].max().date()}',
          flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
