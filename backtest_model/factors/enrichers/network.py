# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.network —— 富化数据抓取（新浪 / 东财）
==============================================================================

自 `F:\\quantTrade\\analyzers\\three_factor_segment_analysis.py` 迁入并解耦，
**纯抓取、返回内存结构**，落盘交给 `store.py`（DB）与 `context.py`（缓存）。

数据源
------
* 快照（名称 / PE / PB / 总市值 / 流通市值 / 现价）: 新浪 `Market_Center.getHQNodeData`
* 行业分类                                        : 东财 F10 `RPT_F10_CORETHEME_BOARDTYPE`
                                                    失败时回退新浪行业分类
* 前复权日线（收盘）                              : 新浪 `CN_MarketData.getKLineData`

口径保持与原脚本逐字一致：
* 市值单位 **万元**（入库 / 使用时再折算亿元）；
* 日线收盘为**前复权**，末值 == 不复权现值，故
  ``价(t)/价(now)`` 即为市值 / PB 的历史折算系数；
* 日线日期为 ``int32`` YYYYMMDD，收盘为 ``float32``。
"""

import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'http://finance.sina.com.cn/',
}

_SINA_KLINE = ('http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
               'CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={n}')
_SINA_NODE = ('http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
              'Market_Center.getHQNodeData?page={page}&num=100&sort=symbol&asc=1&node={node}')
_SINA_HY_LIST = 'http://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php'

_EM_DC = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
_EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://data.eastmoney.com/',
}


# ═════════════════════════════════════════════════════════════════════════
# 通用工具
# ═════════════════════════════════════════════════════════════════════════

def _get(url, encoding='utf-8', retries=3, timeout=20):
    """带重试的 HTTP GET，返回文本。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            return urllib.request.urlopen(req, timeout=timeout).read().decode(
                encoding, 'replace')
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(0.8 + 1.5 * i)
    raise last


def _get_json(url, retries=3):
    """带重试的 JSON GET（东财）。"""
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=_EM_HEADERS)
            return json.loads(urllib.request.urlopen(req, timeout=25)
                              .read().decode('utf-8', 'replace'))
        except Exception as e:                       # noqa: BLE001
            last = e
            time.sleep(0.8 + 1.2 * i)
    raise last


def safe_float(v):
    """安全转 float（空值 / 非法值 -> NaN）。"""
    try:
        if v is None or v == '':
            return np.nan
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def sina_symbol(code):
    """6 位代码 → 新浪 symbol（sh/sz/bj 前缀）。"""
    code = str(code)
    if code.startswith('000300'):
        return 'sh' + code
    if code.startswith(('6', '9')):
        return 'sh' + code
    if code.startswith(('4', '8')):
        return 'bj' + code
    return 'sz' + code


# ═════════════════════════════════════════════════════════════════════════
# 快照（名称 / PE / PB / 市值 / 现价）
# ═════════════════════════════════════════════════════════════════════════

def fetch_spot(max_pages=120, node='hs_a'):
    """全市场当前快照。

    Returns:
        ``{code: {name, per, pb, mktcap, nmc, price}}``；
        `mktcap` / `nmc` 单位为**万元**（总市值 / 流通市值），`price` 为不复权现价。
    """
    out, page = {}, 1
    while page <= max_pages:
        txt = _get(_SINA_NODE.format(page=page, node=node))
        if not txt.strip().startswith('['):
            break
        rows = json.loads(txt)
        if not rows:
            break
        for r in rows:
            code = str(r.get('code', ''))
            if not code:
                continue
            out[code] = {
                'name': r.get('name', ''),
                'per': safe_float(r.get('per')),
                'pb': safe_float(r.get('pb')),
                'mktcap': safe_float(r.get('mktcap')),   # 万元（总市值）
                'nmc': safe_float(r.get('nmc')),         # 万元（流通市值）
                'price': safe_float(r.get('trade')),     # 不复权现价
            }
        page += 1
    return out


# ═════════════════════════════════════════════════════════════════════════
# 行业分类
# ═════════════════════════════════════════════════════════════════════════

