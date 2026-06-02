# 尾盘量价强度因子 IC 计算流程文档

> 版本: v1.0
> 创建时间: 2026-06-02 15:15 北京时间

## 概述

尾盘量价强度因子 IC 计算脚本 (`ic_tail_price_volume_intensity.py`) 计算尾盘量价强度因子与次日收益的信息系数。

## 因子定义

**公式**：
- 尾盘涨跌幅 = `(prices[-1] - prices[0]) / prices[0]`
- 尾盘量比 = `sum(volumes) / volume`
- 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

**含义**：
- 正值 → 尾盘上涨且成交量放大（资金流入）
- 负值 → 尾盘下跌且成交量放大（资金流出）

## 数据依赖

| 数据源 | 文件路径 | 字段 |
|--------|----------|------|
| 尾盘数据 | `data_fetchers/result/tail_trading_data.json.gz` | `date`, `asset`, `prices`, `volumes` |
| 主数据源 | `data_fetchers/result/factor_ic_data.json.gz` | `date`, `asset`, `volume`, `forward_return_1d` |

## 运行方式

```bash
cd /home/admin/projects/factor_ic_analyzer
python3 -m factor_ic.ic_tail_price_volume_intensity

# 强制全量计算
python3 -m factor_ic.ic_tail_price_volume_intensity --force-full
```

## 输出文件

- **路径**: `factor_ic/result/ic_tail_price_volume_intensity_1d_analysis_result.json`
- **格式**: JSON（MODULE.md 定义）

## 实测结果

> 待运行后补充