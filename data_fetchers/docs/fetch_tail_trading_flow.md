# 尾盘数据拉取流程文档

> 版本: v2.2
> 创建时间: 2026-05-29 11:17 北京时间
> 更新时间: 2026-05-29 18:00 北京时间

## 概述

尾盘数据拉取脚本 (`fetch_tail_trading.py`) 从东方财富5分钟K线API获取尾盘时段（14:00-15:00）的交易数据，用于尾盘因子计算。

## 版本历史

| 版本 | 时间 | 修改内容 |
|------|------|----------|
| v2.2 | 2026-05-29 18:00 | 第六轮深度优化：输出版本号同步、异常处理精确化（main/CLI删除网络异常）、虚假引用删除 |
| v2.1 | 2026-05-29 17:00 | 第五轮深度优化：注释修正、异常处理修正、删除未使用参数 |
| v2.0 | 2026-05-29 16:30 | 字段结构重构：尾盘时段扩展到14:00-15:00（13根K线）、新增 prices/volumes 数组、删除冗余字段 |
| v1.4 | 2026-05-29 15:00 | 第四轮深度优化：修复变量名覆盖bug、异常处理精确化、API常量命名规范化 |
| v1.0 | 2026-05-29 11:30 | 初始版本：复用公共模块、支持全量/增量模式 |

## 数据源

- **API**: 东方财富5分钟K线接口
- **URL**: `http://push2his.eastmoney.com/api/qt/stock/kline/get`
- **数据范围**: 约最近12个交易日（API限制）
- **数据粒度**: 5分钟K线（常量 `API_KLT = 5`）

## 尾盘时段定义

- **时间范围**: 14:00 - 15:00（收盘前1小时）
- **K线数量**: 13根5分钟K线
  - 14:00, 14:05, 14:10, 14:15, 14:20, 14:25, 14:30, 14:35, 14:40, 14:45, 14:50, 14:55, 15:00

## 输出指标

每条记录包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `date` | str | 交易日期 (YYYY-MM-DD) |
| `asset` | str | 股票代码 |
| `prices` | list[float] | 14:00-15:00 的13个收盘价（按时间升序） |
| `volumes` | list[int] | 14:00-15:00 的13个成交量（按时间升序） |
| `tail_high` | float | 尾盘最高价（13根K线最高价的最大值） |
| `tail_low` | float | 尾盘最低价（13根K线最低价的最小值） |

## 输出文件

- **路径**: `data_fetchers/result/tail_trading_data.json.gz`
- **格式**: JSON压缩文件
- **版本**: 2.1

## 输出结构

```json
{
  "meta": {
    "generated_at": "2026-05-29T16:30:00.000000",
    "source": "eastmoney_5min",
    "n_days": 10,
    "n_assets": 10,
    "date_range": {
      "start": "2026-05-15",
      "end": "2026-05-28"
    },
    "last_updated": "2026-05-29 16:30:00",
    "version": "2.1"
  },
  "data": [
    {
      "date": "2026-05-28",
      "asset": "000001",
      "prices": [10.95, 10.96, 10.97, 10.98, 10.99, 11.00, 10.99, 10.98, 10.99, 11.00, 11.01, 11.00, 10.99],
      "volumes": [12345, 23456, 34567, 45678, 56789, 67890, 78901, 89012, 90123, 12345, 23456, 34567, 45678],
      "tail_high": 11.01,
      "tail_low": 10.95
    }
  ]
}
```

## 运行模式

### 全量模式

拉取所有股票的历史数据（约12个交易日）。

```bash
cd /home/admin/projects/factor_ic_analyzer/data_fetchers
python3 fetch_tail_trading.py --full
```

**执行时间估算**: 约10分钟（3000支股票 × 200ms间隔）

### 增量模式

拉取最新一天的尾盘数据，追加到现有缓存。

```bash
python3 fetch_tail_trading.py
```

**执行时间估算**: 约10分钟（3000支股票 × 200ms间隔）

### 测试模式

只拉取10支股票，用于快速验证。

```bash
python3 fetch_tail_trading.py --test --full
```

**执行时间**: 约5秒

## 限流控制

- **请求间隔**: 200ms
- **重试机制**: 3次重试，1秒间隔
- **并发限制**: 单线程顺序请求

## 依赖模块

| 模块 | 功能 |
|------|------|
| `common/http_client.py` | HTTP请求（eastmoney_session, request_with_retry） |
| `common/cache_manager.py` | 缓存读写（read_cache, write_cache） |
| `common/stock_utils.py` | 股票列表（load_main_board_stock_list） |
| `common/paths.py` | 路径管理（get_module_result_dir） |
| `common/logger_config.py` | 日志配置（setup_logger） |

## 测试验证

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 -m pytest data_fetchers/test_cases/test_fetch_tail_trading.py -v
```

**测试覆盖**:
- K线字符串解析
- 尾盘时段筛选
- 指标计算逻辑
- 市场代码转换
- 版本常量验证

## 常见问题

### Q1: 为什么只能获取12天历史数据？

东方财富API对5分钟K线的请求限制为最近500条数据。每天约48根5分钟K线，因此只能获取约10-12个交易日的历史数据。

### Q2: 增量模式如何判断是否需要追加？

增量模式检查缓存中最新的日期，如果当天已有数据则跳过，否则拉取最新一天追加到缓存。

### Q3: 尾盘K线数量不足时如何处理？

如果某天尾盘K线数量不足13根（如停牌、数据缺失），该天的尾盘数据会被跳过，不写入输出。

## 相关文档

- [实现计划](./docs/plans/fetch_tail_trading_plan.md)
- [字段重构计划](./docs/plans/fetch_tail_trading_field_refactor_plan_v1.0.md)
- [模块规范](../MODULE.md)
- [项目规范](../PROJECT.md)