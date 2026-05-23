# KDJ_J 因子分层回测流程文档

**创建日期**: 2026-05-23
**因子名称**: kdj_j_1d
**因子方向**: 反向因子（ic_mean = -0.015）

---

## 1. 因子概述

### 1.1 因子定义

KDJ_J 因子是 KDJ 指标的 J 值，计算公式：

```
RSV = (Close - LowN) / (HighN - LowN) * 100
K = EMA(RSV, m1)  （首次用50）
D = EMA(K, m2)    （首次用50）
J = 3K - 2D
```

其中：
- `N = 9`: RSV 计算周期
- `M1 = 3`: K 值平滑周期
- `M2 = 3`: D 值平滑周期

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | -∞ ~ +∞（可超出 0-100） |
| 实测范围 | -28.62 ~ 128.78 |
| 超买信号 | J > 100 |
| 超卖信号 | J < 0 |

### 1.3 IC 分析结果

```json
{
  "ic_mean": -0.01518764980544747,
  "factor_direction": "反向因子：分层回测时做多低值组、做空高值组",
  "statistical_significance": true
}
```

**结论**: IC 绝对值 < 0.03，预测能力较弱，但统计显著。

---

## 2. 分层配置

### 2.1 分层阈值

```python
layer_thresholds = [-30, 0, 20, 80, 100, 130]
```

**分层定义**:

| Layer | 阈值范围 | 名称 | 含义 |
|-------|----------|------|------|
| 1 | J < 0 | 超卖层 | 极度超卖 |
| 2 | 0 ≤ J < 20 | 偏下层 | 超卖倾向 |
| 3 | 20 ≤ J < 80 | 中性层 | 中性区间 |
| 4 | 80 ≤ J < 100 | 偏上层 | 超买倾向 |
| 5 | J ≥ 100 | 超买层 | 极度超买 |

### 2.2 多空组合

```python
factor_direction = 'negative'  # 反向因子
long_layers = [1, 2]   # 做多超卖层
short_layers = [4, 5]  # 做空超买层
```

**策略逻辑**: 
- 反向因子，做多低值组（超卖），做空高值组（超买）
- 符合 KDJ 指标的传统用法：超卖反弹、超买回调

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 脚本实现

### 3.1 文件位置

```
backtest/layered_backtest_kdj_j_1d.py
```

### 3.2 核心函数

#### `calculate_kdj_j(factor_df, n=9, m1=3, m2=3)`

**计算步骤**:
1. 按 asset+date 排序
2. 计算 n 日滚动最高价 HighN 和最低价 LowN
3. 计算 RSV = (Close - LowN) / (HighN - LowN) * 100
4. 使用 EWM 计算 K（初始值 50）
5. 使用 EWM 计算 D（初始值 50）
6. 计算 J = 3K - 2D

**注意事项**:
- 函数入口必须先 `.copy()`
- KDJ 是单股票时序指标，必须按 asset 分组
- `rolling(min_periods=n)` 导致前 n-1 天为 NaN

#### `run_kdj_j_layered_backtest()`

**执行流程**:
```
1. 加载配置 KDJJLayerConfig
2. 从缓存加载因子数据和收益数据
3. 计算 KDJ_J 因子
4. 创建回测引擎 LayeredBacktestEngine
5. 执行分层回测
6. 生成报告
7. 保存结果
```

### 3.3 运行命令

```bash
cd /home/admin/projects/factor_ic_analyzer
PYTHONPATH=/home/admin/projects/factor_ic_analyzer python3 backtest/layered_backtest_kdj_j_1d.py
```

---

## 4. 输出结果

### 4.1 输出文件

| 文件 | 路径 |
|------|------|
| 回测结果 | `cache/backtest/kdj_j_layered_backtest.json` |
| 每日明细 | `cache/backtest/kdj_j_layered_backtest_daily.json.gz` |

### 4.2 结果结构

```json
{
  "meta": {
    "factor_name": "kdj_j",
    "n_days_total": 515,
    "n_assets_total": 2999,
    "layer_names": {...},
    "kdj_params": {"n": 9, "m1": 3, "m2": 3}
  },
  "layer_stats": [...],
  "long_short": {...},
  "monotonicity": {...},
  "config": {...}
}
```

---

## 5. 分层效果评估

### 5.1 评估维度

1. **单调性**: Layer 1→5 收益是否递减（反向因子）
2. **多空收益**: long_layers vs short_layers 的收益差
3. **夏普比率**: 风险调整后收益
4. **换手率**: 交易成本影响

### 5.2 预期结果

由于 IC 绝对值较小（-0.015），分层效果可能不显著：
- 单调性可能较弱
- 多空组合收益差可能较小
- 需结合其他因子使用

---

## 6. 规范遵循

### 6.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

### 6.2 代码规范

遵循 `PROJECT.md`:
- 使用 `logging` 模块（非 `print`）
- 函数入口 `.copy()` 防副作用
- pandas 语义，避免 `np.where` 混用

### 6.3 公共模块复用

| 模块 | 用途 |
|------|------|
| `factor_ic.common.logger_config` | 日志配置 |
| `factor_ic.common.convert_types` | 类型转换 |
| `backtest.common.layered_backtest` | 分层回测引擎 |

---

## 7. 注意事项

### 7.1 KDJ 计算陷阱

1. **初始值问题**: EWM 计算需要虚拟初始值 50
2. **排序问题**: 必须 asset+date 排序，否则跨股票混合
3. **NaN 处理**: 前 n-1 天为 NaN，回测时自动过滤

### 7.2 边界处理

实测 J 值范围 -28.62 ~ 128.78，阈值设计需覆盖：
- 下界: -30（实测最小值向下取整）
- 上界: 130（实测最大值向上取整）

### 7.3 IC 较弱的因子

KDJ_J 因子 IC 绝对值 < 0.03：
- 单独使用效果有限
- 建议与其他因子组合使用
- 可作为辅助信号

---

## 8. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-05-23 | v1.0 | 初始版本，创建 KDJ_J 分层回测脚本 |