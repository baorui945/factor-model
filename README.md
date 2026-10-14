# ai_backtest_model —— 三因子买点「最优组合」策略级回测工程

> 从 `quantTrade` 主工程中**独立拆出**的回测工程：自带日线/月线数据导入能力，
> 与主工程解耦（只依赖 MySQL 数据 + 工程内 `data/` 资产）。

---

## 1. 工程定位

本工程做两件事：

| # | 能力 | 入口 | 说明 |
|---|------|------|------|
| 1 | **数据导入**（仅日线 / 月线） | `run_import.py` | 从 baostock 或本地 TDX 文本导入到 MySQL |
| 2 | **策略级回测** | `run_backtest.py` | 三因子买点「最优组合」日频等权组合回测 + Excel/图表 |

回测口径：信号日 **T 收盘价**建仓，持有 **N 个交易日**后收盘价平仓，
持有期内同一只股票**不重复建仓**，每日对所有在持标的**等权**，
建仓/平仓各扣 **0.10%**，基准为**沪深300**。

---

## 2. 目录结构

```
F:\ai_backtest_model\
├── config.py                  # 配置加载（读同目录 .env，工程内自包含）
├── .env                       # 实际数据库配置（由主工程复制；已就绪）
├── .env.example               # 配置模板
├── requirements.txt           # 依赖清单
├── run_import.py              # ★ 数据导入统一入口（--freq daily|monthly|all）
├── run_backtest.py            # ★ 回测主入口
├── rebuild_signals.py         # ★ 信号重建：在新数据表上重扫三因子买点（可断点续跑）
├── run_update_factors.py      # ★ 富化数据刷新：行业/市值/PB/前复权日线/vol60 → MySQL（每周）
├── enrich_signals.py          # ★ 信号富化：读富化库补齐因子 → 信号池 pkl（网络兜底）
├── scripts/
│   └── update_factors_weekly.bat  #   计划任务入口（每周一 02:00，--if-stale 自动跳过）
├── _prepull_px.py             #   工具：回测价格缓存预热（14 块批量拉取 → parquet）
├── _run_wait.py               #   工具：后台起命令 + 阻塞等待 + 回吐日志尾部（长任务用）
├── _parity_report.py          #   工具：新旧信号池对拍明细（差异分布）
├── _check_fresh.py            #   工具：数据新鲜度体检（DB vs 缓存/信号池/指数）
│
├── importers/                 # 数据导入子包（只做日线/月线）
│   ├── common.py              #   连接 / 建表 / 幂等 upsert / baostock / 文件解析
│   ├── base.py                #   通用导入流程（网络通道 + 文件通道）
│   ├── daily.py               #   日线 CLI  -> backward_daily
│   └── monthly.py             #   月线 CLI  -> backward_monthly
│
├── config/                    # ★ 因子 / 闸门 / 富化配置（唯一扩展点，改这里即可加因子）
│   ├── factors.json           #   回测层因子：组合 / 敏感性 / 分层
│   ├── signal.json            #   信号层：指标参数 + F1/F2/F3 闸门
│   └── enrichers.json         #   富化层：抓取参数 + 富化器清单 + 分档边界
│
├── backtest_model/            # 回测模型子包
│   ├── settings.py            #   路径与默认参数（唯一来源）
│   ├── data.py                #   信号池 / 价格抓取缓存 / 沪深300 / 价格面板
│   ├── engine.py              #   去重建仓 / 日频等权回测 / 绩效指标 / 逐笔明细
│   ├── factors/               # ★ 因子插件体系（数值因子 + 判定闸门 + 富化器，见 §11/§12）
│   │   ├── base.py            #     FeatureFactor + 规则求值 evaluate_rules
│   │   ├── registry.py        #     因子注册表 + factors/signal/enrichers.json 加载
│   │   ├── builtin.py         #     内置数值因子（nmc/vol60/mom60/mkt_dev/pb_t）
│   │   ├── indicators.py      #     MA / MACD 指标（参数化）
│   │   ├── gates/             #     判定型闸门 F1 / F2 / F3（可插拔）
│   │   ├── enrichers/         #     信号富化层（可插拔，见 §12）
│   │   │   ├── base.py        #       Enricher 基类 + 注册表
│   │   │   ├── network.py     #       新浪/东财抓取（快照 / 行业 / 前复权日线）
│   │   │   ├── store.py       #       FactorStore：富化三表读写（MySQL）
│   │   │   ├── metrics.py     #       上市板 / vol60 / mom60 / 大盘环境
│   │   │   ├── context.py     #       EnrichContext：库表优先、网络兜底
│   │   │   ├── builtin.py     #       内置富化器（board/industry/market_cap/…）
│   │   │   ├── buckets.py     #       富化列分档
│   │   │   └── pipeline.py    #       build_features / enrich_signals 编排
│   │   ├── model.py           #     ThreeFactorModel（配置 + 闸门组装）
│   │   ├── scanner.py         #     滚动扫描（单只股票逐日判定）
│   │   └── db.py              #     MySQL 日线访问（自包含）
│   ├── combos.py              #   组合定义（读 config/factors.json）
│   ├── analysis.py            #   绩效总览 / 年度月度 / 敏感性 / 因子分层 / 说明
│   ├── excel_report.py        #   多 Sheet Excel 导出（涨跌着色）
│   ├── charts.py              #   6 面板净值图
│   └── run.py                 #   回测 CLI 实现
│
├── data/                      # 工程内数据资产
│   ├── sig_all_horizons.pkl   #   三因子信号池（42,875 条 × 33 列 / 11.7 MB）
│   │                          #     由 rebuild+enrich 在 backward_tdx_daily 上重建
│   ├── idx_000300.pkl         #   沪深300 收盘
│   └── _cache/                #   后复权价格 parquet 缓存 + 前复权日线缓存（自动生成）
│
├── logs/                      # 计划任务日志（自动生成）
├── samples/day/               # 本地文件导入样例（TDX 文本格式）
├── sql/create_tables.sql      # 建表脚本（导入器也会自动建表）
├── output/                    # 回测产物（xlsx / csv / charts）
├── temp/                      # 归档：一次性探查/诊断脚本 + 中间缓存（非系统流程）
│                              #   已被主流程取代或被 run_update_factors.py 覆盖，见 temp/README.md
├── .gitignore                 # 忽略 .env / 缓存 / 输出 / temp
└── README.md                  # 本文件
```

