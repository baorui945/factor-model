# -*- coding: utf-8 -*-
"""
==============================================================================
_run_wait.py —— 后台起命令 + 阻塞等待 + 回吐尾部日志（一次调用拿到结果）
==============================================================================

背景
----
重建 / 富化 / 回测这类长任务，如果靠「反复读同一个日志文件」来看进度，
容易变成重复轮询而卡死流程。本脚本把「等待」收敛到一次调用里：

    1) 以分离进程（DETACHED_PROCESS）启动目标命令，
       stdout/stderr 合并写入 --log（UTF-8，避免 PowerShell 重定向写 UTF-16 乱码）；
    2) 主进程每 --interval 秒打印一次心跳（已用时 / 子进程是否存活）；
    3) 子进程结束、命中 --done-regex 或超时后，打印退出码与日志末尾 --tail 行。

即使外层 shell 被中断，分离出去的子进程仍会继续跑；
之后用 `--attach` 只查看日志尾部即可（不会重启任务）。

用法
----
    # 启动并阻塞等待（结束即打印摘要）
    python _run_wait.py --log output/_enrich.log --timeout 5400 -- \
        python -u enrich_signals.py --signals output/signals_rebuilt_full.csv

    # 只查看某个任务的日志尾部（不启动新进程）
    python _run_wait.py --log output/signals_rebuilt_full.csv --attach
"""

import argparse
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def read_tail(path: str, n: int):
    """读取文本文件末尾 n 行（容忍编码问题）。"""
    if not os.path.isfile(path):
        return []
    with open(path, 'rb') as f:
        data = f.read()
    text = data.decode('utf-8', errors='replace')
    lines = [ln.rstrip('\r') for ln in text.splitlines()]
    return lines[-n:]


def print_tail(path: str, n: int):
    """打印日志尾部。"""
    lines = read_tail(path, n)
    print(f'\n----- 日志尾部 {os.path.relpath(path, ROOT)}（{len(lines)} 行）-----')
    for ln in lines:
        print(ln)
    print('----- 尾部结束 -----')


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog='_run_wait',
        description='后台起命令并阻塞等待，结束时回吐日志尾部')
    ap.add_argument('--log', required=True, help='日志文件（UTF-8）')
    ap.add_argument('--timeout', type=float, default=3600.0,
                    help='最长等待秒数，默认 3600')
    ap.add_argument('--interval', type=float, default=15.0,
                    help='心跳间隔秒数，默认 15')
    ap.add_argument('--tail', type=int, default=60, help='结束时回吐的行数，默认 60')
    ap.add_argument('--done-regex', default=None,
                    help='日志命中该正则即认为完成（提前结束等待）')
    ap.add_argument('--attach', action='store_true',
                    help='只查看日志尾部，不启动任何进程')
    ap.add_argument('cmd', nargs=argparse.REMAINDER,
                    help='-- 之后的待执行命令')
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.attach:
        print_tail(args.log, args.tail)
        return 0

    cmd = [c for c in args.cmd if c != '--']
    if not cmd:
        print('缺少待执行命令，示例：python _run_wait.py --log x.log -- python -u a.py')
        return 2

    log_path = os.path.abspath(args.log)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'

    flags = 0
    if os.name == 'nt':
        flags = (subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP)

    print('=' * 78)
    print('  后台启动: ' + ' '.join(cmd))
    print(f'  日志    : {log_path}')
    print(f'  超时    : {args.timeout / 60:.0f} 分钟')
    print('=' * 78)

    with open(log_path, 'wb') as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                                cwd=ROOT, env=env, creationflags=flags)
    print(f'  子进程 PID: {proc.pid}')

    pat = re.compile(args.done_regex) if args.done_regex else None
    t0 = time.perf_counter()
    done_hit = False
    while True:
        rc = proc.poll()
        el = time.perf_counter() - t0
        if rc is not None:
            break
        if pat is not None:
            hit = [ln for ln in read_tail(log_path, 40) if pat.search(ln)]
            if hit:
                done_hit = True
                break
        if el >= args.timeout:
            print(f'\n[超时] 已等待 {el / 60:.1f} 分钟，子进程仍在运行（PID '
                  f'{proc.pid}），本次不再等待')
            print_tail(log_path, args.tail)
            return 3
        print(f'  [watch] 运行中 已用 {el / 60:.1f} 分钟 ...', flush=True)
        time.sleep(args.interval)

    el = time.perf_counter() - t0
    if done_hit and proc.poll() is None:
        print(f'\n[完成标记命中] 用时 {el / 60:.1f} 分钟（子进程可能仍在收尾）')
    else:
        print(f'\n[结束] 退出码 {proc.returncode}  用时 {el / 60:.1f} 分钟')
    print_tail(log_path, args.tail)
    return 0 if (proc.returncode in (0, None)) else 1


if __name__ == '__main__':
    sys.exit(main())
