# Design: 全链路排除不可交易股票（涨停类）

> 日期: 2026-06-19
> 触发规则: H8（2+ 文件需 design.md）、H9（超粒度需拆分）
> 数据依据: `temporary/backtest_untradeable_impact.py` 回测对比结果

---

## 1. 背景与数据依据

### 1.1 问题

交易模型: T-1 算因子 → T 尾盘买入 → T+1 尾盘卖出。

T 日涨停（一字板/尾盘封板）的股票无法在 T 日尾盘买入，但当前 IC 计算和分层回测将其视为可交易股票，导致：

- 涨停股票集中在空头层（7/9 因子偏向高值=空头方向）
- 涨停股票 forward_return 显著为正（均值 1.98% vs 正常 0.04%，t=24.35，p≈0）
- 空头层收益被人为抬高 → 多空收益被压缩

### 1.2 回测对比数据

| 因子 | Pool A 年化 | Pool B 年化 | 差异 | Pool A 夏普 | Pool B 夏普 |
|------|-----------|-----------|------|-----------|-----------|
| momentum_strength | 5.13% | 23.48% | +18.35pp | 0.517 | 2.447 |
| volume_ratio_5 | 15.46% | 18.19% | +2.73pp | 1.897 | 2.298 |
| tail_price_position | 43.02% | 72.20% | +29.18pp | 5.475 | 9.672 |

三个因子年化收益变化均 >5%，按预定标准走全链路过滤方案。

### 1.3 不可交易判定标准

**仅涨停类（T 日买不进），不含跌停类（T 日可买，T+1 跌停是持仓风险不可预知）**

| 类型 | 判定条件 | 所需列 |
|------|---------|--------|
| 一字板涨停 | amplitude < 0.01 且 涨幅 ≥ 0.098 | amplitude, close, prev_close |
| 尾盘涨停 | 涨幅 ≥ 0.098 且 close == high（排除一字板） | close, high, prev_close |

涨幅 = (close - prev_close) / prev_close，其中 prev_close = groupby(asset).close.shift(1)

---

## 2. 方案设计

### 2.1 核心思路

在 `factor_generator.py` 生成 `factor_ic_data.json.gz` 时新增 `is_untradeable` 布尔列。各下游模块读取此列进行过滤，避免每个模块重复计算。

### 2.2 列归属

新增 `_FLAG_COLS` 类别，独立于 `_BASE_COLS` / `_EXTENDED_FACTOR_COLS` / `_RETURN_COLS`：

```python
_FLAG_COLS: tuple[str, ...] = ("is_untradeable",)
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS + _FLAG_COLS
```

JSON 中存储为 `0` / `1`（整数），避免 bool 序列化问题。

### 2.3 计算位置

在 `_run_factor_pipeline` 之后、`_format_and_write_output` 之前新增一步：

```
Step 11.10: 标记不可交易股票
  - 输入: factor_df（已含 amplitude, close, high + 基础列）
  - 计算: prev_close = groupby(asset).close.shift(1)
  - 计算: pct_change = (close - prev_close) / prev_close
  - 标记: is_untradeable = 一字板涨停 | 尾盘涨停
  - 输出: factor_df 新增 is_untradeable 列
```

### 2.4 下游过滤方式

| 模块 | 过滤位置 | 过滤逻辑 |
|------|---------|---------|
| factor_ic | `data_loader.py` load_factor_return_data | 返回前 `df = df[~df['is_untradeable'].astype(bool)]` |
| backtest | `layered_backtest_runner.py` load_factor_return_data | 同上 |
| comprehensive_factor | `factor_loader.py` load_full_data | 同上（可选参数控制） |
| stock_selector | `stock_selector.py` select_stocks | 用 `is_untradeable` 替代 `amplitude < 0.01` 过滤 |

**向后兼容**：如果数据源中无 `is_untradeable` 列（旧数据），不过滤，日志 warning。

---

## 3. 决策矩阵

| 决策点 | 方案 | 来源 |
|--------|------|------|
| 不可交易范围 | 仅涨停类（不含跌停） | 用户确认（2026-06-19）：T 日跌停可买，T+1 跌停不可预知 |
| 列存储格式 | 整数 0/1 | JSON bool 序列化兼容性 |
| 列归属 | 新增 `_FLAG_COLS` 类别 | 不污染 `_BASE_COLS`（行情）和 `_EXTENDED_FACTOR_COLS`（因子） |
| 计算位置 | factor_generator 管线 Step 11.10 | 统一数据源原则，单一计算点 |
| 下游过滤 | 各模块 data_loader 层 | 对业务逻辑透明，IC/backtest 引擎无需改动 |
| 向后兼容 | 旧数据无列则不过滤 | 避免强制全量重跑才能使用 |
| stock_selector | 用 is_untradeable 替代 amplitude | 修复当前 amplitude<1% 不区分涨跌的缺陷 |

---

## 4. 任务拆分（H9 粒度控制）

| 子任务 | 文件 | 预估行数 | 依赖 |
|--------|------|---------|------|
| T1: factor_generator 新增 is_untradeable | `data_fetchers/factor_generator.py` + test | ~80 行 | 无 |
| T2: factor_ic 数据加载过滤 | `factor_ic/common/data_loader.py` + test | ~30 行 | T1 |
| T3: backtest 数据加载过滤 | `backtest/common/layered_backtest_runner.py` + test | ~30 行 | T1 |
| T4: comprehensive_factor 过滤 + stock_selector 修复 | `comprehensive_factor/common/factor_loader.py` + `stock_selector.py` + test | ~60 行 | T1 |
| T5: 全量重跑 + 新旧对比 | 脚本（temporary/） | — | T1-T4 |

每个子任务 ≤3 文件 ≤200 行，独立可提交。

---

## 5. 验证方案

### 5.1 单元测试

- T1: 验证 `is_untradeable` 标记正确（构造一字板/尾盘涨停/正常股票测试数据）
- T2-T4: 验证过滤后数据不含 `is_untradeable=1` 的行
- T4: 验证 stock_selector 用 `is_untradeable` 过滤而非 `amplitude < 0.01`

### 5.2 集成验证

- T1 完成后重新生成 `factor_ic_data.json.gz`，验证列存在且值正确
- T5 全量重跑后对比新旧 IC/回测/选股结果

### 5.3 回测对比预期

- 多空年化收益应增大（空头层不再含涨停溢价）
- 夏普比率应增大
- 单调性可能变化

---

## 6. 风险

| 风险 | 缓解 |
|------|------|
| 全量重跑耗时数小时 | 分步执行，每步验证 |
| 历史结果被覆盖 | T5 前备份 result/ 目录 |
| is_untradeable 计算依赖 prev_close | 首日数据 prev_close=NaN → is_untradeable=0（保守不过滤） |
| stock_selector 行为变化 | 原 amplitude<1% 过滤被替代，需确认不影响现有测试 |
