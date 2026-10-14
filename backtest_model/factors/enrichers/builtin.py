# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.builtin —— 内置富化器
==============================================================================

注册顺序与旧版 `build_features` 的列顺序保持一致：

    board         上市板（代码前缀判定）
    industry      行业（东财 F10 / 新浪，随快照每周更新）
    market_cap    总/流通市值、PB（按前复权价比例折算到信号日）、PE（当前快照）、信号日价
    volatility    60 日年化波动 vol60 / 60 日动量 mom60
    market_regime 沪深300 相对 MA60 偏离 mkt_dev / 60 日动量 mkt_mom60（帧级）
    sig_count     信号密度（同一样本期内该股信号次数）
    year          信号年份（帧级）

新增富化器只需在本文件（或自定义模块）用 ``@register_enricher`` 注册，
再在 `config/enrichers.json` 的 ``enrichers`` 段增删条目即可。
"""

import numpy as np

from .base import Enricher, register_enricher
from .metrics import board_of, index_regime


@register_enricher
class BoardEnricher(Enricher):
    """上市板（沪主板 / 深主板 / 创业板 / 科创板 / 北交所 / 其他）。"""

    key = 'board'
    label = '上市板'
    columns = ('board',)

    def enrich(self, ctx, code, grp, out):
        out['board'] = board_of(code)


@register_enricher
class IndustryEnricher(Enricher):
    """行业分类（取自快照表 / 网络，未分类记 '未分类'）。"""

    key = 'industry'
    label = '行业'
    columns = ('industry',)

    def enrich(self, ctx, code, grp, out):
        out['industry'] = ctx.ind_map.get(code, '未分类')


@register_enricher
class SigCountEnricher(Enricher):
    """信号密度：同一样本期内该股票出现的信号次数。"""

    key = 'sig_count'
    label = '信号密度'
    columns = ('sig_count',)

    def enrich(self, ctx, code, grp, out):
        out['sig_count'] = ctx.sig_count.get(code, len(grp))


@register_enricher
class MarketCapEnricher(Enricher):
    """市值 / 估值：按「前复权价(t) / 前复权价(now)」比值折算到信号日。

    * 总市值 mv_total = 快照总市值(万元)/1e4 × ratio  （亿元）
    * 流通市值 nmc     = 快照流通市值(万元)/1e4 × ratio （亿元）
    * 市净率   pb_t    = 快照 PB × ratio
    * 市盈率   pe_now  = 快照 PE（无法可靠折算，仅代表当前估值）
    * 信号日价 price    = 信号日前复权收盘
    """

    key = 'market_cap'
    label = '市值 / 估值'
    columns = ('mv_total', 'nmc', 'pb_t', 'pe_now', 'price')
    source = 'store'

    def enrich(self, ctx, code, grp, out):
        meta = ctx.spot.get(code, {})
        day_ints = grp['signal_date'].dt.strftime('%Y%m%d').astype(int).to_numpy()
        p_sig, ratio, _, _ = ctx.derived(code, day_ints)

        out['mv_total'] = meta.get('mktcap', np.nan) / 1e4 * ratio
        out['nmc'] = meta.get('nmc', np.nan) / 1e4 * ratio
        pb_now = meta.get('pb', np.nan)
        out['pb_t'] = (pb_now * ratio if pb_now == pb_now
                       else np.full(len(grp), np.nan))
        out['pe_now'] = meta.get('per', np.nan)
        out['price'] = p_sig


@register_enricher
class VolatilityEnricher(Enricher):
    """个股 60 日年化波动率 vol60 与 60 日动量 mom60（信号日口径）。"""

    key = 'volatility'
    label = '60日波动 / 动量'
    columns = ('vol60', 'mom60')
    source = 'store'

    def enrich(self, ctx, code, grp, out):
        day_ints = grp['signal_date'].dt.strftime('%Y%m%d').astype(int).to_numpy()
        _, _, vol60, mom60 = ctx.derived(code, day_ints)
        out['vol60'] = vol60
        out['mom60'] = mom60


@register_enricher
class MarketRegimeEnricher(Enricher):
    """大盘环境（帧级）：沪深300 相对 MA60 偏离 mkt_dev + 60 日动量 mkt_mom60。

    与旧版一致，直接在**全部信号**的日期序列上计算后按位置写入 ``feat``
    （要求 ``sigs`` 按股票聚簇排列，重建信号 CSV 天然满足）。
    """

    key = 'market_regime'
    label = '大盘环境'
    columns = ('mkt_dev', 'mkt_mom60')
    source = 'store'
    scope = 'frame'

    def enrich_frame(self, ctx, sigs, feat):
        day_ints = sigs['signal_date'].dt.strftime('%Y%m%d').astype(int).to_numpy()
        idx_dev, idx_mom = index_regime(ctx.idx_kl, day_ints)
        feat['mkt_dev'] = idx_dev
        feat['mkt_mom60'] = idx_mom


@register_enricher
class YearEnricher(Enricher):
    """信号年份（市场周期维度，帧级）。"""

    key = 'year'
    label = '年份'
    columns = ('year',)
    scope = 'frame'

    def enrich_frame(self, ctx, sigs, feat):
        feat['year'] = feat['signal_date'].dt.year

