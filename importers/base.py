# -*- coding: utf-8 -*-
"""
==============================================================================
通用导入流程（日线 / 月线共用）
==============================================================================

提供两条导入通道，均可由 `daily.py` / `monthly.py` 直接调用：

1. `import_baostock()` —— 从 baostock 网络源按代码逐只抓取（后复权 hfq），
   幂等写入 MySQL；支持 `limit` / `dry_run` / 股票池选择。
2. `import_files()`     —— 从本地行情文本（TDX 导出格式）批量导入。

两条通道都遵循：**建表 -> 抓取 -> 批量 upsert -> 输出统计**。
"""

import os
import time
from datetime import datetime
from typing import Dict, Optional, Sequence

from . import common as C


def _stat() -> Dict[str, int]:
    return {'codes': 0, 'ok': 0, 'empty': 0, 'fail': 0, 'rows': 0}


def _print_stat(freq: str, st: Dict[str, int], table: str, t0: float,
                dry_run: bool = False) -> None:
    el = time.time() - t0
    verb = '解析' if dry_run else '写入'
    C._LOG.info('─' * 68)
    C._LOG.info('[%s] 导入完成  代码 %d 只（成功 %d / 空 %d / 失败 %d）',
                freq, st['codes'], st['ok'], st['empty'], st['fail'])
    C._LOG.info('[%s] %s %s 行 -> 表 %s  耗时 %.1fs%s',
                freq, verb, f"{st['rows']:,}", table, el,
                '  [dry-run 未写库]' if dry_run else '')


# ═════════════════════════════════════════════════════════════════════════
# 通道 1：baostock 网络源
# ═════════════════════════════════════════════════════════════════════════

def import_baostock(freq: str,
                    codes: Optional[Sequence[str]] = None,
                    start: Optional[str] = None,
                    end: Optional[str] = None,
                    adjustflag: str = '1',
                    limit: Optional[int] = None,
                    universe: str = 'all',
                    sleep: float = 0.0,
                    dry_run: bool = False) -> Dict[str, int]:
    """从 baostock 抓取并写入 MySQL。

    Args:
        freq: 'daily' | 'monthly'
        codes: 指定代码列表；为 None 时按 `universe` 取股票池
        start / end: 'YYYY-MM-DD'；end 默认今天
        adjustflag: '1'=后复权(hfq) '2'=前复权 '3'=不复权
        limit: 只处理前 N 只（连通性测试用）
        universe: 'all'=baostock 全市场 / 'db'=仅表内已有股票（增量补齐）
        sleep: 每只之间的额外休眠秒数
        dry_run: 只抓取不写库

    Returns:
        统计字典 {'codes','ok','empty','fail','rows'}
    """
    table, _, _ = C.FREQ_SPEC[freq]
    end = end or datetime.now().strftime('%Y-%m-%d')
    st = _stat()
    t0 = time.time()

    conn = C.get_connection()
    try:
        C.ensure_table(conn, freq)
        n0, lo0, hi0 = C.table_stats(conn, table)
        C._LOG.info('目标表 %s 现有 %s 行（%s ~ %s）', table, f'{n0:,}', lo0, hi0)

        bs = C.bs_login()
        try:
            if codes:
                code_list = [C.from_bs_code(c) if '.' in str(c)
                             else str(c).strip().zfill(6) for c in codes]
                name_map = {}
            else:
                pool = (C.list_bs_universe(bs) if universe == 'all'
                        else C.list_db_universe(conn, table))
                name_map = dict(pool)
                code_list = [c for c, _ in pool]
            if limit:
                code_list = code_list[:limit]
            st['codes'] = len(code_list)

            C._LOG.info('开始导入 freq=%s  %s ~ %s  adjustflag=%s  共 %d 只%s',
                        freq, start, end, adjustflag, len(code_list),
                        '（dry-run 不写库）' if dry_run else '')
            pbar = C.tqdm(code_list, unit='只',
                          desc=f'{freq} 导入', disable=not code_list)
            for code in pbar:
                name = name_map.get(code, '')
                try:
                    rows = C.fetch_bs_bars(bs, code, freq, start, end,
                                           adjustflag, name)
                except Exception as e:
                    st['fail'] += 1
                    C._LOG.warning('  %s 抓取失败: %s', code, e)
                    continue
                if not rows:
                    st['empty'] += 1
                else:
                    st['ok'] += 1
                    if dry_run:
                        st['rows'] += len(rows)          # dry-run：只统计解析行数
                    else:
                        st['rows'] += C.upsert_bars(conn, table, rows)
                if hasattr(pbar, 'set_postfix'):
                    pbar.set_postfix(ok=st['ok'], rows=f"{st['rows']:,}")
                if sleep:
                    time.sleep(sleep)
        finally:
            C.bs_logout(bs)
    finally:
        conn.close()

    if not dry_run:
        conn = C.get_connection()
        try:
            n1, lo1, hi1 = C.table_stats(conn, table)
        finally:
            conn.close()
        C._LOG.info('表 %s 现有 %s 行（%s ~ %s）', table, f'{n1:,}', lo1, hi1)
    _print_stat(freq, st, table, t0, dry_run)
    return st


# ═════════════════════════════════════════════════════════════════════════
# 通道 2：本地文件（TDX 导出格式）
# ═════════════════════════════════════════════════════════════════════════

def import_files(freq: str,
                 directory: str,
                 pattern: str = '*.txt',
                 truncate: bool = False,
                 dry_run: bool = False,
                 start: Optional[str] = None,
                 end: Optional[str] = None) -> Dict[str, int]:
    """从本地行情文本批量导入。

    Args:
        freq: 'daily' | 'monthly'
        directory: 行情文件所在目录
        pattern: 文件匹配模式，默认 '*.txt'
        truncate: 导入前清空目标表（全量重建；默认关闭）
        dry_run: 只解析不写库
        start / end: 可选的日期闭区间过滤（'YYYY-MM-DD'）；None 表示全量导入

    Returns:
        统计字典 {'codes','ok','empty','fail','rows'}
    """
    table, _, _ = C.FREQ_SPEC[freq]
    st = _stat()
    t0 = time.time()

    files = C.iter_bars_files(directory, pattern)
    if not files:
        raise FileNotFoundError(f'目录下没有匹配文件: {directory}\\{pattern}')
    st['codes'] = len(files)

    conn = C.get_connection()
    try:
        C.ensure_table(conn, freq)
        if truncate and not dry_run:
            with conn.cursor() as cur:
                cur.execute(f'TRUNCATE TABLE {table}')
            conn.commit()
            C._LOG.warning('已清空表 %s', table)

        C._LOG.info('解析目录 %s（%d 个文件, 模式 %s）%s', directory, len(files),
                    pattern, '（dry-run 不写库）' if dry_run else '')
        pbar = C.tqdm(files, unit='文件', desc=f'{freq} 文件导入')
        for path in pbar:
            try:
                _code, _name, rows = C.parse_bars_file(path, freq,
                                                       start=start, end=end)
            except Exception as e:
                st['fail'] += 1
                C._LOG.warning('  %s 解析失败: %s', os.path.basename(path), e)
                continue
            if not rows:
                st['empty'] += 1
                continue
            st['ok'] += 1
            if dry_run:
                st['rows'] += len(rows)                  # dry-run：只统计解析行数
            else:
                st['rows'] += C.upsert_bars(conn, table, rows)
            if hasattr(pbar, 'set_postfix'):
                pbar.set_postfix(ok=st['ok'], rows=f"{st['rows']:,}")
    finally:
        conn.close()

    _print_stat(freq, st, table, t0, dry_run)
    return st

