# -*- coding: utf-8 -*-
"""
==============================================================================
回测主入口
==============================================================================

    python run_backtest.py                                  # 默认：20/30/40/60 持有期
    python run_backtest.py --horizons 20 --no-cost
    python run_backtest.py --chart                          # 另存 6 面板净值图
    python run_backtest.py --refresh --out D:\\out.xlsx

详细参数见：python run_backtest.py -h
（回测逻辑位于 `backtest_model/` 包，本文件仅做路径准备与转发。）
"""

import os
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backtest_model.run import main                       # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
