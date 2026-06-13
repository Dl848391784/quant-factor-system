# Design: 选股前置最低振幅阈值 + Top N 从 3 改为 10

> 日期: 2026-06-11
> 状态: Plan

## 背景

当前选股结果（Top 3）推荐的股票振幅均为 0.0 或接近 0.0，属于一字板涨停股：
- 实际无法买入（全天封板无成交机会）
- 若涨停打开则趋势反转，恰恰是卖点

根本原因：因子体系偏好"低振幅+低换手率"特征，而一字板涨停股在这些因子上是"完美匹配"，但实际可操作性为零。

## 数据验证

最新日期(2026-06-10)振幅分布：
- 振幅=0: 4只（一字板涨停）
- 振幅<0.01: 12只（0.4%，接近一字板）
- 振幅<0.02: 238只（7.9%，偏小波动）
- 振幅均值: 0.046, 中位数: 0.040

## 变更方案

### 变更 1：选股前置最低振幅阈值

**阈值选择**: `min_amplitude = 0.01`（1%）
- 排除振幅 <1% 的股票（12只/0.4%），这些基本是一字板或接近一字板
- 不排除振幅 1%-2% 的正常低波动股（如238只中有226只振幅在1%-2%之间，正常可交易）
- 阈值不宜过大（0.02会排除7.9%正常股）或过小（0只排除纯一字板，但接近一字板同样不可操作）

**实现位置**: `sort_and_select()` 函数，在覆盖率过滤之后、排序之前

**实现方式**:
```python
# 在 StockSelectorConfig 中新增:
min_amplitude: float = 0.01  # 最低振幅阈值（排除不可交易的一字板涨停股）

# 在 sort_and_select() 中新增参数:
min_amplitude: float = 0.01  # 最低振幅阈值

# 过滤逻辑（在 valid_mask 构建阶段）:
if min_amplitude > 0 and 'amplitude' in result_df.columns:
    amplitude_mask = result_df['amplitude'] >= min_amplitude
    excluded_by_amplitude = int(valid_mask.sum() - (valid_mask & amplitude_mask).sum())
    if excluded_by_amplitude > 0:
        logger.info(
            "振幅过滤: 排除 %d 只股票（振幅 < %.2f%%，一字板或接近一字板涨停股不可买入）",
            excluded_by_amplitude,
            min_amplitude * 100,
        )
    valid_mask = valid_mask & amplitude_mask
```

**CLI 参数**:
```python
parser.add_argument(
    "--min_amplitude",
    type=float,
    default=0.01,
    help="最低振幅阈值（默认: 0.01=1%%，排除不可交易的一字板涨停股）",
)
```

**结果 JSON 新增字段**:
```json
"meta": {
    "min_amplitude": 0.01,
    "excluded_by_amplitude": 8,  // 振幅过滤排除的股票数
    ...
}
```

**报告展示**: 在"八、股票选股结果"中新增振幅过滤说明行

### 变更 2：Top N 从 3 改为 10

**修改位置**:
- `StockSelectorConfig.top_n`: 3 → 10
- CLI `--top_n` default: 3 → 10
- MODULE.md 示例更新

## 涉及文件清单

| 文件 | 改动类型 | 改动量 |
|------|---------|--------|
| comprehensive_factor/stock_selector.py | 新增 min_amplitude 参数 + 过滤逻辑 + top_n 默认值 | ~50行 |
| comprehensive_factor/MODULE.md | 更新选股规范 + 输出模板 + 版本历史 | ~30行 |
| summary/generate_factor_summary_report.py | 报告展示振幅过滤信息 | ~20行 |

总计: 3 文件，~100行 ≤ 200行上限 ✓

## 规范引用

- PROJECT.md 规则 #5: 因子方向根据实际 IC 确定
- PROJECT.md 规则 #2: 输出位置 `<模块>/result/`
- AGENTS.md Design-First: 2+文件先提交 design.md
- AGENTS.md 任务粒度: ≤3 文件 ≤200 行

## 验证计划

1. 运行 `python comprehensive_factor/stock_selector.py --top_n 10` 验证选股结果
2. 确认振幅<0.01的股票被排除
3. 运行 `python summary/generate_factor_summary_report.py` 验证报告展示
4. pytest 验证测试通过
5. ruff check + mypy 验证代码规范