---

## 3. 快速开始

### 3.1 安装依赖

```bat
cd F:\ai_backtest_model
pip install -r requirements.txt
```

> 若直接复用主工程虚拟环境，可跳过本步：
> `F:\quantTrade\venv\Scripts\python.exe`

### 3.2 配置数据库

`.env` 已从主工程复制（`DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME`）。
如换环境，请复制 `.env.example` 为 `.env` 后修改。

自检（不写库）：

```bat
python run_import.py --freq daily --limit 5 --dry-run
```

### 3.3 导入数据

```bat
:: 日线：全市场，2021-06-01 至今（后复权）
python run_import.py --freq daily --start 2021-06-01

:: 月线：全市场，2015-01-01 至今
python run_import.py --freq monthly --start 2015-01-01

:: 日线 + 月线 一次完成
python run_import.py --freq all --start 2021-06-01

:: 只导指定股票
python run_import.py --freq daily --codes 600354,000001,300750
```

### 3.4 运行回测

```bat
python run_backtest.py                              :: 默认 20/30/40/60 持有期
python run_backtest.py --horizons 20 --no-cost      :: 只跑 20 日、免成本
python run_backtest.py --chart                      :: 额外输出 6 面板净值图
python run_backtest.py --refresh                    :: 强制重拉价格缓存
python run_backtest.py --out D:\my.xlsx             :: 自定义输出路径
```

---

## 4. 数据导入（仅日线 / 月线）

### 4.1 两条通道

| 通道 | 参数 | 数据源 | 适用场景 |
|------|------|--------|----------|
| **网络源**（默认） | `--source baostock` | baostock 后复权(hfq) | 新环境一次性灌数 / 补齐历史 |
| **文件源** | `--source file --dir <目录>` | 本地 TDX 导出文本 | 离线导入 / 已有 TDX 数据 |

### 4.2 目标表

| 频率 | 表名 | 唯一键 | baostock 频率 |
|------|------|--------|---------------|
| 日线 | `backward_daily` | `(stock_code, trade_date)` | `d` |
| 月线 | `backward_monthly` | `(stock_code, trade_date)` | `m` |

写入字段统一为：
`stock_code, stock_name, trade_date, open_price, high_price, low_price, close_price, volume, amount`

