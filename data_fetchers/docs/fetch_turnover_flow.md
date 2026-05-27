# fetch_turnover 流程文档

> 版本: v2.11
> 创建时间: 2026-05-27 19:00 北京时间
> 更新时间: 2026-05-27 19:00 北京时间

---

## 概述

换手率数据拉取脚本，包含两个数据源：
1. 东财千股千评 API（fetch_turnover_rate_eastmoney）- 实时数据
2. baostock 数据源（fetch_turnover_rate_baostock）- 历史数据

**缓存路径：** `cache/factor_data/turnover_rate_data.json.gz`

---

## 目录

1. [数据结构](#数据结构)
2. [核心流程](#核心流程)
3. [函数接口](#函数接口)
4. [CLI 参数](#cli-参数)
5. [错误处理](#错误处理)
6. [版本历史](#版本历史)

---

## 数据结构

### 输出结构

```json
{
  "meta": {
    "generated_at": "2026-05-27T19:00:00",
    "source": "eastmoney",
    "n_days": 1,
    "n_assets": 2500,
    "date_range": {
      "start": "2026-05-26",
      "end": "2026-05-27"
    },
    "last_updated": "2026-05-27 19:00:00",
    "version": "2.11"
  },
  "data": [
    {
      "date": "2026-05-27",
      "asset": "600000",
      "turnover_rate": 2.5,
      "name": "浦发银行"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|-----|------|------|
| meta.generated_at | string | 数据生成时间（ISO格式） |
| meta.source | string | 数据源（eastmoney/baostock/mixed） |
| meta.n_days | int | 交易日数 |
| meta.n_assets | int | 股票数量 |
| meta.date_range.start | string | 日期范围起始 |
| meta.date_range.end | string | 日期范围结束 |
| meta.last_updated | string | 最后更新时间 |
| meta.version | string | 版本号 |
| data[].date | string | 交易日期 |
| data[].asset | string | 股票代码 |
| data[].turnover_rate | float | 换手率（%） |
| data[].name | string | 股票名称（东财数据源有） |

---

## 核心流程

### 东财数据源流程

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 加载现有缓存                                         │
│  load_cache() → existing_data                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 拉取新数据                                           │
│  fetch_turnover_rate_eastmoney() → new_records              │
│  - 分页获取（pageSize=500）                                   │
│  - 主板股票过滤（60/00开头）                                   │
│  - ST/退市股票剔除                                            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 合并去重                                             │
│  merge_records(existing_data, new_records) → merged_data    │
│  - (date, asset) 作为唯一键                                   │
│  - 数据源标记（eastmoney/baostock/mixed）                     │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 保存缓存                                             │
│  save_cache(merged_data)                                    │
│  - tempfile 原子写入                                         │
│  - gzip 压缩                                                 │
└─────────────────────────────────────────────────────────────┘
```

### baostock 数据源流程

```
┌─────────────────────────────────────────────────────────────┐
│  Step 0: 登录 baostock                                        │
│  bs.login() → lg                                             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 加载主板股票列表                                      │
│  load_stock_list() → all_stocks                             │
│  - 从 cache/stock_list.json 读取                             │
│  - 主板股票过滤                                               │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 加载现有缓存                                          │
│  load_cache() → existing_stocks（增量模式跳过已有股票）        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 计算日期范围                                          │
│  end_date = datetime.now()                                   │
│  start_date = end_date - timedelta(days=n_days * 1.5)       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 串行拉取                                              │
│  for stock in all_stocks:                                    │
│    - 跳过已有股票（增量模式）                                   │
│    - query_history_k_data_plus()                             │
│    - 连续失败检测 + 暂停机制                                   │
│    - 时间估算 + 进度显示                                       │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 5: 合并并保存                                            │
│  merge_records() → save_cache()                             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 6: 登出 baostock                                        │
│  bs.logout()                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 函数接口

### 公共函数（__all__ 导出）

| 函数 | 返回类型 | 说明 |
|-----|---------|------|
| `load_cache(logger_arg)` | `dict[str, Any] | None` | 加载现有缓存 |
| `save_cache(data, logger_arg)` | `None` | 保存缓存文件 |
| `get_cached_turnover_codes(logger_arg)` | `set[str]` | 获取缓存的股票代码集合 |
| `fetch_turnover_rate_eastmoney(logger_arg)` | `list[dict[str, Any]]` | 东财数据源拉取 |
| `fetch_turnover_rate_baostock(n_days, max_stocks, full, logger_arg)` | `bool` | baostock 数据源拉取 |
| `main(logger_arg)` | `bool` | 主函数（东财版本） |

### 内部函数

| 函数 | 说明 |
|-----|------|
| `is_main_board_stock(code, name)` | 主板股票判断 |
| `load_stock_list()` | 加载主板股票列表 |
| `get_baostock_code(stock_code)` | 转换为 baostock 格式 |
| `fetch_stock_history_baostock(...)` | 拉取单只股票历史数据 |
| `get_existing_stocks(cache_data)` | 获取已有数据的股票代码 |
| `merge_records(existing_data, new_records, source, logger_arg)` | 合并数据 |
| `format_time(seconds)` | 格式化时间显示 |

---

## CLI 参数

| 参数 | 默认值 | 说明 |
|-----|-------|------|
| `--baostock` | False | 使用 baostock 数据源 |
| `--full` | False | 全量拉取（不使用缓存） |
| `--n-days` | 500 | 历史天数（baostock） |
| `--max-stocks` | 0 | 最大股票数（baostock，0为不限制） |

### 使用示例

```bash
# 东财数据源（默认）
python data_fetchers/fetch_turnover.py

# baostock 数据源
python data_fetchers/fetch_turnover.py --baostock

# baostock 全量拉取 100 天
python data_fetchers/fetch_turnover.py --baostock --full --n-days 100
```

---

## 错误处理

### CLI 异常处理（v2.11）

```python
try:
    if args.baostock:
        success = fetch_turnover_rate_baostock(...)
    else:
        success = main(...)
    sys.exit(0 if success else 1)
except Exception as e:
    cli_logger.error(f"执行失败: [{type(e).__name__}]: {e}")
    sys.exit(1)
```

### load_cache 类型校验（v2.11）

```python
if not isinstance(data, dict):
    _logger.warning(f"[缓存] JSON 类型异常: 期望 dict，实际 {type(data).__name__}")
    return None
```

### 重试机制

- 东财 API：最多重试 3 次，等待时间递增（2s → 4s → 6s）
- baostock：连续失败 5 次暂停 30 秒

---

## 版本历史

| 版本 | 日期 | 改进内容 |
|-----|------|---------|
| v2.11 | 2026-05-27 | 类型系统规范化：CLI异常处理、load_cache类型校验、typing内置泛型、ST_PREFIXES注释修正 |
| v2.10 | 2026-05-27 | tempfile修复：同一with块内写入 |
| v2.9 | 2026-05-27 | total_pages=0边界处理+冗余常量删除 |
| v2.8 | 2026-05-27 | logger初始化统一+跳过日志粒度优化 |
| v2.7 | 2026-05-27 | 时间估算逻辑+数据源合并逻辑 |
| v2.6 | 2026-05-27 | doctest修复+logger赋值统一 |
| v2.5 | 2026-05-27 | ST_PREFIXES元组优化+优先级语义+边界处理 |
| v2.4 | 2026-05-27 | 时间统计修复+空数据处理+数据源保留 |
| v2.3 | 2026-05-27 | 公共函数创建+类型注解+文档字符串 |
| v2.2 | 2026-05-27 | ST_PREFIXES常量+ST检测修复+__all__导出+CLI简化 |
| v2.1 | 2026-05-27 | logger参数化+tempfile+session资源管理+print迁移 |
| v2.0 | 2026-05-27 | PEP8导入顺序+版本号常量+datetime统一 |
| v1.2 | 2026-04-08 | 初始版本 |

---

## 相关文件

| 文件 | 说明 |
|-----|------|
| `data_fetchers/fetch_turnover.py` | 主脚本 |
| `cache/factor_data/turnover_rate_data.json.gz` | 缓存文件 |
| `cache/stock_list.json` | 股票列表（baostock依赖） |
| `data_fetchers/logs/fetch_turnover_*.log` | 日志文件 |

---

## 开发后动作

```
□ 修改代码后运行导入测试：python -c "from data_fetchers.fetch_turnover import load_cache, save_cache"
□ 检查缓存文件完整性：gzip -dc cache/factor_data/turnover_rate_data.json.gz | python -m json.tool
□ 更新版本历史和版本号
□ 检查 MODULE.md 约束编号是否需要新增
□ 检查流程文档时间标注是否同步更新
```

---

*最后更新: 2026-05-27 19:00 北京时间*