# fetch_tail_trading.py 字段重构计划 v1.0

> 创建时间: 2026-05-29 16:30 北京时间
> 目标: 简化输出字段，尾盘时段从 14:30-15:00 改为 14:00-15:00

---

## 需求变更

| 原字段 | 新字段 | 说明 |
|-------|--------|------|
| `tail_volume` | **删除** | 冗余 |
| `tail_volume_pct` | **删除** | 冗余 |
| `tail_close` | **删除** | 冗余（prices 数组已包含） |
| - | `prices` | **新增** - 14:00-15:00 的13个收盘价 |
| - | `volumes` | **新增** - 14:00-15:00 的13个5分钟成交量 |
| `tail_high` | `tail_high` | 保留，区间扩大到14:00-15:00 |
| `tail_low` | `tail_low` | 保留，区间扩大到14:00-15:00 |

**尾盘时段变更**：14:30-15:00（7根K线） → 14:00-15:00（13根K线）

---

## 输出结构对比

### 原结构
```json
{
  "date": "2026-05-28",
  "asset": "000001",
  "tail_volume": 121393,
  "tail_volume_pct": 0.1419,
  "tail_high": 10.99,
  "tail_low": 10.97,
  "tail_close": 10.99
}
```

### 新结构
```json
{
  "date": "2026-05-28",
  "asset": "000001",
  "prices": [10.95, 10.96, 10.97, 10.98, 10.99, 11.00, 10.99, 10.98, 10.99, 11.00, 11.01, 11.00, 10.99],
  "volumes": [12345, 23456, 34567, 45678, 56789, 67890, 78901, 89012, 90123, 12345, 23456, 34567, 45678],
  "tail_high": 11.01,
  "tail_low": 10.95
}
```

---

## 执行步骤

### Step 1: 常量修改（fetch_tail_trading.py 第99-101行）

| 修改点 | 原值 | 新值 |
|-------|------|------|
| `TAIL_PERIOD_START` | `'14:30'` | `'14:00'` |
| `TAIL_KLINE_COUNT` | `7` | `13` |

**文件头版本历史更新**：
- 新增 v2.0 (2026-05-29): 字段结构重构（尾盘时段扩展、新增 prices/volumes、删除冗余字段）

### Step 2: `_calculate_tail_metrics` 函数重构（第163-209行）

**删除字段计算**：
- `tail_volume`
- `tail_volume_pct`
- `tail_close`

**新增字段计算**：
- `prices`: 从 tail_klines 提取所有收盘价，按时间排序
- `volumes`: 从 tail_klines 提取所有成交量，按时间排序

**保留字段修改**：
- `tail_high`: max(所有K线的high)
- `tail_low`: min(所有K线的low)

**docstring 更新**：
```python
"""
计算尾盘指标

Returns:
    尾盘指标字典，包含：
    - prices: 14:00-15:00 的13个收盘价（按时间升序）
    - volumes: 14:00-15:00 的13个成交量（按时间升序）
    - tail_high: 尾盘最高价
    - tail_low: 尾盘最低价
    
Note:
    若尾盘K线数量不足13根，返回 None
"""
```

### Step 3: `fetch_tail_trading_for_stock` docstring 更新（第212-239行）

**Returns 节更新**：
```python
"""
Returns:
    尾盘数据记录列表，每条包含：
    - date: 交易日期
    - asset: 股票代码
    - prices: 14:00-15:00 的13个收盘价
    - volumes: 14:00-15:00 的13个成交量
    - tail_high: 尾盘最高价
    - tail_low: 尾盘最低价
"""
```

### Step 4: `_filter_tail_klines` docstring 更新（第141-153行）

**Note 更新**：
```python
"""
Note:
    尾盘时段共13根5分钟K线：14:00, 14:05, 14:10, 14:15, 14:20, 14:25, 14:30, 14:35, 14:40, 14:45, 14:50, 14:55, 15:00
"""
```

### Step 5: 版本常量更新（第80行）

```python
_OUTPUT_VERSION = '2.0'  # 字段结构变更
```

### Step 6: 流程文档更新（docs/fetch_tail_trading_flow.md）

| 修改点 | 内容 |
|-------|------|
| 版本历史表 | 新增 v2.0 行 |
| 尾盘时段定义 | 14:00-15:00（13根K线） |
| 输出指标表 | 更新字段列表 |
| 输出结构示例 | 更新 JSON 示例 |

### Step 7: 测试用例更新（test_cases/test_fetch_tail_trading.py）

| 测试类 | 修改内容 |
|-------|---------|
| `TestTailKlineFilter` | 尾盘时段改为 14:00-15:00（13根K线） |
| `TestTailMetrics` | 字段验证改为 `prices`、`volumes`，删除 `tail_volume`/`tail_volume_pct`/`tail_close` |
| `TestOutputVersion` | 版本验证改为 `'2.0'` |

---

## 验证检查清单

```
□ 常量修改正确（TAIL_PERIOD_START、TAIL_KLINE_COUNT）
□ _calculate_tail_metrics 返回新字段结构
□ prices/volumes 按时间升序排列
□ tail_high/tail_low 使用13根K线范围
□ docstring 全部更新
□ _OUTPUT_VERSION 更新为 '2.0'
□ 文件头版本历史新增 v2.0
□ 流程文档同步更新
□ 测试用例同步更新
□ 运行脚本验证输出结构
□ 运行 pytest 验证测试通过
```

---

## 文件修改清单

| 文件 | 操作 |
|-----|------|
| `fetch_tail_trading.py` | 常量 + 函数 + docstring + 版本 |
| `docs/fetch_tail_trading_flow.md` | 字段表 + 示例 + 版本历史 |
| `test_cases/test_fetch_tail_trading.py` | 测试用例同步 |