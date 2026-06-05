# Design: momentum_strength 因子开发

## 1. 需求概述

**因子定义**：
- `momentum_strength = return_5d / std(return_1d, 5日)`
- 含义：动量强度因子，衡量 5 日累计涨幅相对于 5 日日收益率波动率的比率
- 高值 → 持续上涨趋势（动量强），低值 → 震荡或下跌（动量弱）

**公式依赖**：
- `return_5d`: 5 日累计涨幅（已有因子 `return_5d` 在 `_EXTENDED_FACTOR_COLS`）
- `return_1d`: 日收益率序列（需计算，已存在 `past_return_1d`）

**注意**：`return_5d` 和 `past_return_1d` 已在 factor_generator.py 中定义并计算。

## 2. 文件修改清单

### 2.1 数据层（Phase 1）

| 序号 | 文件 | 修改位置 | 作用 |
|------|------|----------|------|
| 1 | `data_fetchers/factor_calculator.py` | 新增 `calculate_momentum_strength()` | 因子计算逻辑 |
| 2 | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` 添加 | 数据源因子列定义 |
| 3 | `data_fetchers/factor_generator.py` | 导入 `calculate_momentum_strength` | 导入因子计算函数 |
| 4 | `data_fetchers/factor_generator.py` | Step X 计算 `momentum_strength` | 执行因子计算 |

### 2.2 IC 脚本（Phase 2）

| 序号 | 文件 | 修改位置 | 作用 |
|------|------|----------|------|
| 5 | `factor_ic/ic_momentum_strength_1d.py` | 新建 | IC 计算脚本 |
| 6 | `factor_ic/docs/ic_momentum_strength_1d_flow.md` | 新建 | 流程文档 |
| 7 | `factor_ic/test_cases/test_ic_momentum_strength_1d.py` | 新建 | pytest 测试 |
| 8 | `factor_ic/test_cases/ic_momentum_strength_1d_test_cases.md` | 新建 | 测试用例文档 |

### 2.3 分层回测脚本（Phase 3）

| 序号 | 文件 | 修改位置 | 作用 |
|------|------|----------|------|
| 9 | `backtest/layered_backtest_momentum_strength_1d.py` | 新建 | 分层回测脚本 |
| 10 | `backtest/docs/layered_backtest_momentum_strength_1d_flow.md` | 新建 | 流程文档 |
| 11 | `backtest/test_cases/test_layered_backtest_momentum_strength_1d.py` | 新建 | pytest 测试 |

### 2.4 因子映射与定义（Phase 4）

| 序号 | 文件 | 修改位置 | 作用 |
|------|------|----------|------|
| 12 | `comprehensive_factor/common/factor_selector.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（筛选层） |
| 13 | `comprehensive_factor/common/weight_engine.py` | `FACTOR_NAME_TO_COL_MAP` | 因子名→列名映射（权重层） |
| 14 | `factor_definitions.py` | `FACTOR_DEFINITIONS` | 因子定义（名称、公式、含义） |

### 2.5 项目文档（Phase 5）

| 序号 | 文件 | 修改位置 | 作用 |
|------|------|----------|------|
| 15 | `PROJECT.md` | 因子列表章节 | 项目级因子清单 |
| 16 | `data_fetchers/MODULE.md` | 版本历史 | 模块版本更新 |
| 17 | `factor_ic/MODULE.md` | 版本历史 | 模块版本更新 |
| 18 | `backtest/MODULE.md` | 版本历史 | 模块版本更新 |

## 3. 核心计算逻辑

### 3.1 因子计算函数签名

```python
def calculate_momentum_strength(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    计算动量强度因子
    
    公式: momentum_strength = return_5d / std(return_1d, 5日)
    
    Args:
        factor_df: 包含 return_5d 和 close 列的 DataFrame
        logger_arg: 日志记录器
    
    Returns:
        添加 momentum_strength 列的 DataFrame
    
    边界处理:
        - std = 0 时设为 NaN（除零保护）
        - return_5d = NaN 时结果为 NaN（历史不足）
        - 前5日数据设为 NaN（rolling window不足）
    """
```

### 3.2 计算步骤

