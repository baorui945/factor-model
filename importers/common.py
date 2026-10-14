# -*- coding: utf-8 -*-
"""
==============================================================================
导入器公共工具：数据库连接 / 建表 / 批量写入 / baostock 抓取 / 本地文件解析
==============================================================================

被 `importers/daily.py`（日线）与 `importers/monthly.py`（月线）共用。

统一数据模型（两张表结构一致）::

    stock_code, stock_name, trade_date,
    open_price, high_price, low_price, close_price, volume, amount

写入策略：`INSERT ... ON DUPLICATE KEY UPDATE`，依赖唯一键
`(stock_code, trade_date)` 实现**幂等增量导入**（重复运行不会产生脏数据）。
"""

import os
import re
import sys
import glob
import time
import logging
from datetime import date, datetime
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd
import pymysql

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config  # noqa: E402

try:
    from tqdm import tqdm
except ImportError:                                   # pragma: no cover
    def tqdm(it=None, **kw):                          # 退化实现
        return it if it is not None else []


# ═════════════════════════════════════════════════════════════════════════
# 常量
# ═════════════════════════════════════════════════════════════════════════

#: 统一行情列（与建表结构一一对应）
BAR_COLUMNS = ['stock_code', 'stock_name', 'trade_date',
               'open_price', 'high_price', 'low_price', 'close_price',
               'volume', 'amount']

#: 频率 -> (表名, baostock frequency, 表唯一键名)
#: 表名统一取自 config，可用 .env / 环境变量覆盖：
#:   TABLE_BACKWARD_DAILY   （默认 backward_daily）
#:   TABLE_BACKWARD_MONTHLY （默认 backward_monthly）
FREQ_SPEC = {
    'daily':   (config.TABLE_BACKWARD_DAILY,   'd', 'uk_code_date'),
    'monthly': (config.TABLE_BACKWARD_MONTHLY, 'm', 'uk_code_month'),
}

_LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
_LOG = logging.getLogger('importer')


def setup_logging(level: int = logging.INFO, log_file: Optional[str] = None) -> None:
    """初始化导入器日志（控制台 + 可选文件）。"""
    _LOG.setLevel(level)
    _LOG.propagate = False
    if not _LOG.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(_LOG_FORMAT))
        _LOG.addHandler(sh)
    if log_file:
        fh = logging.FileHandler(log_file, encoding='utf-8')
        fh.setFormatter(logging.Formatter(_LOG_FORMAT))
        _LOG.addHandler(fh)


# ═════════════════════════════════════════════════════════════════════════
# 数据库
# ═════════════════════════════════════════════════════════════════════════

def get_connection(local_infile: bool = False,
                   with_dict: bool = False) -> pymysql.connections.Connection:
    """建立 MySQL 连接（沿用 config.get_db_config()）。"""
    cfg = config.get_db_config()
    params = {
        'host': cfg['host'], 'port': cfg['port'], 'user': cfg['user'],
        'password': cfg['password'], 'database': cfg['database'],
        'charset': cfg['charset'] or 'utf8mb4',
        'cursorclass': (pymysql.cursors.DictCursor if with_dict
                        else pymysql.cursors.Cursor),
    }
    if local_infile:
        params['local_infile'] = True
    return pymysql.connect(**params)


_DDL_DAILY = """
CREATE TABLE IF NOT EXISTS {table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(100),
    trade_date DATE NOT NULL,
    open_price DECIMAL(10,2),
    high_price DECIMAL(10,2),
    low_price DECIMAL(10,2),
    close_price DECIMAL(10,2),
    volume BIGINT,
    amount DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date (stock_code, trade_date),
    INDEX idx_date (trade_date),
    INDEX idx_stock (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# 月线表额外保留 macd_value / macd_tag 两列（与既有库结构对齐）
_DDL_MONTHLY = """
CREATE TABLE IF NOT EXISTS {table} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(20) NOT NULL,
    stock_name VARCHAR(100),
    trade_date DATE NOT NULL,
    open_price DECIMAL(10,2),
    high_price DECIMAL(10,2),
    low_price DECIMAL(10,2),
    close_price DECIMAL(10,2),
    volume BIGINT,
    amount DECIMAL(15,2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    macd_value DECIMAL(10,2),
    macd_tag VARCHAR(100),
    UNIQUE KEY uk_code_month (stock_code, trade_date),
    INDEX idx_date (trade_date),
    INDEX idx_stock (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DDL = {'daily': _DDL_DAILY, 'monthly': _DDL_MONTHLY}


def ensure_table(conn, freq: str) -> str:
    """按频率确保目标表存在，返回表名。"""
    table, _, _ = FREQ_SPEC[freq]
    with conn.cursor() as cur:
        cur.execute(_DDL[freq].format(table=table))
    conn.commit()
    return table


# ── 批量幂等写入 ─────────────────────────────────────────────────────────

_UPSERT_SQL = """
INSERT INTO {table}
    (stock_code, stock_name, trade_date, open_price, high_price, low_price,
     close_price, volume, amount)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    stock_name  = VALUES(stock_name),
    open_price  = VALUES(open_price),
    high_price  = VALUES(high_price),
    low_price   = VALUES(low_price),
    close_price = VALUES(close_price),
    volume      = VALUES(volume),
    amount      = VALUES(amount)
"""


def upsert_bars(conn, table: str, rows: Sequence[tuple],
                batch_size: int = 2000) -> int:
    """批量幂等写入行情数据。

    Args:
        conn: MySQL 连接
        table: 目标表名
        rows: 元素为 `BAR_COLUMNS` 顺序的元组序列
        batch_size: 每批提交行数

    Returns:
        实际提交的行数
    """
    if not rows:
        return 0
    sql = _UPSERT_SQL.format(table=table)
    n = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), batch_size):
            blk = list(rows[i:i + batch_size])
            cur.executemany(sql, blk)
            conn.commit()
            n += len(blk)
    return n


