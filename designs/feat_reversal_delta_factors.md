# Design: 止跌信号差分因子（Reversal Delta Factors）

> 遵循 AGENTS.md Design-First 流程：涉及 2+ 文件改动，必须先提交 design.md 通过审核才能动手。

---

## 1. 需求概述

**问题根因**（Pitfall #60）：8个选中因子全部描述"当天绝对状态"，7个负向因子天然偏好"极端弱势"股票。无论怎么调权重/砍冗余，选股都偏向闷跌股。模型无法区分：
- ✅ 超跌止跌股（放量、尾盘回升、换手增加）
- ❌ 闷跌股（缩量、尾盘收低、换手不变）

**解决方案**：新增4个差分因子 `factor(T) - factor(T-1)`，捕捉"从弱转强"的止跌信号，补充"状态变化"维度。

### 新增因子定义

| 因子名 | 公式 | 含义 | 依赖原始因子 | IC方向预期 |
|--------|------|------|------------|-----------|
| `amplitude_delta` | amplitude(T) - amplitude(T-1) | 振幅变化：回升=止跌放量 | amplitude | 不预判（H5） |
| `turnover_surge_delta` | turnover_surge(T) - turnover_surge(T-1) | 换手突增变化：增加=关注回升 | turnover_surge | 不预判（H5） |
| `tail_price_position_delta` | tail_price_position(T) - tail_price_position(T-1) | 尾盘位置变化：回升=买盘进场 | tail_price_position | 不预判（H5） |
| `tail_volume_shrink_delta` | tail_volume_shrink(T) - tail_volume_shrink(T-1) | 尾盘缩量变化：缩量减少=放量 | tail_volume_shrink | 不预判（H5） |

**计算规则**：
- 按 `asset` 分组 `shift(1)` 获取前一日值
- 第一日无前值 → NaN（自然排除，不做填充）
- 原始因子为 NaN 时 → delta 也为 NaN（传播而非填充）

---

## 2. 文件修改清单

### Phase 1: 数据层

| # | 文件 | 修改内容 | 行数预估 |
|---|------|---------|---------|
| 1.1 | `data_fetchers/factor_calculator.py` | 新增4个 `calculate_*_delta()` 函数，每个约50行 | ~200 |
| 1.2 | `data_fetchers/factor_generator.py` | `_EXTENDED_FACTOR_COLS` 添加4列名 | ~4 |
| 1.3 | `data_fetchers/factor_generator.py` | 导入4个新函数 + 4个Step计算步骤 + metadata | ~80 |
| 1.4 | `data_fetchers/factor_generator.py` | 版本历史 | ~8 |

### Phase 2: IC脚本

| # | 文件 | 修改内容 | 行数预估 |
|---|------|---------|---------|
| 2.1 | `factor_ic/ic_amplitude_delta_1d.py` | 新建，参照 ic_amplitude_1d.py 模板 | ~160 |
| 2.2 | `factor_ic/ic_turnover_surge_delta_1d.py` | 新建 | ~160 |
| 2.3 | `factor_ic/ic_tail_price_position_delta_1d.py` | 新建 | ~160 |
| 2.4 | `factor_ic/ic_tail_volume_shrink_delta_1d.py` | 新建 | ~160 |

### Phase 3: 分层回测脚本

| # | 文件 | 修改内容 | 行数预估 |
|---|------|---------|---------|
| 3.1 | `backtest/layered_backtest_amplitude_delta_1d.py` | 新建薄声明Config类 | ~50 |
| 3.2 | `backtest/layered_backtest_turnover_surge_delta_1d.py` | 同上 | ~50 |
| 3.3 | `backtest/layered_backtest_tail_price_position_delta_1d.py` | 同上 | ~50 |
| 3.4 | `backtest/layered_backtest_tail_volume_shrink_delta_1d.py` | 同上 | ~50 |

### Phase 4: 因子映射