```python
# Step 1: 入口 copy（遵循 M11）
factor_df = factor_df.copy()

# Step 2: 计算日收益率 return_1d
# past_return_1d = close[t] / close[t-1] - 1
factor_df['return_1d_temp'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x / x.shift(1) - 1
)

# Step 3: 计算 5 日标准差（rolling std）
factor_df['return_1d_std_5'] = factor_df.groupby('asset')['return_1d_temp'].transform(
    lambda x: x.rolling(window=5, min_periods=5).std()
)

# Step 4: 计算动量强度
# momentum_strength = return_5d / std(return_1d, 5)
factor_df['momentum_strength'] = factor_df['return_5d'] / factor_df['return_1d_std_5']

# Step 5: 除零保护（std = 0 → NaN）
factor_df.loc[factor_df['return_1d_std_5'] < EPSILON, 'momentum_strength'] = np.nan

# Step 6: 清理临时列
del factor_df['return_1d_temp']
del factor_df['return_1d_std_5']

return factor_df
```

### 3.3 输入列依赖

- `close`: 计算日收益率 `return_1d`
- `return_5d`: 5 日累计涨幅（已存在于数据源）

**关键依赖**: `return_5d` 必须先在 factor_generator.py 中计算完成，才能用于本因子。

## 4. IC 脚本模板

遵循 `factor_ic/ic_amplitude_1d.py` 模板结构：

```python
#!/usr/bin/env python3
"""动量强度因子 IC 计算器"""

from data_fetchers.factor_calculator import calculate_momentum_strength
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)
DEFAULT_MIN_STOCKS = 10

def main():
    result = run_complex_factor_ic(
        factor_name='momentum_strength',
        factor_col='momentum_strength',
        factor_cols=['close', 'return_5d'],  # 需要 close 计算 return_1d，需要 return_5d
        custom_factor_calculation=calculate_momentum_strength,
        min_stocks=DEFAULT_MIN_STOCKS,
        _logger=logger
    )
    # ... 日志输出
    return result
```

## 5. 分层回测脚本模板

遵循 `backtest/layered_backtest_amplitude_1d.py` 模板结构：

```python
#!/usr/bin/env python3
"""动量强度因子分层回测脚本"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_momentum_strength


class MomentumStrengthLayerConfig(LayerConfigBase):
    """动量强度因子分层配置"""
    
    factor_name: ClassVar[str] = 'momentum_strength'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest', 'lower', 'normal', 'higher', 'highest'
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=MomentumStrengthLayerConfig,
        factor_calculator=calculate_momentum_strength
    )
```

## 6. 执行顺序

按照 PROJECT.md 因子开发规范，修改顺序：

```
Phase 1: 数据层
  → factor_calculator.py (计算函数)
  → factor_generator.py (数据源)

Phase 2: IC 脚本
  → ic_momentum_strength_1d.py
  → 流程文档
  → pytest 测试

Phase 3: 分层回测脚本
  → layered_backtest_momentum_strength_1d.py
  → 流程文档
  → pytest 测试

Phase 4: 因子映射
  → factor_selector.py
  → weight_engine.py
  → factor_definitions.py

Phase 5: 文档更新
  → PROJECT.md
  → MODULE.md 版本历史
```

## 7. 验证检查清单

### 7.1 数据层验证

- [ ] `calculate_momentum_strength()` 函数正确计算
- [ ] 边界处理：std=0 → NaN，前5日 → NaN
- [ ] 临时列清理完成
- [ ] factor_generator.py 正确调用并保存到数据源

### 7.2 IC 脚本验证

- [ ] 输出结构符合 MODULE.md 模板
- [ ] 五维度判断字段完整
- [ ] 流程文档时间标注同步
- [ ] pytest 测试通过

### 7.3 分层回测验证

- [ ] percentile 分层正确
- [ ] factor_direction 从 IC 文件派生
- [ ] 流程文档时间标注同步
- [ ] pytest 测试通过

### 7.4 规范合规检查

- [ ] H1: 模块边界（无跨模块复用）
- [ ] H2: 输出位置（result/ 目录）
- [ ] H6: 异常链（raise ... from e）
- [ ] H7: 路径导入（from paths import）
- [ ] M11: DataFrame 入口 copy
- [ ] M53: 计算前数据校验

## 8. 任务拆分建议

由于涉及 15+ 文件，建议拆分为 5 个子任务：

| 子任务 | 文件数 | 行数估计 |
|--------|--------|----------|
| Task 1: 数据层 | 2 | ~80 行 |
| Task 2: IC 脚本 | 4 | ~150 行 |
| Task 3: 分层回测 | 3 | ~100 行 |
| Task 4: 因子映射 | 3 | ~30 行 |
| Task 5: 文档更新 | 4 | ~50 行 |

每个子任务符合 H9 任务粒度约束（≤3 文件、≤200 行）。

---

**创建时间**: 2026-06-05
**状态**: 待审核