def table_stats(conn, table: str) -> Tuple[int, Optional[date], Optional[date]]:
    """返回 (行数, 最早交易日, 最晚交易日)。"""
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
                    f"FROM {table}")
        n, lo, hi = cur.fetchone()
        if isinstance(n, dict):                      # DictCursor 兜底
            n, lo, hi = n.get('COUNT(*)'), n.get('MIN(trade_date)'), n.get('MAX(trade_date)')
    return int(n or 0), lo, hi


# ═════════════════════════════════════════════════════════════════════════
# baostock 数据源
# ═════════════════════════════════════════════════════════════════════════

#: 只取必要字段（月线 frequency='m' 同样支持这批字段）
_BS_FIELDS = 'date,code,open,high,low,close,volume,amount'


def bs_login():
    """登录 baostock，返回模块句柄。"""
    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        raise RuntimeError(f'baostock 登录失败: {lg.error_code} {lg.error_msg}')
    return bs


def bs_logout(bs) -> None:
    """安全登出 baostock。"""
    try:
        bs.logout()
    except Exception:
        pass


def to_bs_code(code6: str) -> str:
    """6 位纯数字代码 -> baostock 前缀代码（sh./sz./bj.）。"""
    code6 = str(code6).strip().zfill(6)
    if code6[0] in ('6', '5', '9'):
        return 'sh.' + code6
    if code6[0] in ('0', '1', '2', '3'):
        return 'sz.' + code6
    return 'bj.' + code6


def from_bs_code(bs_code: str) -> str:
    """baostock 前缀代码 -> 6 位纯数字代码。"""
    return str(bs_code).split('.')[-1].strip().zfill(6)


def _f(x) -> Optional[float]:
    """宽松转 float（空串 / 非法值 -> None）。"""
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _i(x) -> Optional[int]:
    """宽松转 int。"""
    v = _f(x)
    return int(v) if v is not None else None


def fetch_bs_bars(bs, code6: str, freq: str, start: str, end: str,
                  adjustflag: str = '1', stock_name: str = '') -> List[tuple]:
    """抓取单只股票一段行情。

    Args:
        bs: `bs_login()` 返回的句柄
        code6: 6 位证券代码
        freq: 'daily' | 'monthly'
        start / end: 'YYYY-MM-DD'
        adjustflag: '1'=后复权(hfq) / '2'=前复权 / '3'=不复权
        stock_name: 证券名称（写入库中，可选）

    Returns:
        `BAR_COLUMNS` 顺序的元组列表
    """
    _, bs_freq, _ = FREQ_SPEC[freq]
    rs = bs.query_history_k_data_plus(
        to_bs_code(code6), _BS_FIELDS,
        start_date=start, end_date=end,
        frequency=bs_freq, adjustflag=adjustflag)
    if rs.error_code != '0':
        raise RuntimeError(f'baostock {code6} 查询失败: '
                           f'{rs.error_code} {rs.error_msg}')
    out: List[tuple] = []
    while rs.next():
        r = rs.get_row_data()
        if len(r) < 8 or not r[0]:
            continue
        close = _f(r[5])
        if close is None:                # 停牌日无收盘价，跳过
            continue
        out.append((code6, stock_name, r[0],
                    _f(r[2]), _f(r[3]), _f(r[4]), close, _i(r[6]), _f(r[7])))
    return out


def list_bs_universe(bs, day: Optional[str] = None) -> List[Tuple[str, str]]:
    """用 baostock 取全部 A 股 (代码, 名称)。

    会自动剔除指数 / B 股 / 退市代码：只保留 6 位且首位在 0/3/6 的标的。
    """
    day = day or datetime.now().strftime('%Y-%m-%d')
    rs = bs.query_all_stock(day=day)
    if rs.error_code != '0':
        raise RuntimeError(f'baostock query_all_stock 失败: '
                           f'{rs.error_code} {rs.error_msg}')
    out, seen = [], set()
    while rs.next():
        code, _status, name = rs.get_row_data()[:3]
        c6 = from_bs_code(code)
        if len(c6) != 6 or c6[0] not in ('0', '3', '6') or c6 in seen:
            continue
        seen.add(c6)
        out.append((c6, name or ''))
    return sorted(out)