| # | 文件 | 修改内容 |
|---|------|---------|
| 4.1 | `comprehensive_factor/common/factor_selector.py` | `FACTOR_NAME_TO_COL_MAP` 添加4映射 |
| 4.2 | `comprehensive_factor/common/weight_engine.py` | `FACTOR_NAME_TO_COL_MAP` 添加4映射 |
| 4.3 | `factor_definitions.py` | `FACTOR_DEFINITIONS` 添加4定义 |

### Phase 5: Pipeline + 报告 + 文档

| # | 文件 | 修改内容 |
|---|------|---------|
| 5.1 | `run_pipeline.py` | STAGE_2/3 SCRIPTS 添加新脚本 |
| 5.2 | `summary/generate_factor_summary_report.py` | DATA_PATHS 添加新路径 |
| 5.3 | PROJECT.md | 新增规范章节 |
| 5.4-5.6 | MODULE.md (3个) | 版本历史 |

---

## 3. 核心计算逻辑

### factor_calculator.py 新增函数

4个差分因子共用同一个计算模式，提取为通用辅助函数减少重复：

```python
def _calculate_delta(
    factor_df: pd.DataFrame,
    base_col: str,
    delta_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """通用差分计算：base_col(T) - base_col(T-1)，按asset分组shift
    
    Args:
        factor_df: 含 date, asset, base_col 的DataFrame
        base_col: 原始因子列名（如 'amplitude'）
        delta_col: 差分因子列名（如 'amplitude_delta'）
        logger_arg: 可选logger
    
    Returns:
        factor_df 新增 delta_col 列
        
    边界处理：
        - 第一日无前值 → NaN（自然排除）
        - 原始因子为 NaN → delta 也为 NaN（传播）
        - 按asset分组shift(1)，不跨股票
    """
    factor_df = factor_df.copy()  # M11: DataFrame参数先copy
    # 按asset分组，按date排序后shift
    factor_df = factor_df.sort_values(['asset', 'date'])
    factor_df[delta_col] = factor_df.groupby('asset')[base_col].shift(1)
    factor_df[delta_col] = factor_df[base_col] - factor_df[delta_col]
    # shift产生的前值列名是临时列，清理
    # NaN传播：base_col或前值为NaN → delta为NaN
    
    valid_count = int(factor_df[delta_col].notna().sum())
    total_count = len(factor_df)
    if logger_arg:
        logger_arg.info(
            "差分因子 %s: 有效=%d (%.2f%%), base_col=%s",
            delta_col, valid_count, valid_count/total_count*100, base_col,
        )
    return factor_df


def calculate_amplitude_delta(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """振幅差分因子：amplitude(T) - amplitude(T-1)
    
    含义：振幅从低开始回升=止跌放量信号，振幅继续下降=闷跌加剧
    
    required_cols: ['date', 'asset', 'amplitude']
    """
    return _calculate_delta(factor_df, 'amplitude', 'amplitude_delta', logger_arg)


def calculate_turnover_surge_delta(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """换手突增差分因子：turnover_surge(T) - turnover_surge(T-1)
    
    含义：换手从低开始增加=市场关注回升，继续下降=无人关注
    
    required_cols: ['date', 'asset', 'turnover_surge']
    """
    return _calculate_delta(factor_df, 'turnover_surge', 'turnover_surge_delta', logger_arg)


def calculate_tail_price_position_delta(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """尾盘位置差分因子：tail_price_position(T) - tail_price_position(T-1)
    
    含义：尾盘从最低价回升=买盘开始进场，继续走低=卖方主导
    
    required_cols: ['date', 'asset', 'tail_price_position']
    """
    return _calculate_delta(factor_df, 'tail_price_position', 'tail_price_position_delta', logger_arg)


def calculate_tail_volume_shrink_delta(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """尾盘缩量差分因子：tail_volume_shrink(T) - tail_volume_shrink(T-1)
    
    含义：尾盘从缩量转放量=资金开始介入，继续缩量=冷清
    
    required_cols: ['date', 'asset', 'tail_volume_shrink']
    """
    return _calculate_delta(factor_df, 'tail_volume_shrink', 'tail_volume_shrink_delta', logger_arg)
```

