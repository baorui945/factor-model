# -*- coding: utf-8 -*-
"""
==============================================================================
三因子买点信号 —— 全历史重建（面向当前数据域表）
==============================================================================

背景
----
`data/sig_all_horizons.pkl`（24,054 条）原本只覆盖 2022-01-04~2026-08-06，
因为它由主工程 `F:\\quantTrade` 用 `history_days=1500` 的一次滚动回测产出。
新表 `backward_tdx_daily` 已覆盖 2015-09-01~2026-10-09（11.1 年），
本脚本用**完全相同的因子口径**在更长历史上重扫信号。

口径（与主工程 `analyzers/three_factor_backtest.py` 逐字一致）
------------------------------------------------------------
* 因子判定：默认复用**本地** `backtest_model.factors` 的三因子闸门模型
  （F1 趋势强弱 / F2 趋势方向 / F3 多空力量，指标 MA7 / MA21 /
  MACD(30,89,9)，参数见 `config/signal.json`）；加 `--legacy` 则改用主工程
  `analyzers` 分析器（用于严格对拍 / 回退）。两者判定结果逐位一致。
* **扫描窗口恒为 360 根**：对第 i 个交易日，取 `df[i-359 : i+1]` 送
  `analyze_pattern()`。因此**信号只取决于该 360 根窗口内的数据**，
  与 `history_days` 无关 —— 扩大 `history_days` 只延长可扫描的日期区间，
  不会改变重叠区间内的既有信号（可做严格对拍校验）。
* 前瞻收益：`return_Nd = close(i+N)/close(i) - 1`，N ∈ {20,30,40,60}。
* 股票池：新表最新的 `stock_code/stock_name`，剔除 ST / 退市等异常股。

用法
----
    # 全市场重建（默认读 .env 的 TABLE_BACKWARD_DAILY）
    python rebuild_signals.py

    # 只看 5 只（连通性 / 口径冒烟）
    python rebuild_signals.py --limit 5

    # 与既有信号池对拍（重叠区间应完全一致）
    python rebuild_signals.py --limit 80 --check-parity data/sig_all_horizons.pkl

    # 指定表 / 输出
    python rebuild_signals.py --table backward_daily --out output\\sig_old.csv
"""

import argparse
import importlib.util
import multiprocessing as mp
import os
import pickle
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
QUANT = r'F:\quantTrade'

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, 'reconfigure'):
        _s.reconfigure(encoding='utf-8', errors='replace')


