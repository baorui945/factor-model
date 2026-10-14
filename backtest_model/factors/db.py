# -*- coding: utf-8 -*-
"""
==============================================================================
factors.db —— 行情数据库访问（自包含）
==============================================================================

供信号扫描使用的 MySQL 后复权日线访问层：股票池（过滤 ST / 退市）与单只
股票的 OHLCV。口径与主工程 `MACDAccumulationAnalyzer` 一致。
"""

import threading

import pandas as pd
import pymysql

import config


class MarketDB:
    """MySQL 后复权日线访问器（主连接 + 线程本地连接）。"""

    def __init__(self, table=None, db_config=None):
        self.config = db_config or config.get_db_config()
        self.table_name = table or config.TABLE_BACKWARD_DAILY
        self.connection = None
        self.thread_local = threading.local()

    def connect(self):
        try:
            self.connection = pymysql.connect(
                host=self.config['host'], user=self.config['user'],
                password=self.config['password'],
                database=self.config['database'], port=self.config['port'],
                charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
            print(f'✅ 已连接到数据库: {self.config["database"]}  '
                  f'表: {self.table_name}')
            return True
        except Exception as e:                              # noqa: BLE001
            print(f'❌ 数据库连接失败: {e}')
            return False

    def disconnect(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def _thread_conn(self):
        if getattr(self.thread_local, 'connection', None) is None:
            self.thread_local.connection = pymysql.connect(
                host=self.config['host'], user=self.config['user'],
                password=self.config['password'],
                database=self.config['database'], port=self.config['port'],
                charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
        return self.thread_local.connection

    def _close_thread_conn(self):
        if getattr(self.thread_local, 'connection', None) is not None:
            try:
                self.thread_local.connection.close()
            except Exception:                               # noqa: BLE001
                pass
            self.thread_local.connection = None

    @staticmethod
    def is_st_stock(stock_code, stock_name):
        """是否为 ST / 退市等异常股票。"""
        if not stock_name:
            return False
        for marker in ('ST', '*ST', '退市', '退', 'S*ST', 'SST', 'NST'):
            if marker in stock_name:
                return True
        return False

    def get_all_stock_codes(self):
        """取最新快照的股票池（过滤 ST / 退市）。"""
        query = f"""
            SELECT b.stock_code, b.stock_name FROM (
                SELECT stock_code, stock_name,
                       ROW_NUMBER() OVER (PARTITION BY stock_code
                                          ORDER BY trade_date DESC) AS rn
                FROM {self.table_name}
            ) b WHERE b.rn = 1 ORDER BY b.stock_code
        """
        try:
            cur = self.connection.cursor()
            cur.execute(query)
            rows = cur.fetchall()
        except Exception as e:                              # noqa: BLE001
            print(f'❌ 获取股票代码列表失败: {e}')
            return []
        out, skipped = [], 0
        for row in rows:
            name = row['stock_name'] or ''
            if self.is_st_stock(row['stock_code'], name):
                skipped += 1
                continue
            out.append({'stock_code': row['stock_code'], 'stock_name': name})
        if skipped:
            print(f'  过滤掉 {skipped} 只ST/退市等异常股票')
        print(f'  有效股票数: {len(out)}')
        return out

    def get_stock_data(self, stock_code, limit_days=800, use_thread_conn=False):
        """取单只股票最近 `limit_days` 根日线（按日期升序）。"""
        conn = self._thread_conn() if use_thread_conn else self.connection
        query = f"""
            SELECT stock_code, stock_name, trade_date, open_price, high_price,
                   low_price, close_price, volume, amount
            FROM {self.table_name}
            WHERE stock_code = %s
            ORDER BY trade_date DESC
            LIMIT %s
        """
        try:
            cur = conn.cursor()
            cur.execute(query, (stock_code, limit_days))
            data = cur.fetchall()
        except Exception as e:                              # noqa: BLE001
            print(f'❌ 获取股票 {stock_code} 数据失败: {e}')
            return pd.DataFrame()
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame(data)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        return df.sort_values('trade_date').reset_index(drop=True)