> `backward_monthly` 另有 `macd_value` / `macd_tag` 两列（由主工程 MACD 工具回写），
> 本工程 upsert **不会触碰**这两列。

### 4.3 幂等与增量

写入语句为 `INSERT ... ON DUPLICATE KEY UPDATE`，配合唯一键：

* **重复运行不产生脏数据**，同 `(代码, 日期)` 会被覆盖为最新拉取值；
* 指定 `--start` 为更晚日期即为**增量补齐**；
* 只想补表内已有股票的缺口时用 `--universe db`（默认 `all` 走全市场名单）。

### 4.4 常用参数

```bat
--start / --end           日期区间（YYYY-MM-DD）
--codes 600354,000001     指定代码
--code-file codes.txt     代码清单文件（每行一个，支持 # 注释）
--universe all|db         股票池来源
--limit N                 只处理前 N 只（连通性测试）
--adjustflag 1|2|3        1=后复权(默认) 2=前复权 3=不复权
--truncate                导入前清空目标表（文件源全量重建用，危险）
--dry-run                 只抓取/解析，不写库
--sleep S                 每只之间休眠秒数
-v                        调试日志
```

### 4.5 本地文件格式（TDX 导出）

文件名：`sh#600354.txt` 或 `600354.txt`（取 `#` 后 / 扩展名前 的 6 位代码）
首行：表头（含股票名称，形如 `600354 敦煌种业 日线 后复权`）
正文：空白分隔，列顺序 `日期 开 高 低 收 成交量 成交额`，日期支持
`YYYY-MM-DD` / `YYYY/MM/DD` / `YYYYMMDD`。

> 可直接参考工程内样例：`samples/day/sh#600354.txt`，试跑：
> `python run_import.py --freq daily --source file --dir samples\day --dry-run`

---

## 5. 回测模型

### 5.1 信号与因子

信号池 `data/sig_all_horizons.pkl`（由本工程 `rebuild_signals.py` + `enrich_signals.py`
在当前数据表 `backward_tdx_daily` 上重扫并富化生成，流程见 §10），
关键因子：

| 因子 | 含义 | 用途 |
|------|------|------|
| `nmc` | 流通市值（亿元） | 小市值过滤 |
| `vol60` | 60 日年化波动率 | 趋势强弱（F1） |
| `mom60` | 60 日动量 | 趋势方向（F2） |
| `mkt_dev` | 沪深300 相对 MA60 偏离 | 择时 |
| `pb_t` | 市净率 | 低估值过滤 |
| `f20/f30/f40/f60` | 信号级远期收益 | 分层统计 |

### 5.2 六个对比组合

| 键 | 名称 | 过滤条件 |
|----|------|----------|
| `ALL` | 全部三因子信号 | 不筛（基准对照） |
| `A` | 优选组合A | `nmc<40` & `vol60<0.45` & `|mom60|<0.10` |
| **`S1`** | **最优组合** | `nmc<20` & `0.25≤vol60<0.35` & `−0.10≤mom60<0` |
| `S2` | S1 放宽动量 | `nmc<20` & `0.25≤vol60<0.35` & `mom60<0` |
| `S3` | S1 + 择时 | S1 且 `mkt_dev>0` |
| `S4` | S1 + 低估值 | S1 且 `pb_t<2` |

### 5.3 回测口径（关键约定）

| 项目 | 约定 |
|------|------|
| 信号来源 | `data/sig_all_horizons.pkl`（工程自带，由本工程重扫生成） |
| 价格来源 | MySQL `TABLE_BACKWARD_DAILY` 后复权（open/close） |
| 建仓 | 信号日 **T 收盘价**买入；持有期内**去重**，期满后下一个信号日才可再建 |
| 平仓 | **T+N 个交易日收盘价**卖出（停牌自动顺延到下一有报价日） |
| 权重 | 每个交易日对所有在持标的**等权**（日度再平衡） |
| 成本 | 新开 n 只 / 平仓 m 只 / 总持仓 h 只（等权 1/h）→ 当日成本率 `(n+m)/h × cost/2` |
| 基准 | 沪深300 同期买入持有 |
| 年化天数 | 252 |
| 默认区间 | `settings.DEF_START`（默认 2015-09-01，对齐新表全历史）~ 价格数据末日 |

### 5.4 输出产物