def _abm_config():
    """以独立名加载本工程 config.py，避免与主工程同名模块冲突。"""
    spec = importlib.util.spec_from_file_location(
        'abm_config', os.path.join(ROOT, 'config.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ABM = _abm_config()
sys.path.insert(0, ROOT)
sys.path.insert(0, QUANT)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog='rebuild_signals',
        description='三因子买点信号全历史重建（滚动 360 根窗口）')
    ap.add_argument('--table', default=_ABM.TABLE_BACKWARD_DAILY,
                    help=f'日线后复权表名，默认 {_ABM.TABLE_BACKWARD_DAILY}（本工程 .env）')
    ap.add_argument('--history-days', type=int, default=3000,
                    help='每只股票加载的历史K线上限，默认 3000（覆盖全表）')
    ap.add_argument('--scan-window', type=int, default=360,
                    help='滚动扫描窗口长度，默认 360（与主工程一致，勿改）')
    ap.add_argument('--start', default='2015-09-01',
                    help='只保留该日（含）之后的信号，默认 2015-09-01')
    ap.add_argument('--limit', type=int, default=None, help='只扫前 N 只（冒烟用）')
    ap.add_argument('--workers', type=int, default=0, help='进程数，0=CPU 核数')
    ap.add_argument('--out', default=None, help='输出 CSV 路径')
    ap.add_argument('--ckpt', default=None,
                    help='断点目录，默认 output/_sig_ckpt（每批次结果独立落盘，可续跑）')
    ap.add_argument('--batch', type=int, default=8, help='每批股票数，默认 8')
    ap.add_argument('--no-resume', action='store_true', help='忽略断点，从头重跑')
    ap.add_argument('--check-parity', default=None,
                    help='既有信号池 pkl，做重叠区间对拍')
    ap.add_argument('--legacy', action='store_true',
                    help='改用主工程 analyzers 分析器（默认用本地 factors 三因子'
                         '闸门模型；--legacy 用于严格对拍 / 回退）')
    return ap


# ── 多进程工作件（必须模块级，spawn 才能 pickle）─────────────────────────
_WORKER = None
_FWD = (20, 30, 40, 60)


def _init_worker(table: str, history_days: int, scan_window: int,
                 legacy: bool = False) -> None:
    global _WORKER
    if table:
        os.environ['TABLE_BACKWARD_DAILY'] = table     # 子进程内先于 config 导入
    import config
    if legacy:
        from analyzers.three_factor_backtest import ThreeFactorBacktester
        a = ThreeFactorBacktester(config=config.get_db_config(), max_workers=1,
                                  history_days=history_days,
                                  scan_window=scan_window)
        a.forward_periods = list(_FWD)                 # 含 60 日前瞻
        a.connect()
        _WORKER = {'engine': 'legacy', 'analyzer': a,
                   'history_days': history_days, 'scan_window': scan_window}
    else:
        from backtest_model.factors import MarketDB, ThreeFactorModel
        db = MarketDB(table=table)
        db.connect()
        _WORKER = {'engine': 'native', 'db': db, 'model': ThreeFactorModel(),
                   'history_days': history_days, 'scan_window': scan_window}


def _run_batch(infos):
    out = []
    if _WORKER is None:
        return out
    for info in infos:
        try:
            if _WORKER['engine'] == 'legacy':
                out.extend(_WORKER['analyzer'].backtest_stock(
                    info['stock_code'], info.get('stock_name', '')))
            else:
                from backtest_model.factors import scan_stock
                df = _WORKER['db'].get_stock_data(
                    info['stock_code'], limit_days=_WORKER['history_days'])
                if df.empty:
                    continue
                out.extend(scan_stock(
                    _WORKER['model'], df, stock_code=info['stock_code'],
                    stock_name=info.get('stock_name', ''),
                    scan_window=_WORKER['scan_window'],
                    forward_periods=list(_FWD)))
        except Exception:                              # noqa: BLE001
            continue
    return out


def _run_batch_tagged(payload):
    """带批次号的批处理包装（用于断点续跑：每批结果独立落盘）。"""
    idx, infos = payload
    try:
        return idx, _run_batch(infos)
    except Exception:                                  # noqa: BLE001
        return idx, []


def stock_universe(table, history_days, scan_window, legacy=False):
    """取股票池（过滤 ST / 退市）。

    native：用自包含 `factors.MarketDB`；legacy：用主工程分析器（对拍 / 回退）。
    """
    if table:
        os.environ['TABLE_BACKWARD_DAILY'] = table
    import config
    if legacy:
        from analyzers.three_factor_backtest import ThreeFactorBacktester
        a = ThreeFactorBacktester(config=config.get_db_config(), max_workers=1,
                                  history_days=history_days,
                                  scan_window=scan_window)
        assert a.connect(), '数据库连接失败'
        try:
            print(f'[表] 实际使用: {a.table_name}')
            return a.get_all_stock_codes()
        finally:
            a.disconnect()
    from backtest_model.factors import MarketDB
    db = MarketDB(table=table)
    assert db.connect(), '数据库连接失败'
    try:
        print(f'[表] 实际使用: {db.table_name}')
        return db.get_all_stock_codes()
    finally:
        db.disconnect()


def _load_ckpt(batches, ckpt):
    """汇总断点目录中的批次结果；缺失批次按空处理并告警。"""
    sigs, missing = [], []
    for i in range(len(batches)):
        p = os.path.join(ckpt, f'b{i:04d}.pkl')
        if not os.path.exists(p):
            missing.append(i)
            continue
        with open(p, 'rb') as f:
            sigs.extend(pickle.load(f))
    if missing:
        print(f'⚠ 缺失 {len(missing)} 批（按无信号处理）：{missing[:10]}')
    return sigs


def _to_frame(signals) -> pd.DataFrame:
    rows = [{
        'stock_code': str(s['stock_code']).zfill(6),
        'stock_name': s['stock_name'],
        'signal_date': s['signal_date'],
        'signal_close': s['signal_close'],
        **{f'return_{p}d': s['returns'].get(p) for p in (20, 30, 40, 60)},
    } for s in signals]
    d = pd.DataFrame(rows)
    if len(d):
        d = d.sort_values(['stock_code', 'signal_date']).reset_index(drop=True)
    return d


def parity_check(new: pd.DataFrame, path: str):
    """与既有信号池做重叠区间对拍：仅按 (股票, 日期) 两个键比较。"""
    old = pd.read_pickle(path)[['stock_code', 'signal_date']].copy()
    old['stock_code'] = old['stock_code'].astype(str).str.zfill(6)
    old['signal_date'] = old['signal_date'].astype(str)

    nn = new[['stock_code', 'signal_date']].copy()
    nn['signal_date'] = nn['signal_date'].astype(str)

    keo = set(map(tuple, old.to_numpy()))
    ken = set(map(tuple, nn.to_numpy()))
    span = nn[(nn['stock_code'].isin(set(old['stock_code']))) &
              (nn['signal_date'] >= old['signal_date'].min()) &
              (nn['signal_date'] <= old['signal_date'].max())]
    kes = set(map(tuple, span.to_numpy()))

    res = {'old_n': len(old), 'new_n': len(nn),
           'old_codes': old['stock_code'].nunique(),
           'new_codes': nn['stock_code'].nunique(),
           '重叠区间内 新信号数': len(kes),
           '旧有但新无': len(keo - ken),
           '重叠区间内 新多出': len(kes - keo)}
    return res, sorted(keo - ken)[:10], sorted(kes - keo)[:10]


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    workers = args.workers or (os.cpu_count() or 4)
    out_dir = os.path.join(ROOT, 'output')
    os.makedirs(out_dir, exist_ok=True)

    print('=' * 78)
    print('  三因子买点信号 —— 全历史重建')
    print('=' * 78)
    print(f'  数据表       : {args.table}')
    print(f'  历史K线上限  : {args.history_days}    扫描窗口: {args.scan_window}')
    print(f'  启动日期过滤 : >= {args.start}    进程数: {workers}')
    print(f'  判定引擎     : {"主工程 analyzers (--legacy)" if args.legacy else "本地 factors 三因子闸门模型"}')
    print('=' * 78)

    t0 = time.perf_counter()
    infos = stock_universe(args.table, args.history_days, args.scan_window,
                           args.legacy)
    if args.limit:
        infos = infos[:args.limit]

    bs = max(1, args.batch)
    batches = [infos[i:i + bs] for i in range(0, len(infos), bs)]
    ckpt = args.ckpt or os.path.join(out_dir, '_sig_ckpt')
    os.makedirs(ckpt, exist_ok=True)
    todo = list(range(len(batches)))
    if not args.no_resume:
        have = [i for i in todo
                if os.path.exists(os.path.join(ckpt, f'b{i:04d}.pkl'))]
        if have:
            todo = [i for i in todo if i not in set(have)]
            print(f'[断点] 已完成 {len(have)}/{len(batches)} 批，续跑剩余 {len(todo)} 批')

    n_batch = max(len(todo), 1)
    done_stocks = (len(batches) - len(todo)) * bs
    done, nb = done_stocks, 0
    t_loop = time.perf_counter()
    if todo:
        ctx = mp.get_context('spawn')
        with ctx.Pool(processes=workers, initializer=_init_worker,
                      initargs=(args.table, args.history_days,
                                args.scan_window, args.legacy)) as pool:
            tag = ((i, batches[i]) for i in todo)
            for idx, res in pool.imap_unordered(_run_batch_tagged, tag, chunksize=1):
                with open(os.path.join(ckpt, f'b{idx:04d}.pkl'), 'wb') as f:
                    pickle.dump(res, f, protocol=4)
                done += len(batches[idx])
                nb += 1
                if nb % 25 == 0 or nb >= n_batch:
                    el = time.perf_counter() - t_loop
                    print(f'  [{min(done, len(infos)):>4}/{len(infos)}] '
                          f'批次 {nb}/{n_batch}  已用 {el / 60:.1f} 分钟  '
                          f'预计剩余 '
                          f'{el / max(done - done_stocks, 1) * (len(infos) - done) / 60:.1f} 分钟',
                          flush=True)
    else:
        print('[断点] 全部批次已完成，直接汇总')

    d = _to_frame(_load_ckpt(batches, ckpt))
    if len(d):
        d = d[d['signal_date'] >= args.start].reset_index(drop=True)

    el = time.perf_counter() - t0
    print(f'\n[结果] 信号 {len(d):,} 条 / '
          f'{d["stock_code"].nunique() if len(d) else 0} 只  用时 {el / 60:.1f} 分钟')
    if len(d):
        print(f'       日期 {d["signal_date"].min()} ~ {d["signal_date"].max()}')
        print('       按年 ' + str(d['signal_date'].str[:4]
                                    .value_counts().sort_index().to_dict()))

    out = args.out or os.path.join(
        out_dir, f'signals_rebuilt_{time.strftime("%Y%m%d_%H%M%S")}.csv')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    d.to_csv(out, index=False, encoding='utf-8-sig')
    print(f'✅ 已保存: {out}')

    if args.check_parity:
        res, miss, extra = parity_check(d, args.check_parity)
        print('\n' + '-' * 78)
        print('【对拍】与既有信号池比较')
        for k, v in res.items():
            print(f'   {k:22s} {v:,}' if isinstance(v, int) else f'   {k:22s} {v}')
        if miss:
            print('   旧有但新无样例:', miss)
        if extra:
            print('   新多出样例    :', extra)
    return 0


if __name__ == '__main__':
    sys.exit(main())
