# -*- coding: utf-8 -*-
"""
==============================================================================
factors.enrichers.store —— 富化数据的数据库落库 / 读回（FactorStore）
==============================================================================

把「行业 / 市值 / PB / 前复权日线 / vol60 / mom60」沉淀到 MySQL，由
`run_update_factors.py` **每周刷新一次**，`enrich_signals.py` 直接读表，
从此不再依赖外部工程 `F:\\quantTrade\\analyzers`。

三张表（表名见 `config/enrichers.json` → `tables`，或 `.env`）
------------------------------------------------------------------
``factor_spot``       个股快照（每只一行，取代抓取快照 + 行业映射）
    stock_code, stock_name, industry, board, pe, pb,
    mktcap（总市值, 万元）, nmc（流通市值, 万元）, price（不复权现价）, snapshot_date

``factor_qfq_daily``  前复权日线收盘 + 派生量（每只每日一行）
    stock_code, trade_date, close_price, vol60, mom60

``factor_index_daily`` 指数日线（大盘环境，可选）
    index_code, trade_date, close_price

精度约定（**关键**）
--------------------
新浪日线收盘原为 ``float32``，本层入库前做 ``float(np.float32(v))``、
读出后再次 ``astype(np.float32)``，从而与旧脚本的 float32 口径**逐位一致**，
保证重建的 ``sig_all_horizons.pkl`` 不因落库而漂移。
"""

import os
import sys
import threading
from datetime import date

import numpy as np
import pymysql

from ... import settings as _S

_ROOT = _S.ROOT_DIR
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config                                                  # noqa: E402

_DDL_SPOT = """
CREATE TABLE IF NOT EXISTS {table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(100),
    industry VARCHAR(100),
    board VARCHAR(20),
    pe DOUBLE,
    pb DOUBLE,
    mktcap DOUBLE COMMENT '总市值(万元)',
    nmc DOUBLE COMMENT '流通市值(万元)',
    price DOUBLE COMMENT '不复权现价',
    snapshot_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code (stock_code),
    INDEX idx_industry (industry)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DDL_QFQ = """
