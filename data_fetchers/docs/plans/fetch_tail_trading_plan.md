# 尾盘数据拉取脚本实现计划

> 版本: v1.0
> 创建时间: 2026-05-29 11:30 北京时间
> 作者: 云瑶

---

## 背景

用户需要拉取尾盘（14:30-15:00）的5分钟K线数据，用于构建尾盘因子。
- 数据源：东方财富5分钟K线 API
- 数据粒度：5分钟K线，尾盘时段共7根（14:30-15:00）
- 覆盖股票：约3000支主板股票
- 模式：全量模式（初始化时拉取历史12天）+ 增量模式（每日更新最新一天）

---

## 设计决策

### 1. 新建脚本 vs 融合现有脚本

**决策：新建 `fetch_tail_trading.py`**

理由：
1. 数据粒度本质不同（分钟级 vs 日线级）
2. API源不同（东财5分钟K线 vs baostock日线）
3. 遵循 MODULE.md 约束 #1 命名规范 `fetch_<数据源>.py`
4. 模块职责单一，便于独立测试维护

### 2. 输出路径

**决策：`data_fetchers/result/tail_trading_data.json.gz`**

遵循 MODULE.md 约束 #2（输出到 result 目录）

### 3. 公共模块复用

**复用以下公共模块**（遵循 MODULE.md 约束 #4）：

| 模块 | 复用函数 | 用途 |
|------|---------|------|
| http_client.py | `eastmoney_session` | HTTP Session 管理 |
| http_client.py | `request_with_retry` | 带重试的请求 |
| http_client.py | `DEFAULT_EASTMONEY_HEADERS` | 东财请求头 |
| cache_manager.py | `read_cache/write_cache` | 缓存读写 |
| stock_utils.py | `load_main_board_stock_list` | 加载主板股票列表 |
| stock_utils.py | `is_main_board_stock` | 判断主板股票 |
| stock_utils.py | `EXCLUDED_NAME_KEYWORDS` | ST 股票关键词 |
| paths.py | `get_module_result_dir` | 获取 result 目录 |

---

## 实现任务清单

### Phase 1: 基础框架（10分钟）

**Task 1.1: 创建脚本骨架**
- 文件路径：`data_fetchers/fetch_tail_trading.py`
- 导入公共模块（遵循 MODULE.md 约束 #51：导入在模块顶部）
- 定义模块级常量（遵循 MODULE.md 约束 #16：version 字段提取为常量）
- 配置 logger（使用 `setup_logger`）

**Task 1.2: 定义输出结构**
```json
{
  "meta": {
    "generated_at": "2026-05-29T11:30:00",
    "source": "eastmoney_5min",
    "n_days": 12,
    "n_assets": 3000,
    "date_range": {
      "start": "2026-05-15",
      "end": "2026-05-28"
    },
    "last_updated": "2026-05-29 11:30:00",
    "version": "1.0"
  },
  "data": [
    {
      "date": "2026-05-28",
      "asset": "000001",
      "tail_volume": 1234567,
      "tail_volume_pct": 0.15,
      "tail_high": 10.50,
      "tail_low": 10.30,
      "tail_close": 10.45
    }
  ]
}
```

### Phase 2: 数据拉取逻辑（15分钟）

**Task 2.1: 实现单股尾盘数据拉取**
- 函数：`fetch_tail_trading_for_stock(code, logger)`
- API：`http://push2his.eastmoney.com/api/qt/stock/kline/get`
- 参数：`secid=市场.代码`（深市0，沪市1），`klt=5`（5分钟K线），`lmt=500`
- 过滤尾盘时段：14:30-15:00（共7根K线）
- 返回：`tail_volume`, `tail_volume_pct`, `tail_high`, `tail_low`, `tail_close`

**Task 2.2: 实现批量拉取**
- 函数：`fetch_tail_trading_batch(stock_codes, full=False, logger)`
- 全量模式：拉取历史12天数据（每股1次请求）
- 增量模式：拉取最新一天数据（每股1次请求）
- 限流：200ms 间隔（遵循 MODULE.md 约束 #78：session 资源管理）
- 进度日志：每100股打印一次

### Phase 3: 缓存管理（10分钟）

**Task 3.1: 实现缓存加载**
- 函数：`load_cache(logger)`
- 使用 `read_cache` 读取 `tail_trading_data.json.gz`
- 返回：`dict | None`

**Task 3.2: 实现缓存保存**
- 函数：`save_cache(data, logger)`
- 使用 `write_cache` 写入 `tail_trading_data.json.gz`
- 遵循 MODULE.md 约束 #80：使用 tempfile

**Task 3.3: 实现合并去重**
- 函数：`merge_records(existing_data, new_records, source, logger)`
- 去重策略：`(date, asset)` 作为 key
- 数据源合并逻辑：遵循 MODULE.md 约束 #93

### Phase 4: 主函数和 CLI（5分钟）

**Task 4.1: 实现主函数**
- 函数：`main(full=False, logger_arg=None)`
- 返回：`bool`（遵循 MODULE.md 约束 #33）
- 流程：load_cache → fetch_batch → merge_records → save_cache

**Task 4.2: 实现 CLI 参数**
- `--full`：全量拉取（不使用缓存）
- `--max-stocks`：限制股票数（用于测试）
- `--test`：测试模式（只拉取10支股票）

---

## 验证检查清单

### Stage 1: Spec Compliance

遵循 MODULE.md 约束：

| 约束 # | 检查项 | 状态 |
|--------|--------|------|
| 1 | 脚本命名：`fetch_tail_trading.py` | ✓ |
| 2 | 输出到 result 目录 | ✓ |
| 4 | 公共模块复用 | ✓ |
| 7 | 日志输出到 logs 目录 | ✓ |
| 16 | version 字段提取为常量 | ✓ |
| 17 | datetime.now() 只调用一次 | ✓ |
| 33 | 函数签名与调用一致 | ✓ |
| 51 | 导入在模块顶部 | ✓ |
| 53 | __all__ 导出列表 | ✓ |
| 77 | logger 参数命名规范 | ✓ |
| 78 | session 资源管理 | ✓ |

### Stage 2: Code Quality

| 检查项 | 状态 |
|--------|------|
| 导入顺序 PEP 8 | ✓ |
| 类型注解完整 | ✓ |
| docstring 完整 | ✓ |
| 异常处理精确 | ✓ |

---

## 预期输出

### 文件清单

| 文件 | 操作 |
|------|------|
| `data_fetchers/fetch_tail_trading.py` | 新建 |
| `data_fetchers/logs/fetch_tail_trading_YYYY-MM-DD.log` | 自动生成 |
| `data_fetchers/result/tail_trading_data.json.gz` | 自动生成 |

### 预期数据量

- 全量模式：3000股 × 12天 = 36000条记录
- 增量模式：3000股 × 1天 = 3000条记录
- 请求次数：约3000次（全量）或3000次（增量）

---

## 风险和对策

### 风险 1：API 限流

- **对策**：200ms 间隔，3000股约10分钟完成
- **应急**：429 错误时暂停5分钟

### 风险 2：股票列表未加载

- **对策**：依赖 `load_main_board_stock_list()`，失败时抛异常

### 风险 3：数据格式不一致

- **对策**：防御性编程，使用 `.get()` 获取字段

---

## 后续工作

1. 创建测试文件：`test_cases/test_fetch_tail_trading.py`
2. 创建流程文档：`docs/fetch_tail_trading_flow.md`
3. 验证实际数据输出

---

*计划状态：待用户确认*