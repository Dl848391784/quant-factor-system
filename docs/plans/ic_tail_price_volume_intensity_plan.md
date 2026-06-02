# 尾盘量价强度因子 IC 脚本开发计划

> 创建时间: 2026-06-02 15:10 北京时间
> 状态: 待用户审核

## 1. 目标

开发 `ic_tail_price_volume_intensity.py` 脚本，计算尾盘量价强度因子的 IC。

## 2. 因子定义

**公式**：
- 尾盘涨跌幅 = `(prices[-1] - prices[0]) / prices[0]`
- 尾盘量比 = `sum(volumes) / volume`（尾盘成交量 / 全天成交量）
- 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

**含义**：
- 正值 → 尾盘上涨且成交量放大（资金流入）
- 负值 → 尾盘下跌且成交量放大（资金流出）
- 绝对值大 → 尾盘量价异动显著

**边界处理**：
- `prices[0]` 接近零时设为 NaN（除零防护）
- `volume` 接近零时设为 NaN（除零防护）
- `volumes` 数组长度不足 13 时设为 NaN（数据不完整）

## 3. 数据依赖

| 数据源 | 文件路径 | 需要字段 |
|--------|----------|----------|
| 尾盘数据 | `data_fetchers/result/tail_trading_data.json.gz` | `date`, `asset`, `prices`, `volumes` |
| 主数据源 | `data_fetchers/result/factor_ic_data.json.gz` | `date`, `asset`, `volume`, `forward_return_1d` |

## 4. 实现方案

### 4.1 使用公共模块

使用 `run_complex_factor_ic` 公共模块（参考 ic_overnight_ret_1d.py 模板）。

### 4.2 自定义因子计算函数

```python
def calculate_tail_price_volume_intensity(factor_df):
    """
    计算尾盘量价强度因子
    
    需要合并尾盘数据（tail_trading_data.json.gz）
    """
    # 1. 加载尾盘数据
    # 2. 合并到 factor_df（按 date, asset）
    # 3. 计算尾盘涨跌幅、尾盘量比
    # 4. 计算尾盘量价强度
    # 5. 处理边界情况
```

### 4.3 文件结构

```
factor_ic/
├── ic_tail_price_volume_intensity.py  # 新建（~200行）
├── docs/
│   └── ic_tail_price_volume_intensity_flow.md  # 新建
├── test_cases/
│   └── ic_tail_price_volume_intensity_test_cases.md  # 新建
│   └── test_ic_tail_price_volume_intensity.py  # 新建（pytest）
```

## 5. 执行步骤

| 步骤 | 任务 | 预计耗时 |
|------|------|----------|
| 1 | 创建 ic_tail_price_volume_intensity.py | 5分钟 |
| 2 | 创建流程文档 ic_tail_price_volume_intensity_flow.md | 3分钟 |
| 3 | 创建测试用例文档 | 2分钟 |
| 4 | 创建 pytest 测试文件 | 5分钟 |
| 5 | 运行脚本验证输出 | 2分钟 |
| 6 | 运行 pytest 测试 | 1分钟 |
| 7 | Git commit | 1分钟 |

## 6. 验证标准

- [ ] 脚本命名符合规范（`ic_<因子名>_1d.py`）
- [ ] 输出文件命名符合规范（`ic_tail_price_volume_intensity_1d_analysis_result.json`）
- [ ] 输出结构包含必需字段（MODULE.md 定义）
- [ ] 流程文档包含时间标注
- [ ] pytest 测试覆盖核心计算逻辑

## 7. 潜在风险

1. **数据合并复杂性**：需要从两个数据源合并数据（tail_trading_data + factor_ic_data）
2. **数据完整性**：tail_trading_data 只有约12天数据，可能影响 IC 计算样本量
3. **公共模块适配**：run_complex_factor_ic 需确认支持多数据源合并

## 8. 待确认事项

1. 因子命名是否为 `tail_price_volume_intensity`？
2. 是否需要其他周期（3d、5d）？
3. 尾盘时段定义是否正确（14:00-15:00）？