CREATE TABLE IF NOT EXISTS {table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    close_price DOUBLE COMMENT '前复权收盘',
    vol60 DOUBLE COMMENT '60日年化波动率',
    mom60 DOUBLE COMMENT '60日动量',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date (stock_code, trade_date),
    INDEX idx_date (trade_date),
    INDEX idx_stock (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DDL_INDEX = """
CREATE TABLE IF NOT EXISTS {table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    close_price DOUBLE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date (index_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_UPSERT_SPOT = """
INSERT INTO {table}
    (stock_code, stock_name, industry, board, pe, pb, mktcap, nmc, price, snapshot_date)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    stock_name    = VALUES(stock_name),
    industry      = VALUES(industry),
    board         = VALUES(board),
    pe            = VALUES(pe),
    pb            = VALUES(pb),
    mktcap        = VALUES(mktcap),
    nmc           = VALUES(nmc),
    price         = VALUES(price),
    snapshot_date = VALUES(snapshot_date)
"""

_UPSERT_QFQ = """
INSERT INTO {table}
    (stock_code, trade_date, close_price, vol60, mom60)
VALUES (%s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    close_price = VALUES(close_price),
    vol60       = VALUES(vol60),
    mom60       = VALUES(mom60)
"""

_UPSERT_INDEX = """
INSERT INTO {table}
    (index_code, trade_date, close_price)
VALUES (%s, %s, %s)
ON DUPLICATE KEY UPDATE close_price = VALUES(close_price)
"""


# ═════════════════════════════════════════════════════════════════════════
# 工具
# ═════════════════════════════════════════════════════════════════════════

def to_f32(v):
    """float32 精度回写（``None`` / NaN -> None），保证落库-回读逐位无损。"""
    try:
        if v is None:
            return None
        f = float(np.float32(v))
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def to_float(v):
    """宽松转 float（NaN -> None）。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def date_iso(day_int):
    """``YYYYMMDD`` 整数 / 字符串 → ``'YYYY-MM-DD'``。"""
    s = str(int(day_int))
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}'


def day_int(x):
    """DATE / 字符串 → ``YYYYMMDD`` 整数。"""
    return int(str(x).replace('-', '').replace('/', '')[:8])


# ═════════════════════════════════════════════════════════════════════════
# FactorStore
# ═════════════════════════════════════════════════════════════════════════

class FactorStore:
    """富化三表（快照 / 前复权日线 / 指数）的读写器。

    Args:
        db_config: MySQL 连接配置，默认 `config.get_db_config()`。
        tables:    ``{'spot', 'qfq_daily', 'index_daily'}`` 表名映射，
                   默认 `config.get_factor_tables()`。
    """

    def __init__(self, db_config=None, tables=None):
        self.config = db_config or config.get_db_config()
        self.tables = tables or config.get_factor_tables()
        self.connection = None
        self.thread_local = threading.local()

    # ── 连接 ────────────────────────────────────────────────────────────
    def _connect(self):
        return pymysql.connect(
            host=self.config['host'], user=self.config['user'],
            password=self.config['password'], database=self.config['database'],
            port=self.config['port'], charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor)

    def connect(self, verbose=True):
        if self.connection is None:
            self.connection = self._connect()
            if verbose:
                print(f'✅ 富化库存: {self.config["database"]}  '
                      f'表 {self.tables["spot"]} / {self.tables["qfq_daily"]} / '
                      f'{self.tables["index_daily"]}')
        return self.connection

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self):
        self.connect(verbose=False)
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def ensure_tables(self):
        """建表（幂等）。"""
        cn = self.connect(verbose=False)
        with cn.cursor() as cur:
            cur.execute(_DDL_SPOT.format(table=self.tables['spot']))
            cur.execute(_DDL_QFQ.format(table=self.tables['qfq_daily']))
            cur.execute(_DDL_INDEX.format(table=self.tables['index_daily']))
        cn.commit()
        return self.tables

    # ── 写入 ────────────────────────────────────────────────────────────
    def upsert_spot(self, rows):
        """整表刷新个股快照（``rows`` 为列顺序元组序列）。"""
        cn = self.connect(verbose=False)
        sql = _UPSERT_SPOT.format(table=self.tables['spot'])
        with cn.cursor() as cur:
            if rows:
                cur.executemany(sql, list(rows))
        cn.commit()
        return len(rows)

    def upsert_qfq(self, rows, batch_size=5000):
        """批量幂等写入前复权日线（``rows``：code, date, close, vol60, mom60）。"""
        cn = self.connect(verbose=False)
        sql = _UPSERT_QFQ.format(table=self.tables['qfq_daily'])
        n = 0
        with cn.cursor() as cur:
            for i in range(0, len(rows), batch_size):
                blk = list(rows[i:i + batch_size])
                cur.executemany(sql, blk)
                cn.commit()
                n += len(blk)
        return n

    def upsert_index(self, rows, batch_size=5000):
        """批量幂等写入指数日线。"""
        cn = self.connect(verbose=False)
        sql = _UPSERT_INDEX.format(table=self.tables['index_daily'])
        n = 0
        with cn.cursor() as cur:
            for i in range(0, len(rows), batch_size):
                blk = list(rows[i:i + batch_size])
                cur.executemany(sql, blk)
                cn.commit()
                n += len(blk)
        return n

    # ── 读回 ────────────────────────────────────────────────────────────
    def load_spot(self):
        """读回个股快照 → ``{code: {name, per, pb, mktcap, nmc, price, industry, board}}``。

        键名与 `network.fetch_spot` 完全对齐，可直接喂给富化流程。
        """
        cn = self.connect(verbose=False)
        with cn.cursor() as cur:
            cur.execute(
                f"SELECT stock_code, stock_name, industry, board, pe, pb, "
                f"mktcap, nmc, price, snapshot_date FROM {self.tables['spot']}")
            rows = cur.fetchall()
        out = {}
        for r in rows:
            code = str(r['stock_code'])
            out[code] = {
                'name': r['stock_name'] or '',
                'per': r['pe'] if r['pe'] is not None else np.nan,
                'pb': r['pb'] if r['pb'] is not None else np.nan,
                'mktcap': r['mktcap'] if r['mktcap'] is not None else np.nan,
                'nmc': r['nmc'] if r['nmc'] is not None else np.nan,
                'price': r['price'] if r['price'] is not None else np.nan,
                'industry': r['industry'] or None,
                'board': r['board'] or None,
                'snapshot_date': (str(r['snapshot_date'])
                                  if r['snapshot_date'] else None),
            }
        return out

    def load_industry(self):
        """读回股票 → 行业映射（``{code: 行业名}``）。"""
        return {c: v['industry'] for c, v in self.load_spot().items()
                if v.get('industry')}

    def load_klines(self, codes, chunk=64):
        """按代码分批读回前复权日线。

        Returns:
            ``{code: (dates(int64), closes(float32), vol60(f8), mom60(f8))}``；
            ``closes`` 以 float32 精度回放，与原抓取口径逐位一致。
        """
        cn = self.connect(verbose=False)
        codes = [str(c) for c in codes]
        table = self.tables['qfq_daily']
        out = {}
        with cn.cursor() as cur:
            for i in range(0, len(codes), chunk):
                ch = codes[i:i + chunk]
                ph = ','.join(['%s'] * len(ch))
                cur.execute(
                    f"SELECT stock_code, trade_date, close_price, vol60, mom60 "
                    f"FROM {table} WHERE stock_code IN ({ph}) "
                    f"ORDER BY stock_code, trade_date", ch)
                row = cur.fetchone()
                cur_code, d, c, v, m = None, [], [], [], []
                while row is not None:
                    code = str(row['stock_code'])
                    if code != cur_code:
                        if cur_code is not None:
                            out[cur_code] = _pack(d, c, v, m)
                        cur_code, d, c, v, m = code, [], [], [], []
                    d.append(day_int(row['trade_date']))
                    c.append(row['close_price'] if row['close_price'] is not None
                             else np.nan)
                    v.append(row['vol60'] if row['vol60'] is not None else np.nan)
                    m.append(row['mom60'] if row['mom60'] is not None else np.nan)
                    row = cur.fetchone()
                if cur_code is not None:
                    out[cur_code] = _pack(d, c, v, m)
        return out

    def load_index(self, index_code='000300'):
        """读回指数日线 → ``(dates(int64), closes(float32))`` 或 None。"""
        cn = self.connect(verbose=False)
        with cn.cursor() as cur:
            cur.execute(
                f"SELECT trade_date, close_price FROM {self.tables['index_daily']} "
                f"WHERE index_code = %s ORDER BY trade_date", (str(index_code),))
            rows = cur.fetchall()
        if not rows:
            return None
        d = [day_int(r['trade_date']) for r in rows]
        c = [r['close_price'] if r['close_price'] is not None else np.nan
             for r in rows]
        return (np.asarray(d, dtype=np.int64),
                np.asarray(c, dtype=np.float32))

    # ── 元信息 ──────────────────────────────────────────────────────────
    def stats(self):
        """返回三表的行数与最新日期，用于新鲜度判断。"""
        cn = self.connect(verbose=False)
        out = {}
        with cn.cursor() as cur:
            for key, table, date_col in (
                    ('spot', self.tables['spot'], 'snapshot_date'),
                    ('qfq', self.tables['qfq_daily'], 'trade_date'),
                    ('index', self.tables['index_daily'], 'trade_date')):
                cur.execute(f"SELECT COUNT(*) AS n, MIN({date_col}) AS lo, "
                            f"MAX({date_col}) AS hi FROM {table}")
                r = cur.fetchone() or {}
                out[key] = {'rows': int(r.get('n') or 0),
                            'min_date': str(r['lo']) if r.get('lo') else None,
                            'max_date': str(r['hi']) if r.get('hi') else None}
        return out


def _pack(dates, closes, vols, moms):
    """把逐行列表打包为定长数组（float32 回放收盘，逐位对齐抓取口径）。"""
    return (np.asarray(dates, dtype=np.int64),
            np.asarray(closes, dtype=np.float32),
            np.asarray(vols, dtype=np.float64),
            np.asarray(moms, dtype=np.float64))