| 产物 | 路径 | 内容 |
|------|------|------|
| Excel（8 Sheet） | `output/three_factor_best_backtest_<时间戳>.xlsx` | 见下 |
| 净值 CSV | 同名 `_nav.csv` | 日频净值 + 持仓只数 |
| 逐笔 CSV | 同名 `_trades.csv` | S1 去重后逐笔明细 |
| 净值图 | `output/charts/三因子最优组合回测.png` | 6 面板 |
| 价格缓存 | `data/_cache/bt_daily_px.parquet` | 后复权价格（约 28 MB） |

Excel Sheet：`回测说明 / 绩效总览 / 净值曲线 / 年度收益 / 月度收益 / 交易明细 / 参数敏感性 / 因子分层`

---

## 6. 关键结果（S1 · 持有 20 日，双边成本 0.20%）

| 指标 | 数值 |
|------|------|
| 原始信号 → 去重交易 | 240 条 → **115 笔** |
| 总收益 | **+77.41%** |
| 年化收益 | **+11.30%** |
| 最大回撤 | **−21.34%** |
| 夏普 | **0.72** |
| 资金利用率 | 33.7%（平均持仓 5.27 只） |
| 逐笔毛收益 | 均值 +5.97%、胜率 74.8%、盈亏比 2.64 |

持有期对比：**30 日最佳**（年化 18.26% / 回撤 −22.37% / 夏普 0.90 / 利用率 43.1%），
60 日回撤骤增至 −53.82%。年度上 S1 六年全为正（最差 2022 −1.22%）。

> 核心结论：`ALL`（不过滤）几乎复制沪深300，说明三因子**整体无 alpha**；
> alpha 全部来自「小市值 `nmc<20亿` + `vol60 25~35%` + `mom60<0`」三重过滤。

---

## 7. 已知局限

1. **样本内回测**，S1 经多重比较筛选，存在选择偏差 → 以「参数敏感性」表稳健性为准。
2. 等权日度组合、空仓日收益记 0 → 年化/夏普反映「资金实际在策略里的表现」，
   而非仅持仓日胜率；资金利用率低（约 34%）。
3. 未计冲击成本与涨跌停不可成交。
4. `ALL` 组合几乎复制沪深300，仅作对照，**不可直接复刻**。
5. 信号池可由本工程重建：`rebuild_signals.py` + `enrich_signals.py`（见 §10）；
   但富化层市值采用「快照折算」，长历史下存在偏差（§10.5）。

---

## 8. 验证记录

* 回测复现：与主工程 `analyzers/three_factor_best_backtest.py` 产物**逐 Sheet 一致**
  （绩效总览 25×24 / 净值 1298×11 / 交易明细 115×11 逐笔 / 参数敏感性 13×11 /
  因子分层 16×9 全部数值相同）。
* `回测说明` Sheet 由 26 行增至 27 行（新增第 5 条口径提示）。
* 交易明细股票代码保持文本格式，前导零保留（如 `001368`）。
* 导入器自检：`--freq daily --limit 5 --dry-run` 连接 baostock 正常；
  文件通道 TDX 样例解析正常。

---

## 9. 与主工程的对应关系

| 本工程 | 迁移来源（主工程） |
|--------|--------------------|
| `backtest_model/*` | `analyzers/three_factor_best_backtest.py` |
| `importers/daily.py` | `data/data_backward_adjust_collection.py` |
| `importers/monthly.py` | `data/data_monthly_import.py` |
| `config.py` | 主工程 `config.py`（裁剪为仅日线/月线） |
| `data/*.pkl` | `analysis_results/_seg_cache/` |

---

## 10. 数据源切换与信号池重建（`backward_tdx_daily`）

### 10.1 背景

`data/sig_all_horizons.pkl` 原先直接沿用主工程 `F:\quantTrade` 用
`history_days=1500` 的一次滚动回测产物，只覆盖 2022-01-04~2026-08-06。
新数据表 `backward_tdx_daily` 已覆盖 **2015-09-01 ~ 2026-10-09**（约 11.1 年），
因此本工程改为**自己重建信号池**，并把价格源统一切到该表。

### 10.2 两步流程

