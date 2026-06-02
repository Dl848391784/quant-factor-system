# layered_backtest_tail_price_position_1d.py 流程文档

> 版本: v1.0
> 创建时间: 2026-06-02
> 更新时间: 2026-06-02 16:44 北京时间

---

## 概述

**脚本用途：** 对尾盘价格位置因子进行分层回测，验证因子在不同分层的收益表现。

**因子定义：**
- 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)
- 收盘价 = prices[-1]（尾盘最后一根K线收盘价）
- 含义：收盘价在尾盘价格区间的相对位置，理论范围 [0, 1]

**分层模式：** percentile 5层（每层约20%）

**核心策略：**
1. 薄声明模式：仅定义 factor_name 和 layer_names
2. 因子方向派生：从 IC 文件自动派生（ic_mean < 0 为 negative）
3. 公共模块复用：因子计算复用 ic_tail_price_position.calculate_tail_price_position

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│               TailPricePositionLayerConfig                   │
│  薄声明：仅定义 factor_name + layer_names                    │
│  其他属性由基类 LayerConfigBase 派生                          │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│                factor_cli_main()                             │
│  1. 加载配置                                                 │
│  2. 检测 IC 文件派生因子方向                                  │
│  3. 调用 run_layered_backtest()                              │
│  4. 输出结果摘要                                             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│              run_layered_backtest()                          │
│  1. 加载因子数据                                             │
│  2. 执行因子计算                                             │
│  3. 分层（percentile 5层）                                   │
│  4. 计算各层收益                                             │
│  5. 保存结果                                                 │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────┐
│ calculate_tail_price_ │
│ position()           │
│ 因子计算函数         │
└──────────────────────┘
```

---

## 配置参数

| 参数 | 值 | 说明 |
|------|-----|------|
| factor_name | tail_price_position | 因子名称 |
| layer_names | 5层 | lowest/lower/normal/higher/highest |
| factor_direction | negative | 从 IC 文件派生（ic_mean=-0.0613） |
| n_layers | 5 | 由 len(layer_names) 派生 |

---

## 分层定义

| Layer | 名称 | 含义 | percentile范围 |
|-------|------|------|----------------|
| 1 | 极低层 | 价格位置≈0，收盘在区间底部 | 0-20% |
| 2 | 偏低层 | 价格位置偏低 | 20-40% |
| 3 | 正常层 | 价格位置适中≈0.5 | 40-60% |
| 4 | 偏高层 | 价格位置偏高 | 60-80% |
| 5 | 极高层 | 价格位置≈1，收盘在区间顶部 | 80-100% |

---

## 数据依赖

| 数据文件 | 字段 | 来源模块 |
|---------|------|----------|
| factor_ic_data.json.gz | date, asset, return | data_fetchers/fetch_factor_cache.py |
| tail_trading_data.json.gz | date, asset, prices, tail_high, tail_low | data_fetchers/fetch_tail_trading.py |

---

## 输出位置

- **结果文件：** `backtest/result/tail_price_position_layered_backtest.json`
- **每日详情：** `backtest/result/tail_price_position_layered_backtest_daily.json.gz`

---

## 回测结果摘要（2026-06-02）

| 指标 | 值 |
|------|-----|
| 回测周期 | 11天 |
| Layer1 累计收益 | -2.55% |
| Layer2 累计收益 | -2.84% |
| Layer3 累计收益 | -4.39% |
| Layer4 累计收益 | -4.99% |
| Layer5 累计收益 | -7.20% |

**因子方向说明：** negative 因子，Layer5（极高层）收益最负，符合因子逻辑。

---

## 版本历史

1. v1.0 (2026-06-02): 初始版本，创建流程文档