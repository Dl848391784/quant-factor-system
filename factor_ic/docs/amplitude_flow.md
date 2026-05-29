# 振幅因子实现流程

> 创建时间: 2026-05-29
> 状态: 已完成

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
- 实测范围: 0.00 ~ 0.23，均值 0.04

### 边界处理
- close = 0 时：设为 NaN（无效数据）
- high = low 时：振幅为 0（一字涨停/跌停）

## 实现文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 因子计算函数 | `data_fetchers/factor_calculator.py` | `calculate_amplitude()` 函数 |
| IC 计算脚本 | `factor_ic/ic_amplitude_1d.py` | 使用 `run_complex_factor_ic()` |
| 分层回测脚本 | `backtest/layered_backtest_amplitude_1d.py` | 使用 `run_layered_backtest()` |
| 实现计划 | `factor_ic/docs/plans/ic_amplitude_1d_plan.md` | 计划文档 |

## 运行命令

```bash
# IC 计算
python factor_ic/ic_amplitude_1d.py --force-full

# 分层回测
python backtest/layered_backtest_amplitude_1d.py
```

## IC 分析结果

| 指标 | 值 | 说明 |
|------|------|------|
| IC 均值 | -0.0591 | 负相关（高振幅 → 低收益） |
| IC 标准差 | 0.1689 | |
| ICIR | 0.35 | 稳定性一般 |
| t 统计量 | -8.89 | 统计显著（p < 0.05） |
| 有效天数 | 514 | |
| 数据范围 | 2024-02-26 ~ 2026-05-27 | 545 个交易日 |

## 分层回测结果

| 分层 | 股票数 | 日均收益 | 年化收益 | 夏普比 | 换手率 |
|------|--------|---------|---------|--------|--------|
| Layer1 (低振幅) | 577 | 0.10% | 24.83% | 1.34 | 51.1% |
| Layer2 (偏低) | 577 | 0.10% | 25.25% | 1.18 | 72.1% |
| Layer3 (中位) | 577 | 0.12% | 31.02% | 1.35 | 74.6% |
| Layer4 (偏高) | 577 | 0.12% | 31.23% | 1.27 | 72.0% |
| Layer5 (高振幅) | 578 | 0.02% | 4.69% | 0.18 | 50.3% |

### 多空组合表现

| 指标 | 值 |
|------|------|
| 多头年化收益 | 24.75%（Layer1+Layer2） |
| 空头年化收益 | 17.75%（Layer4+Layer5） |
| 多空年化收益 | 6.99% |
| 夏普比率 | 0.61 |
| 单调性相关系数 | -0.4977（moderate） |

### 因子方向

- **negative**：低振幅股票做多，高振幅股票做空
- 经济含义：波动平稳的股票未来收益更高

## 筛选评估

| 指标 | 值 | 标准 | 结论 |
|------|------|------|------|
| |ic_mean| | 0.0591 | ≥ 0.03 | ✓ 通过 |
| |icir| | 0.35 | ≥ 0.15 | ✓ 通过 |
| |monotonicity_corr| | 0.4977 | ≥ 0.4 | ✓ 通过 |
| long_short_return | 6.99% | ≥ 3% | ✓ 通过 |

**结论：振幅因子通过全部筛选标准，可纳入综合因子候选池。**

## 路径修复

在实现过程中发现 `data_completeness.py` 使用了错误的路径配置：
- 旧路径：`cache/factor_data/factor_data.json.gz`
- 新路径：`data_fetchers/result/factor_ic_data.json.gz`

已修复：
- `FACTOR_DATA_DIR` 从 `cache/factor_data` 改为 `data_fetchers/result`
- 文件名从 `factor_data.json.gz` 改为 `factor_ic_data.json.gz`