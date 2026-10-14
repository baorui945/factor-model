# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.base —— 富化器（Enricher）基类 + 注册表
==============================================================================

**富化器**：为已生成的信号逐条补齐「上下文属性」列（上市板 / 行业 / 市值 /
PB / 波动 / 动量 / 大盘环境 …），是信号表 `sig_all_horizons.pkl` 的「来源层」。

与另外两类因子的分工：

    FeatureFactor  数值因子  —— 回测层，被组合规则筛选用（config/factors.json）
    GateFactor     判定闸门  —— 信号层，判定买点是否成立（config/signal.json）
    Enricher       富化上下文 —— 数据层，为信号补齐属性列（config/enrichers.json）

新增富化器::

    from backtest_model.factors.enrichers import Enricher, register_enricher

    @register_enricher
    class MyEnricher(Enricher):
        key = 'my_col'
        label = '我的属性'
        columns = ('my_col',)
        source = 'derived'          # derived（本地计算）/ store（DB 取数）
        def enrich(self, ctx, code, grp, out):
            out['my_col'] = np.full(len(grp), np.nan)

再在 `config/enrichers.json` 的 `enrichers` 段加入
``{"key": "my_col", "enabled": true}`` 即可，富化 / 回测逻辑无需改动。
"""

_REGISTRY = {}


class Enricher:
    """富化器基类。

    Attributes:
        key:     富化器键（如 'industry'）。
        label:   中文名（说明用）。
        columns: 产出的信号表列名元组（用于文档 / 覆盖检查）。
        source:  'derived'（本地计算）或 'store'（需从快照/日线取数）。
        params:  合并后的参数字典（全局参数 + 本富化器专属参数）。
    """

    key = ''
    label = ''
    columns = ()
    source = 'derived'
    scope = 'group'          # 'group'（逐股票）/ 'frame'（整表帧级）

    def __init__(self, params=None):
        self.params = dict(params or {})

    def enrich(self, ctx, code, grp, out):
        """为一个股票分组补齐列。

        Args:
            ctx:  `EnrichContext`（快照 / 行业 / 前复权日线 / 指数）。
            code: 6 位股票代码。
            grp:  该股票的信号子表（含 ``signal_date`` / ``return_*``）。
            out:  输出字典，按列名写入 ``np.ndarray``（长度 == len(grp)）或标量。
        """
        raise NotImplementedError

    def enrich_frame(self, ctx, sigs, feat):
        """帧级钩子：在全部信号聚合为 `feat` 后补列（``scope == 'frame'`` 时调用）。"""
        return None


    def __repr__(self):
        return f'<Enricher {self.key} ({self.label})>'


def register_enricher(cls):
    """注册一个富化器类（按注册顺序保留）。"""
    if not getattr(cls, 'key', ''):
        raise ValueError('富化器类必须定义非空 key')
    _REGISTRY[cls.key] = cls
    return cls


def get_enricher(key):
    return _REGISTRY[key]


def all_enrichers():
    return list(_REGISTRY.values())


def enricher_keys():
    return list(_REGISTRY.keys())


def build_enrichers(specs, params=None):
    """按配置构造已启用的富化器实例（保序）。

    Args:
        specs:  `config/enrichers.json` 的 ``enrichers`` 段
                ``[{"key", "enabled", "params"}, ...]``。
        params: 全局参数（如 ``kline_datalen``），与各富化器 ``params`` 合并。
    """
    out = []
    for spec in specs or []:
        if not spec.get('enabled', True):
            continue
        cls = _REGISTRY.get(spec['key'])
        if cls is None:
            raise KeyError(f'未注册的富化器: {spec["key"]!r}（可选: {list(_REGISTRY)}）')
        merged = {**(params or {}), **spec.get('params', {})}
        out.append(cls(merged))
    return out
