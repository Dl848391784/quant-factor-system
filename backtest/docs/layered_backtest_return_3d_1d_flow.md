# 3日累计涨幅因子分层回测流程文档

**创建日期**: 2026-06-01
**因子名称**: return_3d_1d
**因子方向**: 反向因子（ic_mean < 0）

---

## 1. 因子概述

### 1.1 因子定义

3日累计涨幅因子衡量过去3日的价格变化程度：

```
return_3d = close[t] / close[t-3] - 1
```

其中：
- 因子需要实时计算，不在统一数据源中预计算
- 理论范围: [-0.3, 0.3]（A股日涨跌幅±10%）

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | [-0.3, 0.3]（A股涨跌幅限制） |
| 正常值 | ≈ 0（3日累计涨跌幅接近0） |
| 涨幅信号 | > 0（过去3日上涨） |
| 跌幅信号 | < 0（过去3日下跌） |

### 1.3 IC 分析结果

来源：`factor_ic/result/ic_return_3d_1d_analysis_result.json`

**结论**: 因子方向由实测 IC 确定，遵循 PROJECT.md 规范。

---

## 2. 分层配置

### 2.1 分层模式

**percentile 5层（每层20%）** - 遵循 PROJECT.md v1.5 规范

| Layer | percentile范围 | 名称 | 含义 |
|-------|---------------|------|------|
| 1 | 0-20% | 极低层(3日跌幅最大) | 过去3日跌幅最大 |
| 2 | 20-40% | 偏低层(3日小幅下跌) | 过去3日小幅下跌 |
| 3 | 40-60% | 正常层(3日变化不大) | 过去3日变化接近0 |
| 4 | 60-80% | 偏高层(3日小幅上涨) | 过去3日小幅上涨 |
| 5 | 80-100% | 极高层(3日涨幅最大) | 过去3日涨幅最大 |

### 2.2 多空组合

多空组合由基类根据 factor_direction 自动派生：

- 正向因子：做多高值组（Layer 4-5），做空低值组（Layer 1-2）
- 反向因子：做多低值组（Layer 1-2），做空高值组（Layer 4-5）

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 数据加载

### 3.1 数据来源

return_3d 因子需要实时计算：

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 统一数据源 | factor_ic_data.json.gz | date, asset, close, forward_return_1d |

**注意**: return_3d 需通过 factor_calculator 实时计算。

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_return_3d_1d.py
```

### 4.2 核心特点

- **薄声明**: 仅定义 factor_name + layer_names ClassVar
- **需计算因子**: 传入 factor_calculator=calculate_return_3d
- **因子方向派生**: factor_direction 从 IC 文件派生

---

## 5. 输出结果

### 5.1 输出文件

遵循 PROJECT.md 输出目录规范，结果输出到 `backtest/result/`：

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/return_3d_layered_backtest.json` |
| 每日明细 | `backtest/result/return_3d_layered_backtest_daily.json.gz` |

---

## 6. 规范遵循

### 6.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

### 6.2 输出目录规范

遵循 `PROJECT.md`:
- 结果输出到 `backtest/result/` 目录

### 6.3 公共模块复用

遵循 `MODULE.md` 公共模块复用规范:
- 使用 factor_cli_main 公共入口
- 使用 LayerConfigBase 基类
- 使用 calculate_return_3d 因子计算函数

---

## 7. 注意事项

### 7.1 因子方向

因子方向不可预判，必须根据实际 IC 测试结果确定。

### 7.2 因子计算时机

return_3d 需要实时计算，不在缓存中预计算。

---

## 8. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-01 | v1.0 | 创建流程文档 |