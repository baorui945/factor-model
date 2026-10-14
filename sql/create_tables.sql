-- ════════════════════════════════════════════════════════════════════════
-- ai_backtest_model —— 数据表建表脚本
-- 说明：导入器（importers/daily.py / monthly.py）在运行时也会自动建表，
--       本脚本用于手工初始化 / 审计字段口径。
-- ════════════════════════════════════════════════════════════════════════

-- ── 日线后复权表 ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backward_daily (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    stock_code   VARCHAR(20)  NOT NULL COMMENT '6位证券代码',
    stock_name   VARCHAR(100)          COMMENT '证券名称',
    trade_date   DATE         NOT NULL COMMENT '交易日',
    open_price   DECIMAL(10,2)         COMMENT '后复权开盘价',
    high_price   DECIMAL(10,2)         COMMENT '后复权最高价',
    low_price    DECIMAL(10,2)         COMMENT '后复权最低价',
    close_price  DECIMAL(10,2)         COMMENT '后复权收盘价',
    volume       BIGINT                COMMENT '成交量(股)',
    amount       DECIMAL(15,2)         COMMENT '成交额(元)',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_code_date (stock_code, trade_date),
    KEY idx_date (trade_date),
    KEY idx_code (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='日线后复权行情';

-- ── 月线后复权表 ────────────────────────────────────────────────────────
-- 注意：实际库中本表额外带 macd_value / macd_tag 两列（由 MACD 分析工具回写），
--       建表时一并声明，避免结构漂移。
CREATE TABLE IF NOT EXISTS backward_monthly (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    stock_code   VARCHAR(20)  NOT NULL COMMENT '6位证券代码',
    stock_name   VARCHAR(100)          COMMENT '证券名称',
    trade_date   DATE         NOT NULL COMMENT '月末交易日',
    open_price   DECIMAL(10,2)         COMMENT '后复权开盘价',
    high_price   DECIMAL(10,2)         COMMENT '后复权最高价',
    low_price    DECIMAL(10,2)         COMMENT '后复权最低价',
    close_price  DECIMAL(10,2)         COMMENT '后复权收盘价',
    volume       BIGINT                COMMENT '成交量(股)',
    amount       DECIMAL(15,2)         COMMENT '成交额(元)',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    macd_value   DECIMAL(10,2)         COMMENT 'MACD 值(分析工具回写)',
    macd_tag     VARCHAR(100)          COMMENT 'MACD 标签(分析工具回写)',
    UNIQUE KEY uk_code_month (stock_code, trade_date),
    KEY idx_date (trade_date),
    KEY idx_code (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='月线后复权行情';