def _fetch_industry_em():
    """东财 F10 板块类型表 → ``{code: 行业名}``（BOARD_TYPE == '行业'）。"""
    mapping, page, pages = {}, 1, None
    while pages is None or page <= pages:
        url = (f"{_EM_DC}?reportName=RPT_F10_CORETHEME_BOARDTYPE"
               f"&columns=SECURITY_CODE,BOARD_NAME,BOARD_TYPE"
               f"&pageSize=1000&pageNumber={page}"
               f"&sortColumns=SECURITY_CODE&sortTypes=1")
        res = (_get_json(url).get('result') or {})
        data = res.get('data') or []
        if not data:
            break
        for r in data:
            if r.get('BOARD_TYPE') == '行业':
                code = str(r.get('SECURITY_CODE') or '')
                name = r.get('BOARD_NAME')
                if code and name:
                    mapping.setdefault(code, name)
        pages = int(res.get('pages') or 0)
        page += 1
    return mapping


def _fetch_industry_sina():
    """新浪行业分类（备用，约覆盖 3000 只）：``{code: 行业名}``。"""
    txt = _get(_SINA_HY_LIST, encoding='gbk')
    raw = json.loads(txt[txt.index('{'): txt.rindex('}') + 1])

    nodes = {}
    for key, val in raw.items():
        parts = str(val).split(',')
        if len(parts) >= 2:
            nodes[key] = parts[1]

    mapping = {}
    for node, ind_name in nodes.items():
        page = 1
        while page <= 30:
            try:
                rows = json.loads(_get(_SINA_NODE.format(page=page, node=node)))
            except Exception:                        # noqa: BLE001
                break
            if not rows:
                break
            for r in rows:
                code = str(r.get('code', ''))
                if code:
                    mapping.setdefault(code, ind_name)
            if len(rows) < 100:
                break
            page += 1
    return mapping


def fetch_industry_map(min_coverage=1000):
    """股票 → 行业映射。主源东财 F10，失败 / 覆盖不足时用新浪补充。"""
    mapping = {}
    try:
        mapping = _fetch_industry_em()
    except Exception:                                # noqa: BLE001
        pass

    if len(mapping) < min_coverage:
        try:
            for k, v in _fetch_industry_sina().items():
                mapping.setdefault(k, v)
        except Exception:                            # noqa: BLE001
            pass
    return mapping


# ═════════════════════════════════════════════════════════════════════════
# 前复权日线
# ═════════════════════════════════════════════════════════════════════════

def fetch_kline(code, datalen=1600):
    """单只标的前复权日线 → ``(int32 日期数组, float32 收盘价数组)`` 或 None。"""
    sym = sina_symbol(code)
    txt = _get(_SINA_KLINE.format(sym=sym, n=datalen), retries=3)
    if not txt.strip().startswith('['):
        return None
    rows = json.loads(txt)
    if not rows:
        return None
    dates = np.array([int(r['day'].replace('-', '')) for r in rows], dtype=np.int32)
    closes = np.array([safe_float(r['close']) for r in rows], dtype=np.float32)
    return dates, closes


def _kline_safe(code, datalen):
    try:
        return fetch_kline(code, datalen)
    except Exception:                                # noqa: BLE001
        return None


def fetch_all_klines(codes, workers=8, datalen=1600, on_progress=None):
    """并发抓取全部标的前复权日线。

    Args:
        codes:       代码序列。
        workers:     并发数。
        datalen:     每只抓取的日线根数。
        on_progress: 可选回调 ``f(done, total)``，用于断点落盘。

    Returns:
        ``{code: (dates, closes) | None}``。
    """
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_kline_safe, c, datalen): c for c in codes}
        for done, fut in enumerate(as_completed(futs), 1):
            out[futs[fut]] = fut.result()
            if on_progress and done % 200 == 0:
                on_progress(done, len(codes))
    if on_progress:
        on_progress(len(codes), len(codes))
    return out


def fetch_index_series(index_code='000300', datalen=1600):
    """指数前复权日线（沪深300 用于大盘环境）→ ``(dates, closes)`` 或 None。"""
    return fetch_kline(index_code, datalen)

