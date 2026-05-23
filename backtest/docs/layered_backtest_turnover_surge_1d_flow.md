# 换手率突增因子分层回测流程文档

**创建日期**: 2026-05-23
**因子名称**: turnover_surge_1d
**因子方向**: 反向因子（ic_mean = -0.0526）

---

## 1. 因子概述

### 1.1 因子定义

换手率突增因子衡量当日换手率相对于历史均值的变化程度：

```
avg_turnover = 过去 N 日换手率均值（不含当日）
turnover_surge = 当日换手率 / avg_turnover
```

其中：
- `surge_window = 5`: 换手率均值计算窗口
- 分子分母都为正数，因子值恒 ≥ 0

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | ≥ 0（无上界） |
| 实测范围 | 0.01 ~ 18.34 |
| 正常值 | surge ≈ 1（当日换手率等于历史均值） |
| 突增信号 | surge > 1（换手率高于均值） |

### 1.3 IC 分析结果

```json
{
  "ic_mean": -0.052552,
  "factor_direction": "反向因子：分层回测时做多低值组、做空高值组",
  "statistical_significance": true
}
```

**结论**: IC 绝对值 > 0.05，预测能力较强，统计显著。

---

## 2. 分层配置

### 2.1 分层阈值

```python
layer_thresholds = [0, 0.5, 1.0, 1.5, 2.0, 3.0]
```

**分层定义**:

| Layer | 阈值范围 | 名称 | 含义 |
|-------|----------|------|------|
| 1 | surge < 0.5 | 极低层 | 换手率远低于均值 |
| 2 | 0.5 ≤ surge < 1 | 偏低层 | 换手率低于均值 |
| 3 | 1 ≤ surge < 1.5 | 正常层 | 换手率接近均值 |
| 4 | 1.5 ≤ surge < 2 | 偏高层 | 换手率偏高 |
| 5 | surge ≥ 2 | 突增层 | 换手率突增 |

### 2.2 多空组合

```python
factor_direction = 'negative'  # 反向因子
long_layers = [1, 2]   # 做多极低偏低层
short_layers = [4, 5]  # 做空偏高层突增层
```

**策略逻辑**: 
- 反向因子，做多低 surge 值组，做空高 surge 值组
- IC 为负说明高换手率突增预期低收益（短期过度交易）

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |
| surge_window | 5 | 换手率均值窗口 |

---

## 3. 数据加载

### 3.1 数据来源

换手率突增因子需要三个数据源：

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 主因子数据 | factor_data.json.gz | date, asset, close |
| 换手率数据 | turnover_rate_data.json.gz | date, asset, turnover_rate |
| 收益数据 | return_data.json.gz | date, asset, forward_return_1d |

### 3.2 数据合并

```python
# 按 date + asset 合并换手率数据
factor_df = factor_df.merge(
    turnover_df[['date', 'asset', 'turnover_rate']],
    on=['date', 'asset'],
    how='left'
)
```

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_turnover_surge_1d.py
```

### 4.2 核心函数

#### `calculate_turnover_surge(factor_df, surge_window=5)`

**计算步骤**:
1. 按 asset+date 排序
2. 计算过去 N 日换手率均值（不含当日）
3. 除零防护：avg_turnover 接近零时标记为 NaN
4. 计算 surge = 当日换手率 / avg_turnover
5. 检测异常负值

**注意事项**:
- 函数入口必须先 `.copy()`
- shift(1) 确保均值不含当日
- 需要 surge_window + 1 天历史数据才能得到第一个有效值

---

## 5. 输出结果

### 5.1 输出文件

遵循 PROJECT.md 输出目录规范，结果输出到 `backtest/result/`：

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/turnover_surge_layered_backtest.json` |
| 每日明细 | `backtest/result/turnover_surge_layered_backtest_daily.json.gz` |

### 5.2 回测结果摘要

| 指标 | 值 |
|------|-----|
| 回测天数 | 510 天 |
| 股票数量 | 2999 只 |
| turnover_surge 范围 | 0.01 ~ 470.28 |
| 分层阈值 | [0, 0.5, 1.0, 2.0, 5.0, 500.0] |
| 多头年化收益 | 66.49% |
| 空头年化收益 | -37.66% |
| 多空年化收益 | 104.15% |
| 多空夏普比率 | 4.89 |
| 单调性相关系数 | -0.9573 (good) |

---

## 6. 分层效果评估

### 6.1 单调性分析

- 单调性相关系数 -0.9573（good）
- 反向因子单调性良好：Layer 1→5 收益递增（符合预期）

### 6.2 多空组合分析

- 多头（Layer 1,2）：年化收益 66.49%，夏普比高
- 空头（Layer 4,5）：年化收益 -37.66%（反向因子空头亏损）
- 多空组合：104.15%，夏普比 4.89（表现优异）

### 6.3 结论

IC 绝对值较大（-0.0526），单调性良好，多空夏普比高达 4.89。因子预测能力较强，分层效果显著。适合与其他因子组合使用。

---

## 7. 规范遵循

### 7.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

### 7.2 输出目录规范

遵循 `PROJECT.md`:
- 结果输出到 `backtest/result/` 目录

### 7.3 数据加载规范

遵循 PROJECT.md 数据完整性校验规范：
- 校验文件存在
- 校验 JSON 解析
- 校验结构完整性

---

## 8. 注意事项

### 8.1 换手率数据来源

换手率数据不在主 factor_data.json.gz 中，需要额外加载 turnover_rate_data.json.gz。

### 8.2 除零防护

avg_turnover 接近零时（过去 N 日完全无交易），turnover_surge 会爆炸式放大，需标记为 NaN。

### 8.3 因子范围

实测 surge 范围 0.01 ~ 18.34，阈值设计需覆盖常见范围，极端值归入边界层。

---

## 9. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-23 | v1.0 | 初始版本，创建换手率突增分层回测脚本 |