| 步骤 | 命令 | 产物 |
|------|------|------|
| ① 信号重扫 | `python rebuild_signals.py --workers 10 --out output\signals_rebuilt_full.csv` | 全历史三因子买点 + `return_20/30/40/60d`（缺 60 根前瞻K线的尾段不出信号） |
| ② 富化数据刷新 | `python run_update_factors.py --if-stale` | 富化库三表：`factor_spot` / `factor_qfq_daily` / `factor_index_daily`（每周一次，见 §12） |
| ③ 因子富化 | `python enrich_signals.py --signals output\signals_rebuilt_full.csv` | `data/sig_all_horizons.pkl`（列结构不变；旧池自动备份） |
| ④ 价格预热 | `python _prepull_px.py`（可选） | `data/_cache/bt_daily_px.parquet` |
| ⑤ 跑回测 | `python run_backtest.py --chart` | Excel / 净值图 / 逐笔（§5.4） |

> ① 实测 3,307 只 / 42,875 条信号，10 进程约 43 分钟（每批 8 只落一个断点文件）；
> ④ 实测 718 万行 / 802 秒。③ 完成后回测会**直接命中** ④ 的缓存，
> 无需 `--refresh`（`--refresh` 仅在数据表更新后需要）。
>
> ② 可以省一次外网抓取：第一次跑完三表后，③ 只需读库；
> 库表缺票时自动回退外网（`--from-network` 可强制只走外网）。

`rebuild_signals.py` **默认**复用本工程 `backtest_model.factors` 的三因子
判定模型（F1 趋势强弱 / F2 趋势方向 / F3 多空力量，指标 MA7 / MA21 /
MACD(30,89,9)，参数见 `config/signal.json`），与主工程
`analyzers/three_factor_backtest.py` 口径**逐位一致**（对拍见 §11.3）；
加 `--legacy` 可切回主工程分析器（严格对拍 / 回退）。

### 10.3 为什么可以做严格对拍

扫描步进为**滚动 360 根窗口**：第 i 个交易日只把 `df[i-359 : i+1]` 送
`analyze_pattern()`。因此

* 信号**只取决于该 360 根窗口内的数据**，与 `history_days` 无关；
* 扩大 `history_days` 只是延长可扫描的日期区间，**不会改变重叠区间内的既有信号**。

于是「新旧信号池在重叠区间完全一致」可以作为重建正确性的硬校验
（`rebuild_signals.py --check-parity`，明细用 `python _parity_report.py`）。

实测对拍（新池 vs 旧池备份 `data/sig_all_horizons.pre_tdx_20261011.pkl`）：

| 指标 | 数值 |
|------|------|
| 旧池 / 新池 | 24,054 条 / 3,102 只（2022-01-04 ~ 2026-08-06） ↔ 42,875 条 / 3,149 只（2017-02-28 ~ 2026-07-09） |
| 交集（股票+日期完全一致） | **23,437** 条 |
| 重叠窗口内 新多出 | **172** 条（占窗口内 23,609 条的 0.73%，涉及 101 只；2022 年占 124 条） |
| 旧有但新无 | **617** 条（其中 **577** 条为 `2026-07-10` 之后的尾段，新池因缺 60 根前瞻K线不产生） |

差异归因：

* **尾段 577 条**：新扫描末端 2026-07-09 之后无法计算 `return_60d`，属预期；
* **新池起点附近 124 条**（2022-01-05/06/11 等）：旧池扫描起点处的窗口预热边界效应；
* **其余零星几十条**：两表后复权序列在个别权息点上的微差导致指标恰好跨阈值。

即两池**重合度 99.3%**，可认为数据源切换未改变信号定义。

### 10.4 工程细节

| 项 | 处理 |
|----|------|
| 模块同名冲突 | 主工程与本工程都有 `config.py` → 用 `importlib.util.spec_from_file_location('abm_config', …)` 独立加载本工程配置 |
| `.env` 覆盖 | 子进程通过 `os.environ['TABLE_BACKWARD_DAILY']` 传递表名，避免被主工程 `.env` 覆盖 |
| 断点续跑 | 每批（默认 8 只）结果落 `output/_sig_ckpt/b####.pkl`，重跑自动跳过已完成批次 |
| 长历史指数 | `data/idx_000300.pkl` 重建为新浪 **2,800 根**（2015-04-01 ~ 2026-10-09），供 `mkt_dev/mkt_mom60` 使用；重建用 `python run_update_factors.py --only index`（原一次性脚本 `_build_idx.py` 已归档到 `temp/`） |
| 长历史前复权日线 | `data/_cache/kline_qfq_long.pkl`（3,307 只 × 2,800 根，可断点续抓） |

