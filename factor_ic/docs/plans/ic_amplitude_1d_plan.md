# 振幅因子实现计划

> 创建时间: 2026-05-29
> 状态: 待执行

## 任务概述

实现振幅因子（Amplitude）的完整流程：
1. IC 计算（factor_ic/ic_amplitude_1d.py）
2. 分层回测（backtest/layered_backtest_amplitude_1d.py）
3. 综合因子集成（待验证因子有效性后决定）

## 因子定义

### 公式
```
amplitude = (high - low) / close
```

### 含义
- 当日振幅相对于收盘价的比率
- 反映价格波动强度
- 值越大 → 波动越剧烈
- 值越小 → 波动平稳

### 范围
- 理论范围: [0, +∞)
- 实际范围: 通常 [0, 0.15]（A股振幅上限15%）

### 边界处理
- close = 0 时：使用 epsilon 防止除零，设为 NaN（无效数据）
- high = low 时：振幅为 0（一字涨停/跌停）

## 实现步骤

### Step 1: 因子计算函数（factor_calculator.py）

```python
def calculate_amplitude(
    factor_df: pd.DataFrame,
    logger_arg: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    计算振幅因子
    
    公式: amplitude = (high - low) / close
    
    Args:
        factor_df: 包含 high, low, close 列的 DataFrame
        logger_arg: 日志记录器（可选）
    
    Returns:
        添加 amplitude 列的 DataFrame
    """
```

新增常量：
- `_COL_AMPLITUDE = 'amplitude'`
- `_DEFAULT_AMPLITUDE_EPSILON = 1e-10`

### Step 2: IC 计算脚本（factor_ic/ic_amplitude_1d.py）

参考模板: `ic_price_position_1d.py`

关键参数：
- `factor_name='amplitude'`
- `factor_col='amplitude'`
- `factor_cols=['high', 'low', 'close']`
- `custom_factor_calculation=calculate_amplitude`

### Step 3: 分层回测脚本（backtest/layered_backtest_amplitude_1d.py）

参考模板: `layered_backtest_price_position_1d.py`

配置：
- 因子方向：待 IC 结果确定（预判为 positive，高振幅→高波动→高收益？）
- long_layers: [4, 5]（高振幅层）
- short_layers: [1, 2]（低振幅层）
- 分层命名：低振幅层/中振幅层/高振幅层

### Step 4: 运行验证

```bash
# IC 计算
python factor_ic/ic_amplitude_1d.py

# 分层回测
python backtest/layered_backtest_amplitude_1d.py
```

### Step 5: 文档更新

- factor_calculator.py 版本历史
- factor_ic/MODULE.md 更新
- backtest/MODULE.md 更新
- 流程文档创建

## 综合因子集成

**前提条件**：因子通过有效性筛选

MODULE.md 无效因子判定标准：
- |ic_mean| < 0.03
- |icir| < 0.15
- |monotonicity_corr| < 0.4
- long_short_return < 3%

**通过条件**：四项全部满足则纳入综合因子候选池

## 文件清单

| 文件 | 类型 | 状态 |
|------|------|------|
| data_fetchers/factor_calculator.py | 修改 | 待执行 |
| factor_ic/ic_amplitude_1d.py | 新建 | 待执行 |
| backtest/layered_backtest_amplitude_1d.py | 新建 | 待执行 |
| factor_ic/docs/amplitude_flow.md | 新建 | 待执行 |
| factor_ic/MODULE.md | 修改 | 待执行 |

## 风险评估

1. **振幅为零数据**：一字涨停/跌停场景（约 0.21% 数据）
   - 处理：返回 0（正确反映无波动）
   
2. **close 为零**：无效数据
   - 处理：设为 NaN，后续 IC 计算自动过滤

3. **因子方向不确定性**：振幅与收益关系需实测
   - 高振幅可能意味着高风险高收益（正向）
   - 或高波动意味着不稳定（负向）