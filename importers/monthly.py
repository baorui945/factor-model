# -*- coding: utf-8 -*-
"""
==============================================================================
月线导入器  ——  MySQL 表 `backward_monthly`（后复权月线）
==============================================================================

月线与日线共用同一套导入引擎（`importers/base.py`），差别只在：

* 目标表     : `backward_monthly`
* baostock 频率 : `m`
* 默认起始日  : `2015-01-01`（月线历史可回溯更久）

用法::

    # 网络源（默认）：全市场月线
    python run_import.py --freq monthly --start 2015-01-01

    # 只导 5 只做连通性测试（不写库）
    python run_import.py --freq monthly --limit 5 --dry-run

    # 指定代码
    python run_import.py --freq monthly --codes 600354,000001

    # 本地文件源
    python run_import.py --freq monthly --source file --dir F:\\stock_dat\\month --pattern "*.txt"

注意：`backward_monthly` 表另有 `macd_value` / `macd_tag` 两列，由 MACD 分析
工具回写；本导入器不触碰这两列（upsert 只更新行情字段）。
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from . import base
    from . import common as C
except ImportError:                                   # 直接以脚本方式运行
    from importers import base                        # type: ignore
    from importers import common as C                 # type: ignore

import config                                         # noqa: E402

FREQ = 'monthly'
#: 默认起始日期（可由 .env 的 IMPORT_MONTHLY_START 覆盖）
DEF_START = os.environ.get('IMPORT_MONTHLY_START', '2015-01-01')
#: 默认复权口径 1=后复权
DEF_ADJUST = os.environ.get('IMPORT_ADJUST_FLAG', '1')


def build_parser() -> argparse.ArgumentParser:
    """构建月线导入命令行参数。"""
    ap = argparse.ArgumentParser(
        prog='import-monthly',
        description=f'月线导入 -> {config.TABLE_BACKWARD_MONTHLY}（后复权）')
    ap.add_argument('--source', choices=['baostock', 'file'], default='baostock',
                    help='数据源，默认 baostock')
    ap.add_argument('--start', default=DEF_START, help=f'起始日，默认 {DEF_START}')
    ap.add_argument('--end', default=None, help='结束日，默认今天')
    ap.add_argument('--codes', default=None, help='逗号分隔的 6 位代码列表')
    ap.add_argument('--code-file', default=None, help='代码清单文件（每行一个）')
    ap.add_argument('--universe', choices=['all', 'db'], default='all',
                    help='股票池：all=全市场 / db=表内已有（增量补齐）')
    ap.add_argument('--limit', type=int, default=None, help='只处理前 N 只')
    ap.add_argument('--adjustflag', default=DEF_ADJUST,
                    help='复权口径 1=hfq(默认) 2=qfq 3=raw')
    ap.add_argument('--dir', default=None, help='本地文件目录（--source file）')
    ap.add_argument('--pattern', default='*.txt', help='本地文件匹配模式')
    ap.add_argument('--truncate', action='store_true', help='导入前清空表（危险）')
    ap.add_argument('--sleep', type=float, default=0.0, help='每只间隔秒数')
    ap.add_argument('--dry-run', action='store_true', help='只抓取/解析，不写库')
    ap.add_argument('-v', '--verbose', action='store_true', help='输出调试日志')
    return ap


def main(argv=None) -> int:
    """月线导入入口。"""
    args = build_parser().parse_args(argv)
    import logging
    C.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    C._LOG.info('月线导入  %s', config.describe())

    if args.source == 'file':
        if not args.dir:
            C._LOG.error('--source file 必须指定 --dir')
            return 2
        base.import_files(FREQ, args.dir, pattern=args.pattern,
                          truncate=args.truncate, dry_run=args.dry_run)
        return 0

    codes = None
    if args.codes:
        codes = [x.strip() for x in args.codes.split(',') if x.strip()]
    if args.code_file:
        codes = C.read_code_file(args.code_file)

    base.import_baostock(
        FREQ, codes=codes, start=args.start, end=args.end,
        adjustflag=args.adjustflag, limit=args.limit,
        universe=args.universe, sleep=args.sleep, dry_run=args.dry_run)
    return 0


if __name__ == '__main__':
    sys.exit(main())