### 10.5 已知偏差（重要）

富化阶段的**市值 / 流通市值 / PB 用「当前快照 × 前复权价(t)/前复权价(now)」折算**，
隐含「信号日至今股本未变」。抽样核对（真值 = `不复权收盘价 × 当期流通股本`）：

| 股票 | 2017—2022 折算倍数 | 说明 |
|------|--------------------|------|
| 600519 贵州茅台 | 1.00 | 股本稳定，误差可忽略 |
| 300106 西部创业 | 1.00 ~ 1.30 | 基本可用 |
| 002049 紫光国微 | 1.39 ~ 1.41 | 送转/增发导致高估约 40% |
| 000001 平安银行 | 1.27（2017）→ 1.03（2025） | 早年高估较多 |

即 **2017 年以后误差多在 1.4 倍以内**，对 `nmc<20亿` / `nmc<40亿` 这类阈值过滤
存在少量误判；但该折算口径与旧版（2022 年起）回测**完全一致**，跨版本可比。
若需要精确市值，需另行抓取历史股本并替换 `nmc` 列。

### 10.6 长任务怎么跑（避免「轮询死循环」）

重建 / 富化 / 回测都是分钟级任务。**不要反复读取同一个日志文件看进度**，
用 `_run_wait.py` 把「启动 + 等待 + 回吐日志」收敛成一次调用：

```bat
:: 后台起命令并阻塞等待，结束即打印退出码 + 日志尾部
python _run_wait.py --log output\_enrich.log --timeout 5400 -- ^
    python -u enrich_signals.py --signals output\signals_rebuilt_full.csv

:: 只看某个已在跑（或被中断）的任务的日志尾部，不重启任务
python _run_wait.py --log output\_sig_build.log --attach
```

要点：

| 项 | 说明 |
|----|------|
| 分离进程 | 用 `DETACHED_PROCESS` 启动，外层 shell 被中断也不会带走子任务 |
| 日志编码 | 脚本固定 `PYTHONIOENCODING=utf-8`，避免 PowerShell `>` 默认写 UTF-16 导致乱码 |
| 断点 | 信号重建自带 `output/_sig_ckpt/b####.pkl`，中断后重跑自动续 |
| 依赖 | `--chart` 需要 `matplotlib`（见 `requirements.txt`，缺失时 Excel 仍会正常产出） |

本次全流程实测产物（2026-10-11）：

| 产物 | 路径 | 规模 |
|------|------|------|
| 重建信号 CSV | `output/signals_rebuilt_full.csv` | 42,875 行（5.1 MB） |
| 信号池 pkl | `data/sig_all_horizons.pkl` | 42,875 × 33（11.7 MB） |
| 价格缓存 | `data/_cache/bt_daily_px.parquet` | 7,183,946 行 / 3,307 只 |
| 回测 Excel | `output/three_factor_best_backtest_<时间戳>.xlsx` | 8 个 Sheet |
| 净值图 | `output/charts/三因子最优组合回测.png` | 6 面板 |

> 最近一次实测（2026-10-11 22:41，价格强制重拉后）：
> `three_factor_best_backtest_20261011_224127.xlsx`（166 KB），
> 与重拉前结果逐项一致 —— ALL/H20 年化 1.89%、回撤 -45.04%、夏普 0.20；
> S1/H20 6.51% / -35.00% / 0.49（103 笔、胜率 65%）；S3/H20 6.51% / -16.88% / 0.56。
>
> 数据是否到期需重拉，用 `python _check_fresh.py` 一键体检
> （对比 DB 表 / 价格缓存 / 信号池 / 指数的最新日期）。

---

## 11. 因子插件化（配置驱动，无需改代码）

本工程把「因子」拆成两类，**都做成可插拔插件**，新增 / 替换 / 调参只需改配置：

| 类别 | 作用 | 定义位置 | 配置 |
|------|------|----------|------|
| **数值因子**（FeatureFactor） | 回测层筛选（组合 / 敏感性 / 分层） | `factors/base.py` + `builtin.py` | `config/factors.json` |
| **判定闸门**（GateFactor） | 信号层判定（F1/F2/F3） | `factors/gates/` | `config/signal.json` |

### 11.1 数值因子（回测层）

