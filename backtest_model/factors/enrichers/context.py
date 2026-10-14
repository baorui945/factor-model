# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.context —— 富化上下文（数据来源统一封装）
==============================================================================

`EnrichContext` 把富化所需的全部外部数据聚合成一个对象，屏蔽「来自 DB 还是
来自网络」的差异：

    ctx.spot      {code: {name, per, pb, mktcap(万元), nmc(万元), price, ...}}
    ctx.ind_map   {code: 行业名}
    ctx.klines    {code: (dates(int64), closes(float32),
                          vol60(float64 或 None), mom60(float64 或 None))}
    ctx.idx_kl    (dates, closes) 沪深300，或 None

数据优先级
----------
1. ``FactorStore``（`factor_spot` / `factor_qfq_daily`，每周由
   `run_update_factors.py` 刷新）—— **首选，零网络**；
2. 网络抓取（`network.py`）—— 库表为空或缺票时自动回退，可落盘断点续抓；
3. 指数：默认沿用既有本地资产 `data/idx_000300.pkl`（与旧口径逐位一致），
   缺失时才用库表 / 网络。
"""

import os
import pickle

import numpy as np

from ... import settings as S
from . import network
from .store import FactorStore


class EnrichContext:
    """富化上下文（只读数据容器）。"""

    def __init__(self, spot, ind_map, klines, idx_kl, source='store'):
        self.spot = spot
        self.ind_map = ind_map
        self.klines = klines
        self.idx_kl = idx_kl
        self.source = source
        self.sig_count = {}          # 由 pipeline 注入：{code: 信号次数}
        self.use_stored_metrics = False
        self._derived = {}           # per-code 派生量缓存

    def kline(self, code):
        """取单只股票的前复权序列（4 元组）或 None。"""
        return self.klines.get(code)

    def derived(self, code, day_ints):
        """一次算好该股票在给定信号日的派生量（逐位复刻原脚本内联公式）。

        Returns:
            ``(p_sig, ratio, vol60, mom60)`` —— 均为 float64 数组；
            ``p_sig`` 信号日前复权价，``ratio = 价(t)/价(now)``（市值 / PB 折算系数），
            ``vol60`` / ``mom60`` 分别为 60 日年化波动与 60 日动量。
        """
        cached = self._derived.get(code)
        if cached is not None:
            return cached

        n = len(day_ints)
        p_sig = np.full(n, np.nan, dtype=np.float64)
        ratio = np.full(n, np.nan, dtype=np.float64)
        vol60 = np.full(n, np.nan, dtype=np.float64)
        mom60 = np.full(n, np.nan, dtype=np.float64)

        kl = self.klines.get(code)
        if kl is not None:
            dates, closes, vols, moms = (list(kl) + [None, None])[:4]
            closes = np.asarray(closes).astype(np.float64)
            p_now = float(closes[-1])
            pos = np.searchsorted(dates, day_ints)
            pos_c = np.clip(pos, 0, len(dates) - 1)
            valid = dates[pos_c] == day_ints
            if p_now > 0:
                for i in range(n):
                    if not valid[i]:
                        continue
                    p = int(pos_c[i])
                    p_sig[i] = closes[p]
                    ratio[i] = closes[p] / p_now
                    if (self.use_stored_metrics and vols is not None
                            and not np.isnan(vols[p])):
                        vol60[i] = vols[p]
                        mom60[i] = moms[p]
                        continue
                    lo = max(0, p - 60)
                    seg = closes[lo:p + 1]
                    if len(seg) >= 21:
                        rr = np.diff(np.log(seg))
                        vol60[i] = rr.std(ddof=1) * np.sqrt(252.0)
                    if lo < p:
                        mom60[i] = closes[p] / closes[lo] - 1.0

        res = (p_sig, ratio, vol60, mom60)
        self._derived[code] = res
        return res


    def __repr__(self):
        return (f'<EnrichContext source={self.source} '
                f'spot={len(self.spot)} industry={len(self.ind_map)} '
                f'klines={len(self.klines)} index={self.idx_kl is not None}>')


def load_index_series(store=None, index_code='000300', datalen=1600):
    """加载沪深300 序列：本地 pkl 优先（口径不变），再退库表 / 网络。"""
    if os.path.isfile(S.IDX_PKL):
        with open(S.IDX_PKL, 'rb') as f:
            d, c = pickle.load(f)
        return (np.asarray(d, dtype=np.int64), np.asarray(c, dtype=np.float32))

    if store is not None:
        try:
            kl = store.load_index(index_code)
            if kl is not None:
                return kl
        except Exception:                            # noqa: BLE001
            pass
    return network.fetch_index_series(index_code, datalen)


def _normalize_klines(raw):
    """网络 2 元组 → 统一的 4 元组（vol60 / mom60 留空表示需就地计算）。"""
    out = {}
    for code, kl in raw.items():
        if kl is None:
            continue
        dates, closes = kl
        out[code] = (np.asarray(dates, dtype=np.int64), closes, None, None)
    return out


def fetch_klines_network(codes, datalen=1600, workers=8, refresh=False,
                         cache_path=None, quiet=False):
    """网络抓取长历史前复权日线（带可断点续抓的 pkl 缓存）。"""
    cache_path = cache_path or S.QFX_KLINE_CACHE
    cache = {}
    if not refresh and os.path.isfile(cache_path):
        with open(cache_path, 'rb') as f:
            cache = pickle.load(f)

    todo = [c for c in codes if not cache.get(c)]
    if not todo:
        if not quiet:
            print(f'[kline] 缓存命中 {len(cache)} 只（{cache_path}），无需抓取')
        return _normalize_klines(cache)

    if not quiet:
        print(f'[kline] 需抓取 {len(todo)} 只（已缓存 {len(cache)}），'
              f'并发 {workers}，datalen={datalen} ...')

    def _progress(done, total):
        if not quiet and (done % 200 == 0 or done == total):
            print(f'  [kline] {done}/{total}', flush=True)
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                pickle.dump({k: v for k, v in cache.items()}, f, protocol=4)

    got = network.fetch_all_klines(todo, workers=workers, datalen=datalen,
                                   on_progress=_progress)
    cache.update(got)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(cache, f, protocol=4)
    if not quiet:
        print(f'[kline] 完成 {len(cache)} 只（新抓成功 '
              f'{sum(1 for v in got.values() if v)}）')
    return _normalize_klines(cache)


def load_context(codes, source='auto', store=None, datalen=1600, workers=8,
                 refresh=False, quiet=False, index_code='000300',
                 write_back=False, batch_size=5000):
    """组装 `EnrichContext`（库表优先，网络兜底）。

    Args:
        codes:     需要的股票代码序列。
        source:    ``'auto'``（默认，库优先+网络补齐）| ``'store'``（只读库）|
                   ``'network'``（只走网络）。
        store:     复用已有 `FactorStore`；None 时自建（source != 'network'）。
        datalen:   网络抓取日线根数。
        workers:   网络并发数。
        refresh:   忽略本地 pkl 缓存重抓。
        write_back: 网络补齐的数据是否回写库表（只在库已存在时生效）。
        index_code: 大盘指数代码。
        quiet:     静默模式。
    """
    codes = [str(c) for c in codes]
    used = 'network' if source == 'network' else 'store'

    if source in ('auto', 'store') and store is None:
        store = FactorStore()

    spot, ind_map, klines = {}, {}, {}
    if used == 'store':
        try:
            store.ensure_tables()
            st = store.stats()
        except Exception as e:                       # noqa: BLE001
            st = None
            used = 'network'
            if not quiet:
                print(f'[ctx] 富化库不可用（{type(e).__name__}: {e}），回退网络')
        if st and st['spot']['rows'] and st['qfq']['rows']:
            spot = store.load_spot()
            ind_map = {c: v['industry'] for c, v in spot.items()
                       if v.get('industry')}
            klines = store.load_klines(codes)
            if not quiet:
                print(f'[ctx] 富化库 source: 快照 {len(spot)} / 行业 '
                      f'{len(ind_map)} / 日线 {len(klines)}  '
                      f'(日线 {st["qfq"]["min_date"]} ~ {st["qfq"]["max_date"]})')
        else:
            used = 'network'
            if not quiet:
                print('[ctx] 富化库为空，回退网络抓取')

    need_kl = [c for c in codes if c not in klines]
    need_spot = [c for c in codes if c not in spot]
    if used == 'network' or need_kl or need_spot:
        if used == 'store' and not quiet:
            print(f'[ctx] 网络补齐：缺日线 {len(need_kl)} 只 / 缺快照 '
                  f'{len(need_spot)} 只')

        if need_spot or not spot:
            net_spot = network.fetch_spot()
            spot.update(net_spot)
            if not quiet:
                print(f'[ctx] 网络快照 {len(net_spot)} 只')

        if not ind_map or len(ind_map) < len(codes) // 2:
            ind_map.update(network.fetch_industry_map())
            if not quiet:
                print(f'[ctx] 网络行业 {len(ind_map)} 只')

        if need_kl or used == 'network':
            target = codes if used == 'network' else need_kl
            klines.update(fetch_klines_network(
                target, datalen=datalen, workers=workers, refresh=refresh,
                quiet=quiet))

        if write_back and store is not None and used == 'store':
            try:
                store.upsert_spot(_spot_rows(spot, codes))
                if not quiet:
                    print('[ctx] 已回写快照到库表')
            except Exception as e:                   # noqa: BLE001
                if not quiet:
                    print(f'[ctx] 回写库表失败：{type(e).__name__}: {e}')

    idx_kl = load_index_series(store if used == 'store' else None,
                              index_code=index_code, datalen=datalen)
    return EnrichContext(spot, ind_map, klines, idx_kl, source=used)


def _spot_rows(spot, codes):
    """把快照字典整理成 `factor_spot` 的列顺序元组序列。"""
    from datetime import date as _date
    from .metrics import board_of
    from .store import to_float
    rows = []
    for code in codes:
        m = spot.get(code)
        if not m:
            continue
        rows.append((code, m.get('name') or '', m.get('industry'),
                     m.get('board') or board_of(code),
                     to_float(m.get('per')), to_float(m.get('pb')),
                     to_float(m.get('mktcap')), to_float(m.get('nmc')),
                     to_float(m.get('price')), _date.today().isoformat()))
    return rows

