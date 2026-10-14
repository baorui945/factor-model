# -*- coding: utf-8 -*-
"""
==============================================================================
数据导入统一入口 —— 日线 / 月线
==============================================================================

把 `--freq` 从命令行里摘出来，其余参数原样透传给对应导入器，
因此 `--freq` 可以写在任意位置。

用法::

    python run_import.py --freq daily   --start 2021-06-01 --end 2026-10-09
    python run_import.py --freq monthly --start 2015-01-01
    python run_import.py --freq all     --start 2021-06-01     # 先日线再月线
    python run_import.py --freq daily   --limit 5 --dry-run    # 连通性自检
    python run_import.py --freq daily   --source file --dir "F:\\stock_dat\\day"
    python run_import.py --freq daily   -h                     # 查看日线参数
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from importers import daily, monthly                     # noqa: E402

_USAGE = """\
ai_backtest_model · 数据导入（仅支持 日线 / 月线）

    python run_import.py --freq daily   [日线参数...]   -> backward_daily
    python run_import.py --freq monthly [月线参数...]   -> backward_monthly
    python run_import.py --freq all     [参数...]       -> 先日线，再月线

    python run_import.py --freq daily -h                # 查看日线全部参数
    python run_import.py --freq monthly -h              # 查看月线全部参数

常用示例：
    python run_import.py --freq daily --start 2021-06-01 --limit 5 --dry-run
    python run_import.py --freq daily --codes 600354,000001,300750
    python run_import.py --freq daily --universe db --start 2026-01-01
    python run_import.py --freq monthly --start 2015-01-01
"""


def split_freq(argv):
    """从参数列表中摘出 `--freq`，返回 (freq, 剩余参数)。"""
    argv = list(argv)
    freq = 'daily'
    out, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == '--freq':
            if i + 1 >= len(argv):
                raise SystemExit('--freq 缺少取值（daily / monthly / all）')
            freq = argv[i + 1]
            i += 2
            continue
        if a.startswith('--freq='):
            freq = a.split('=', 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return freq, out


def main(argv=None) -> int:
    """统一导入入口。"""
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or '-?' in argv:
        print(_USAGE)
        return 0

    freq, rest = split_freq(argv)
    if freq not in ('daily', 'monthly', 'all'):
        print(f'未知 --freq: {freq}')
        print(_USAGE)
        return 2

    if freq == 'all':
        rc = daily.main(rest)
        if rc:
            return rc
        return monthly.main(rest)
    return daily.main(rest) if freq == 'daily' else monthly.main(rest)


if __name__ == '__main__':
    sys.exit(main())