* **改阈值 / 组合 / 分层**：直接编辑 `config/factors.json` 的 `combos` /
  `sensitivity` / `layers` 段，`run_backtest.py` 立即生效。
* **新增数值因子**：在 `factors/builtin.py` 追加一行
  `register_feature(FeatureFactor('turnover', '换手率', '20 日换手率'))`，
  信号池含该列即可在组合里引用 `{"factor": "turnover", "op": ">", "value": 2}`。
* 数值因子会**自动**纳入 `data.py` 的数值化列与敏感性 / 分层，无需改其它代码。

### 11.2 判定闸门（信号层 F1/F2/F3）

* **调 F1/F2/F3 参数**：编辑 `config/signal.json` 的 `gates[].params`
  （如 `f1_close_to_ma21_min`、`f2_above_ma_days`、`f3_red_bar_days`）。
* **新增闸门**：在 `factors/gates/` 里用 `@register_gate` 定义
  `GateFactor` 子类（实现 `check(df) -> (bool, detail)`），再到
  `config/signal.json` 的 `gates` 段加
  `{"key": "F4", "enabled": true, "params": {...}}`；
  `ThreeFactorModel` / 扫描 / 重建逻辑**无需改动**。
* **指标参数**（MACD 30/89/9、MA7/MA21）在 `config/signal.json` 的
  `indicators` 段。

### 11.3 对拍（硬校验）

`rebuild_signals.py` 默认走本地闸门模型，`--legacy` 走主工程分析器；
可对同一批股票分别重建并 `--check-parity` 逐条比对。本地闸门逻辑已用
`python _gate_parity.py` 对 800 组随机行情窗口对拍主工程分析器，
F1 / F2 / F3 判定各 800/800 完全一致。



---

## 12. 富化数据入库存 + 每周自动更新（`factors/enrichers/`）

原 `enrich_signals.py` 直接依赖外部工程
`F:\quantTrade\analyzers\three_factor_segment_analysis.py` 抓取「行业 / 市值 /
PB / 前复权日线 / vol60」，既不可控也无法复用。§12 把它**整体迁入本工程**，
并把抓取结果**沉淀到自己的 MySQL 三表**，由计划任务**每周刷新一次**。

### 12.1 三类插件各司其职

| 类别 | 作用 | 定义位置 | 配置 |
|------|------|----------|------|
| **数值因子** FeatureFactor | 回测层筛选（组合 / 敏感性 / 分层） | `factors/base.py` + `builtin.py` | `config/factors.json` |
| **判定闸门** GateFactor | 信号层判定（F1/F2/F3） | `factors/gates/` | `config/signal.json` |
| **富化器** Enricher | 数据层：为信号补上下文列 | `factors/enrichers/` | `config/enrichers.json` |

内置富化器（`factors/enrichers/builtin.py`）：

| key | 产出列 | 数据来源 |
|-----|--------|----------|
| `board` | `board` | 代码前缀（本地） |
| `industry` | `industry` | `factor_spot.industry`（东财 F10，回退新浪） |
| `market_cap` | `mv_total` / `nmc` / `pb_t` / `pe_now` / `price` | `factor_spot` 快照 × 前复权价折算系数 |
| `volatility` | `vol60` / `mom60` | `factor_qfq_daily` |
| `market_regime` | `mkt_dev` / `mkt_mom60` | 沪深300（`data/idx_000300.pkl`） |
| `sig_count` | `sig_count` | 信号表自身 |
| `year` | `year` | 信号日期 |

新增富化器（无需改富化 / 回测代码）：

```python
# backtest_model/factors/enrichers/builtin.py（或自定义模块）
from backtest_model.factors.enrichers import Enricher, register_enricher
import numpy as np

@register_enricher
class TurnoverEnricher(Enricher):
    key, label, columns = 'turnover', '换手率', 'turnover'
    def enrich(self, ctx, code, grp, out):
        out['turnover'] = np.full(len(grp), np.nan)
```

再往 `config/enrichers.json` 的 `enrichers` 段加
`{"key": "turnover", "enabled": true}` 即可（帧级富化器把 `scope = 'frame'`
并实现 `enrich_frame(ctx, sigs, feat)`）。

### 12.2 富化库三表

表名取自 `config.py`（`TABLE_FACTOR_SPOT` / `TABLE_FACTOR_QFQ_DAILY` /
`TABLE_FACTOR_INDEX_DAILY`，可被 `.env` 覆盖），由 `FactorStore.ensure_tables()`
幂等建表。

