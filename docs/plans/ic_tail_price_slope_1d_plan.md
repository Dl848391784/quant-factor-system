# 尾盘价格趋势斜率因子 IC 脚本开发计划

> 创建时间: 2026-06-02 16:30 北京时间
> 状态: 待用户审核

## 1. 目标

开发 `ic_tail_price_slope_1d.py` 脚本，计算尾盘价格趋势斜率因子的 IC。

## 2. 因子定义

**公式**：
```python
import numpy as np

# prices: 13根5分钟K线收盘价（14:00-15:00）
X = np.arange(13)  # 时间索引: 0, 1, 2, ..., 12
Y = np.array(prices)

# 线性回归
slope, intercept = np.polyfit(X, Y, 1)

# 百分比斜率（消除价格量纲差异）
mean_price = np.mean(prices)
factor_value = slope / mean_price
```

**含义**：
- `tail_price_slope > 0`：尾盘价格上涨趋势
- `tail_price_slope < 0`：尾盘价格下跌趋势
- `|tail_price_slope|` 越大：趋势越强劲

**归一化处理**：百分比斜率（slope / mean_price），消除高价股和低价股的量纲差异，与 forward_return（百分比形式）可比。

**边界处理**：
- `prices` 数组长度不足13时设为 NaN（数据不完整）
- `mean_price` 接近零时设为 NaN（除零防护）
- `prices` 包含 NaN/None 时返回 NaN（数据污染）

## 3. 数据依赖

| 数据源 | 文件路径 | 需要字段 |
|--------|----------|----------|
| 尾盘数据 | `data_fetchers/result/tail_trading_data.json.gz` | `date`, `asset`, `prices` |
| 主数据源 | `data_fetchers/result/factor_ic_data.json.gz` | `date`, `asset`, `forward_return_1d` |

**数据合并方式**：
- 使用 `additional_factor_files` 参数传入尾盘数据路径
- 在 `custom_factor_calculation` 函数内合并（按 date, asset）
- 参考 `ic_tail_price_volume_intensity_plan.md` 的合并方案

## 4. 实现方案

### 4.1 使用公共模块

使用 `run_complex_factor_ic` 公共模块（参考 `ic_overnight_ret_1d.py` 模板）。

### 4.2 自定义因子计算函数

```python
def calculate_tail_price_slope(factor_df, tail_data_path):
    """
    计算尾盘价格趋势斜率因子
    
    Args:
        factor_df: 主数据源 DataFrame（date, asset, forward_return_1d）
        tail_data_path: 尾盘数据路径
    
    Returns:
        DataFrame，新增 'tail_price_slope' 列
    """
    # 1. 加载尾盘数据
    # 2. 合并到 factor_df（按 date, asset）
    # 3. 对每个股票的 prices 数组做线性回归
    # 4. 计算百分比斜率
    # 5. 边界处理
    return factor_df
```

### 4.3 参数配置

```python
result = run_complex_factor_ic(
    factor_name='tail_price_slope',
    factor_col='tail_price_slope',
    factor_cols=['date', 'asset'],  # 主数据源基础列
    custom_factor_calculation=calculate_tail_price_slope,
    additional_factor_files={'tail_data': get_tail_data_path()},
    min_stocks=10,
    force_full=args.force_full,
    _logger=logger
)
```

## 5. 文件清单

| 文件 | 类型 | 位置 |
|------|------|------|
| 因子脚本 | Python | `factor_ic/ic_tail_price_slope_1d.py` |
| 流程文档 | Markdown | `factor_ic/docs/ic_tail_price_slope_1d_flow.md` |
| pytest测试 | Python | `factor_ic/test_cases/test_ic_tail_price_slope_1d.py` |
| 测试用例文档 | Markdown | `factor_ic/test_cases/ic_tail_price_slope_1d_test_cases.md` |

## 6. 开发流程

按照 `superpowers-workflow` 4阶段流程：

### Phase 1: Plan（当前阶段）
- [x] 读取 AGENTS.md
- [x] 加载 superpowers-workflow skill
- [x] 查询 codegraph 知识图谱
- [x] 读取 PROJECT.md 了解规范
- [x] 分析参考脚本结构
- [x] 创建开发计划文档
- [ ] **用户审核通过**

### Phase 2: Execute
- 创建因子脚本（参考 ic_overnight_ret_1d.py）
- 创建流程文档（参考 ic_overnight_ret_1d_flow.md）
- 创建 pytest 测试文件
- 创建测试用例文档
- 运行脚本验证输出
- 运行 pytest 验证测试通过

### Phase 3: Review
- ruff check --fix + ruff format
- pytest --cov-fail-under=70
- Spec Compliance 检查（对照 PROJECT.md）
- Code Quality 检查
- 流程文档一致性检查

### Phase 4: Debug（如有问题）
- 加载 systematic-debugging skill
- 根因分析 → 修复 → 验证

## 7. 潜在问题

1. **数据合并复杂性**：需要从两个数据源合并数据（tail_trading_data + factor_ic_data）
2. **数据完整性**：tail_trading_data 只有约12天数据，可能影响 IC 计算样本量
3. **prices 数组处理**：需要对每个股票的 prices 数组应用线性回归（apply 或 loop）

## 8. 参考文件

- 参考1：`factor_ic/ic_overnight_ret_1d.py`（复杂因子模板）
- 参考2：`docs/plans/ic_tail_price_volume_intensity_plan.md`（尾盘因子合并方案）
- 参考3：`factor_ic/docs/ic_overnight_ret_1d_flow.md`（流程文档模板）
- 参考4：`factor_ic/test_cases/test_ic_overnight_ret_1d.py`（pytest模板）
- 参考5：`factor_ic/test_cases/ic_overnight_ret_1d_test_cases.md`（测试用例文档模板）
- 参考6：`data_fetchers/docs/fetch_tail_trading_flow.md`（尾盘数据结构）

---

**请用户审核后继续 Execute 阶段。**