def list_db_universe(conn, table: str = 'backward_daily',
                     with_name: bool = True) -> List[Tuple[str, str]]:
    """从既有表中读取股票池（代码, 名称），用于确定增量导入范围。

    表不存在或为空时返回空列表（调用方可退回 baostock 全市场名单）。
    """
    try:
        if with_name:
            sql = (f"SELECT stock_code, MAX(stock_name) FROM {table} "
                   f"GROUP BY stock_code ORDER BY stock_code")
        else:
            sql = (f"SELECT DISTINCT stock_code, '' FROM {table} "
                   f"ORDER BY stock_code")
        with conn.cursor() as cur:
            cur.execute(sql)
            return [(str(r[0]).zfill(6), r[1] or '') for r in cur.fetchall()]
    except Exception as e:
        _LOG.debug('读取股票池失败(%s): %s', table, e)
        return []


def read_code_file(path: str) -> List[str]:
    """读取代码清单文件（每行一个代码，支持逗号/空白分隔，# 注释）。"""
    codes = []
    with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            for tok in re.split(r'[,\s;]+', line):
                tok = tok.strip()
                if tok:
                    codes.append(from_bs_code(tok) if '.' in tok
                                 else tok.zfill(6))
    return sorted(set(codes))


# ═════════════════════════════════════════════════════════════════════════
# 本地文件数据源（兼容 TDX 导出文本）
# ═════════════════════════════════════════════════════════════════════════

_FILE_COLS = ['trade_date', 'open_price', 'high_price', 'low_price',
              'close_price', 'volume', 'amount']


def code_from_filename(path: str) -> str:
    """从文件名解析股票代码：`sh#600000.txt` / `600000.txt` -> `600000`。"""
    fn = os.path.basename(path)
    if '#' in fn:
        fn = fn.split('#')[1]
    return from_bs_code(os.path.splitext(fn)[0]) if fn else ''


def name_from_header(path: str) -> str:
    """从文件首行提取股票名称（形如 `600000 浦发银行 日线 后复权`）。"""
    for enc in ('gbk', 'utf-8', 'utf-8-sig'):
        try:
            with open(path, 'r', encoding=enc, errors='ignore') as f:
                head = f.readline().strip()
            break
        except OSError:
            return ''
    m = re.search(r'[\u4e00-\u9fff]{2,}', head)
    return m.group(0) if m else ''


def _norm_date(x) -> Optional[str]:
    """归一化日期字符串为 'YYYY-MM-DD'。"""
    s = str(x).strip().replace('/', '-').replace('.', '-')
    if not s:
        return None
    if s.isdigit() and len(s) == 8:
        s = f'{s[:4]}-{s[4:6]}-{s[6:]}'
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        return None


def parse_bars_file(path: str,
                    freq: str = 'daily',
                    start: Optional[str] = None,
                    end: Optional[str] = None) -> Tuple[str, str, List[tuple]]:
    """解析单个行情文本文件（TDX 导出格式）。

    文件内容为空白分隔，**首行为表头**（跳过），列顺序::

        trade_date  open  high  low  close  volume  amount

    也兼容带英文/中文表头的 CSV（按列名自动识别）。

    Args:
        path: 行情文本路径
        freq: 'daily' | 'monthly'（当前解析逻辑两者同构）
        start / end: 可选的日期闭区间过滤（'YYYY-MM-DD'）；None 表示不过滤

    Returns:
        (code6, stock_name, rows) —— rows 为 `BAR_COLUMNS` 顺序的元组列表
    """
    code6 = code_from_filename(path)
    name = name_from_header(path)

    df = None
    for enc in ('utf-8-sig', 'gbk'):
        try:
            df = pd.read_csv(path, sep=r'\s+', header=None, skiprows=1,
                             names=_FILE_COLS, engine='python',
                             encoding=enc, skip_blank_lines=True)
            break
        except Exception:
            df = None
    if df is None or df.empty:
        return code6, name, []

    df['trade_date'] = df['trade_date'].map(_norm_date)
    df = df.dropna(subset=['trade_date'])
    if start:                                        # 可选：按日期闭区间过滤
        df = df[df['trade_date'] >= str(start)[:10]]
    if end:
        df = df[df['trade_date'] <= str(end)[:10]]
    if df.empty:
        return code6, name, []

    for c in ('open_price', 'high_price', 'low_price', 'close_price',
              'volume', 'amount'):
        df[c] = pd.to_numeric(df[c], errors='coerce')

    rows = []
    for r in df.itertuples(index=False):
        if r.close_price != r.close_price:           # NaN 收盘价
            continue
        rows.append((code6, name, r.trade_date,
                     _f(r.open_price), _f(r.high_price), _f(r.low_price),
                     _f(r.close_price), _i(r.volume), _f(r.amount)))
    return code6, name, rows


def iter_bars_files(directory: str, pattern: str = '*.txt') -> List[str]:
    """列出目录下匹配的行情文件（按文件名排序）。"""
    return sorted(glob.glob(os.path.join(directory, pattern)))