| 表 | 粒度 | 列 |
|----|------|----|
| `factor_spot` | 每股一行（快照） | `stock_code, stock_name, industry, board, pe, pb, mktcap(万元), nmc(万元), price, snapshot_date` |
| `factor_qfq_daily` | 每股每日一行 | `stock_code, trade_date, close_price(前复权), vol60, mom60` |
| `factor_index_daily` | 指数每日一行 | `index_code, trade_date, close_price` |

写入一律 `INSERT … ON DUPLICATE KEY UPDATE`（幂等，可重复跑）。

> **精度约定（关键）**：新浪日线收盘原为 `float32`，入库前 `float(np.float32(v))`、
> 回读后再 `astype(np.float32)`，与旧脚本口径**逐位一致**，
> 保证 `sig_all_horizons.pkl` 不因落库而漂移（对拍见 §12.4）。
>
> **前复权随权息整体平移**：每次刷新 `factor_qfq_daily` 都是**全量重写**，
> 这样「价(t)/价(now)」折算系数始终与抓取当日口径一致。

### 12.3 每周刷新 + 计划任务

```bat
:: ① 每周刷新富化库（外网 → MySQL）
python run_update_factors.py --if-stale        :: 距上次 < 7 天则自动跳过

:: ② 只刷某一部分（快照秒级 / 日线较慢 / 指数）
python run_update_factors.py --only spot
python run_update_factors.py --only kline
python run_update_factors.py --only index --no-index-pkl

:: ③ 看库表现状 / 上次刷新时间
python run_update_factors.py --status

:: ④ 富化（读库；缺票自动回退外网）
python enrich_signals.py --signals output\signals_rebuilt_full.csv
```

注册 Windows 计划任务（每周一 02:00，管理员执行一次）：

```bat
schtasks /Create /TN "ABM_UpdateFactors" /SC WEEKLY /D MON /ST 02:00 ^
    /TR "cmd /c cd /d F:\ai_backtest_model && scripts\update_factors_weekly.bat"
schtasks /Run    /TN "ABM_UpdateFactors"      :: 立即手动跑一次
schtasks /Delete /TN "ABM_UpdateFactors" /F   :: 删除
```

`scripts/update_factors_weekly.bat` 会 `cd` 到工程根、追加日志到
`logs/update_factors_weekly.log`，并靠 `--if-stale` 保证「一周只真刷一次」
（多跑也只是秒级跳过）。刷新时间戳写在
`data/_cache/enrich/last_update.json`。

常用参数：`--only` / `--universe db|spot` / `--limit N`（快速验证）/
`--workers` / `--datalen` / `--batch-size` / `--refresh`（忽略本地 pkl 重抓）/
`--status` / `--if-stale` / `--no-index-pkl`。

### 12.4 对拍（硬校验）

| 脚本 | 校验内容 | 实测 |
|------|----------|------|
| `python _enrich_parity.py` | 旧实现（外部三因子脚本）vs 新实现（本地 `factors/enrichers`）vs 已落盘 `sig_all_horizons.pkl`，同输入逐列比对 | 42,875 行 × 33 列 **逐列完全一致**（两者均通过） |
| `python _store_parity.py` | 富化库落库 → 回读精度（float32 往返）+ 库表路径富化逐列一致 + `use_stored_metrics` 快路径 | 回读不一致 **0**；富化逐列一致；快路径 `max|diff| = 0` |

`_enrich_parity.py` 完全离线（复用 `analysis_results/_seg_cache` 快照 / 行业、
`data/_cache/kline_qfq_long.pkl`、`data/idx_000300.pkl` 与最新 signals CSV），
因此可以随时重跑；`_store_parity.py` 会写入 40 只测试股票后**自动清理**。

### 12.5 已知限制

* 市值 / PB 仍是「当前快照 × 前复权价比」折算，隐含「信号日至今股本未变」
  （§10.5），误差与旧版完全一致，跨版本可比。
* `pe_now` 无法可靠折算，只代表**当前**估值，仅用于刻画估值偏好。
* 富化库首次使用需先跑一次 `run_update_factors.py`（约 3,300 只 × 2,800 根，
  抓取 + 写库数十万行级），之后每周增量刷新即可。

