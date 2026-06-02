# 尾盘量能加速度因子开发计划

> 版本: v1.0
> 创建时间: 2026-06-02

---

## 1. 因子定义

### 1.1 公式

```
量能加速度 = 后半段成交量总和 / 前半段成交量总和

前半段: 14:00-14:30（含14:30，不含14:35）
  - 时间点: 14:00, 14:05, 14:10, 14:15, 14:20, 14:25
  - K线索引: volumes[0:6]（共6根）

后半段: 14:30-15:00（不含14:30，含15:00）
  - 时间点: 14:35, 14:40, 14:45, 14:50, 14:55, 15:00
  - K线索引: volumes[7:13]（共6根）
  - 注意: 14:30（索引6）不属于后半段

factor_value = sum(volumes[7:13]) / sum(volumes[0:6])
```

### 1.2 含义

| factor_value | 含义 |
|-------------|------|
| > 1 | 后半段成交量更大，尾盘加速交易 |
| = 1 | 前后段成交量相等，平稳交易 |
| < 1 | 前半段成交量更大，尾盘减速交易 |

### 1.3 理论预期

尾盘加速交易可能预示：
- 资金抢筹（加速 > 1）→ 看涨预期 → 正向因子
- 资金撤离（加速 < 1）→ 看跌预期 → 正向因子

**方向由实测 IC 确定**，不预设。

---

## 2. 数据依赖

| 数据文件 | 字段 | 说明 |
|---------|------|------|
| tail_trading_data.json.gz | volumes | 13根5分钟K线成交量数组 |
| factor_ic_data.json.gz | forward_return_1d | 次日收益 |

---

## 3. 边界处理

| 场景 | 处理 |
|------|------|
| volumes 长度不足 13 | 返回 NaN（数据不完整） |
| volumes 包含 NaN/None | 返回 NaN（数据污染） |
| 前半段成交量为 0 | 返回 NaN（除零防护） |
| 后半段成交量为 0 | 返回 0（无交易） |

---

## 4. 开发任务

### 4.1 IC 脚本

| 任务 | 文件 | 参考 |
|------|------|------|
| 创建 IC 脚本 | factor_ic/ic_tail_volume_acceleration_1d.py | ic_tail_price_volume_intensity.py |
| 创建流程文档 | factor_ic/docs/ic_tail_volume_acceleration_1d_flow.md | ic_tail_price_volume_intensity_flow.md |
| 创建 pytest 测试 | factor_ic/test_cases/test_ic_tail_volume_acceleration_1d.py | test_ic_tail_price_volume_intensity.py |
| 创建测试用例文档 | factor_ic/test_cases/ic_tail_volume_acceleration_1d_test_cases.md | ic_tail_price_volume_intensity_test_cases.md |

### 4.2 分层回测脚本

| 任务 | 文件 | 参考 |
|------|------|------|
| 创建分层回测脚本 | backtest/layered_backtest_tail_volume_acceleration_1d.py | layered_backtest_tail_price_volume_intensity_1d.py |
| 创建流程文档 | backtest/docs/layered_backtest_tail_volume_acceleration_1d_flow.md | layered_backtest_tail_price_volume_intensity_1d_flow.md |
| 创建 pytest 测试 | backtest/test_cases/test_layered_backtest_tail_volume_acceleration_1d.py | test_layered_backtest_tail_price_volume_intensity_1d.py |

---

## 5. 执行顺序

```
Phase 1: IC 脚本开发
├── 1.1 创建 ic_tail_volume_acceleration_1d.py
├── 1.2 创建 ic_tail_volume_acceleration_1d_flow.md
├── 1.3 创建 test_ic_tail_volume_acceleration_1d.py
├── 1.4 创建 ic_tail_volume_acceleration_1d_test_cases.md
├── 1.5 运行脚本验证
├── 1.6 pytest 验证
└── 1.7 ruff check/format

Phase 2: IC 脚本 5 轮优化
├── Round 1: Spec Compliance
├── Round 2: 代码结构
├── Round 3: 边界处理
├── Round 4: 流程文档同步
├── Round 5: 测试文件同步

Phase 3: 分层回测脚本开发
├── 3.1 创建 layered_backtest_tail_volume_acceleration_1d.py
├── 3.2 创建 layered_backtest_tail_volume_acceleration_1d_flow.md
├── 3.3 创建 test_layered_backtest_tail_volume_acceleration_1d.py
├── 3.4 运行脚本验证
├── 3.5 pytest 验证
└── 3.6 ruff check/format

Phase 4: 分层回测脚本 5 轮优化
├── Round 1: Spec Compliance
├── Round 2: 代码结构
├── Round 3: 边界处理
├── Round 4: 流程文档同步
├── Round 5: 测试文件同步

Phase 5: Git commit
```

---

## 6. 命名规范

| 类型 | 命名 |
|------|------|
| 因子名 | tail_volume_acceleration |
| IC 脚本 | ic_tail_volume_acceleration_1d.py |
| 分层回测脚本 | layered_backtest_tail_volume_acceleration_1d.py |
| 结果文件 | ic_tail_volume_acceleration_1d_analysis_result.json |

---

## 7. 参照脚本

| 脚本 | 用途 |
|------|------|
| ic_tail_price_volume_intensity.py | IC 脚本模板（同为尾盘数据源） |
| ic_tail_price_slope_1d.py | IC 脚本模板（百分比斜率因子） |
| layered_backtest_tail_price_volume_intensity_1d.py | 分层回测模板（薄声明模式） |