### factor_generator.py 修改要点

`_EXTENDED_FACTOR_COLS` 添加4列（在各自原始因子之后）：

```python
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    "past_return_1d",
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "return_5d",
    "momentum_strength",
    "overnight_ret",
    "intraday_intensity",
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
    "amplitude_delta",           # v1.40 新增
    "turnover_surge_delta",      # v1.40 新增
    "tail_price_position_delta", # v1.40 新增
    "tail_volume_shrink_delta",  # v1.40 新增
)
```

注意顺序：差分因子必须在原始因子之后计算（依赖原始因子列已存在）。

---

## 4. IC/回测脚本模板

IC脚本参照 `ic_amplitude_1d.py` 模板，关键差异：
- `factor_name` = `amplitude_delta`
- `factor_col` = `amplitude_delta`
- `factor_cols` = `["date", "asset", "amplitude"]`（需要原始因子列）
- `custom_factor_calculation` = `calculate_amplitude_delta`

回测脚本参照 `layered_backtest_amplitude_1d.py` 薄声明模式：
- `factor_name` = `amplitude_delta`
- `layer_descriptions` 使用 percentile 相对语义（禁止固定阈值）
- 传入 `factor_calculator=calculate_amplitude_delta`

---

## 5. 执行顺序

```
Phase 0: ✅ design.md 提交审核（当前步骤）
Phase 1: 数据层（factor_calculator + factor_generator）
  → 运行 factor_generator.py 生成新数据源
  → 验证新因子列存在且非全NaN
Phase 2: IC脚本（4个）
  → 运行IC脚本，检查 ic_mean/icir/p_value
  → 筛选决策：不显著因子淘汰，不再开发回测
Phase 3: 分层回测脚本（仅对IC显著因子）
Phase 4: 因子映射
Phase 5: Pipeline + 报告 + 文档
Phase 6: 验证（ruff + pytest + pipeline + 选股 + 报告）
```

---

## 6. 验证检查清单

| 检查项 | 验证方式 |
|--------|---------|
| 新因子列存在于 factor_ic_data.json.gz | `python -c "import gzip,json; d=json.load(gzip.open(...)); print('amplitude_delta' in d['data'][0])"` |
| 新因子非全NaN | `python -c "..."` 检查 notna 比例 |
| IC结果文件存在 | `ls factor_ic/result/ic_amplitude_delta_1d_*` |
| IC方向由数据决定 | `python -c "json.load(open(...))['factor_direction']"` |
| 回测结果文件存在 | `ls backtest/result/amplitude_delta_*` |
| 因子映射完整 | `python -c "from comprehensive_factor.common.factor_selector import FACTOR_NAME_TO_COL_MAP; print('amplitude_delta' in FACTOR_NAME_TO_COL_MAP)"` |
| Pipeline包含新脚本 | `grep 'delta' run_pipeline.py` |
| ruff通过 | `ruff check .` |
| pytest通过 | `pytest --cov-fail-under=70` |
| 选股结果改善 | 检查新报告中Top10是否包含止跌反弹股而非闷跌股 |

---

## 7. 触及的H规则

| 规则编号 | 规则 | 本次涉及 |
|---------|------|---------|
| H1 | 模块边界 | factor_calculator在data_fetchers内 ✓ |
| H2 | 输出位置 | result/ ✓ |
| H5 | 因子方向不预判 | delta因子IC方向由数据决定 ✓ |
| H7 | 路径导入 | from paths import ✓ |
| H8 | Design-First | 本文件 ✓ |
| H9 | 任务粒度 | Phase拆分，单Phase≤3文件≤200行 ✓ |
| H10 | 测试覆盖率 | ≥60%（当前阶段） ✓ |