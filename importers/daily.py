# -*- coding: utf-8 -*-
"""
==============================================================================
日线导入器  ——  MySQL 日线后复权表（表名取自 config.TABLE_BACKWARD_DAILY）
==============================================================================

支持两种数据源：

1. **baostock 网络源**（默认）—— 按代码逐只抓取后复权(hfq)日线，幂等写入。
2. **本地文件源** —— 导入 TDX 导出的行情文本（文件名含 6 位代码，
   内容为空白分隔的 `日期 开 高 低 收 量 额`）。

用法::

    # 网络源（默认）：全市场、指定区间
    python run_import.py --freq daily --start 2021-06-01 --end 2026-10-09

    # 只导 5 只做连通性测试（不写库）
    python run_import.py --freq daily --limit 5 --dry-run

    # 指定代码
    python run_import.py --freq daily --codes 600354,000001,300750

    # 仅补表内已有股票的缺口
    python run_import.py --freq daily --universe db --start 2026-01-01

    # 本地文件源（TDX 导出），可用 --file-start 限定起始日
    python run_import.py --freq daily --source file --dir F:\new_tdx\T0002\export_filled --file-start 2015-09-01
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

FREQ = 'daily'
#: 默认起始日期（可由 .env 的 IMPORT_DAILY_START 覆盖）
DEF_START = os.environ.get('IMPORT_DAILY_START', '2021-06-01')
#: 默认复权口径 1=后复权
DEF_ADJUST = os.environ.get('IMPORT_ADJUST_FLAG', '1')


def build_parser() -> argparse.ArgumentParser:
    """构建日线导入命令行参数。"""
    ap = argparse.ArgumentParser(
        prog='import-daily',
        description=f'日线导入 -> {config.TABLE_BACKWARD_DAILY}（后复权）')
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
    ap.add_argument('--file-start', default=None,
                    help='本地文件源的起始日过滤（含），如 2015-09-01；默认不过滤')
    ap.add_argument('--file-end', default=None,
                    help='本地文件源的结束日过滤（含）；默认不过滤')
    ap.add_argument('--truncate', action='store_true', help='导入前清空表（危险）')
    ap.add_argument('--sleep', type=float, default=0.0, help='每只间隔秒数')
    ap.add_argument('--dry-run', action='store_true', help='只抓取/解析，不写库')
    ap.add_argument('-v', '--verbose', action='store_true', help='输出调试日志')
    return ap


def main(argv=None) -> int:
    """日线导入入口。"""
    args = build_parser().parse_args(argv)
    import logging
    C.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    C._LOG.info('日线导入  %s', config.describe())

    if args.source == 'file':
        if not args.dir:
            C._LOG.error('--source file 必须指定 --dir')
            return 2
        base.import_files(FREQ, args.dir, pattern=args.pattern,
                          truncate=args.truncate, dry_run=args.dry_run,
                          start=args.file_start, end=args.file_end)
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
