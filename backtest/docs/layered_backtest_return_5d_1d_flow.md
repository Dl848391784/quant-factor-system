# 5日累计涨幅因子分层回测流程文档

**创建日期**: 2026-06-01
**最后更新**: 2026-06-01 (v1.23架构适配)
**因子名称**: return_5d_1d
**因子方向**: 反向因子（ic_mean = -0.033657）

---

## 1. 因子概述

### 1.1 因子定义

5日累计涨幅因子衡量过去5日的价格变化程度：

```
return_5d = close[t] / close[t-5] - 1
```

其中：
- 因子需要实时计算，不在统一数据源中预计算
- 理论范围: [-0.5, 0.5]（A股日涨跌幅±10%）

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | [-0.5, 0.5]（A股涨跌幅限制） |
| 实测范围 | -0.25 ~ 0.35 |
| 正常值 | ≈ 0（5日累计涨跌幅接近0） |
| 涨幅信号 | > 0（过去5日上涨） |
| 跌幅信号 | < 0（过去5日下跌） |

### 1.3 IC 分析结果

```json
{
  "ic_mean": -0.033657,
  "icir": 0.2845,
  "p_value": 1.2e-12
}
```

**结论**: IC 绝对值 > 0.03，有一定预测能力，统计显著。

---

## 2. 分层配置

### 2.1 分层模式

**percentile 5层（每层20%）** - 遵循 PROJECT.md v1.5 规范

| Layer | percentile范围 | 名称 | 含义 |
|-------|---------------|------|------|
| 1 | 0-20% | 极低层(5日涨幅最小) | 过去5日跌幅最大 |
| 2 | 20-40% | 偏低层(5日小幅下跌) | 过去5日小幅下跌 |
| 3 | 40-60% | 正常层(5日变化不大) | 过去5日变化接近0 |
| 4 | 60-80% | 偏高层(5日小幅上涨) | 过去5日小幅上涨 |
| 5 | 80-100% | 极高层(5日涨幅最大) | 过去5日涨幅最大 |

### 2.2 多空组合

```python
factor_direction = 'negative'  # 反向因子（ic_mean < 0）
long_layers = [1, 2]   # 做多跌幅组（低值层）
short_layers = [4, 5]  # 做空涨幅组（高值层）
```

策略逻辑（运行时派生）：
- factor_direction='negative'（从 IC 文件派生，ic_mean=-0.033657）
- long_layers=[1,2]（做多跌幅组）
- short_layers=[4,5]（做空涨幅组）

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 数据加载

### 3.1 数据来源

return_5d 因子需要实时计算：

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 统一数据源 | factor_ic_data.json.gz | date, asset, close, forward_return_1d |

**注意**: return_5d 需通过 factor_calculator 实时计算。

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_return_5d_1d.py
```

### 4.2 核心特点（v1.23 理想形态）

- **薄声明**: 仅定义 factor_name + layer_names ClassVar
- **需计算因子**: 传入 factor_calculator=calculate_return_5d
- **反向因子配置**: factor_direction='negative'（基类从 IC 文件派生）

```python
class Return5dLayerConfig(LayerConfigBase):
    """5日收益因子分层配置"""
    
    factor_name: ClassVar[str] = 'return_5d'
    # ic_source: ClassVar[str] = 'factor_ic/result/ic_return_5d_1d_analysis_result.json'
    #   可选显式声明以暴露派生路径；未声明时基类按 factor_name 拼接默认路径
    
    layer_names: ClassVar[Sequence[str]] = (
        '极低层(5日涨幅最小)',
        '偏低层(5日小幅下跌)',
        '正常层(5日变化不大)',
        '偏高层(5日小幅上涨)',
        '极高层(5日涨幅最大)'
    )

if __name__ == '__main__':
    factor_cli_main(
        config_cls=Return5dLayerConfig,
        factor_calculator=calculate_return_5d
    )
```

---

## 5. 输出结果

### 5.1 输出文件

遵循 PROJECT.md 输出目录规范，结果输出到 `backtest/result/`：

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/return_5d_layered_backtest.json` |
| 每日明细 | `backtest/result/return_5d_layered_backtest_daily.json.gz` |

### 5.2 回测结果摘要（2026-06-01 运行）

| 指标 | 值 |
|------|-----|
| 回测天数 | 515 天 |
| 股票数量 | 577 只/层 |
| 分层模式 | percentile 5层 |
| 多头年化收益 | 28.5% |
| 空头年化收益 | 11.2% |
| 多空年化收益 | 17.3% |
| 多空夏普比率 | 2.1 |
| 单调性相关系数 | -0.85 (good) |

---

## 6. 分层效果评估

### 6.1 单调性分析

- 单调性相关系数 -0.85（good）
- 反向因子单调性良好：Layer 1→5 收益递减（符合预期）
- Layer 1 (跌幅最大) 累计收益 78%，Layer 5 (涨幅最大) 累计收益 5%

### 6.2 结论

return_5d 因子表现良好：
- 单调性良好，分层效果显著
- 跌幅组（Layer 1,2）表现优于涨幅组
- IC 绝对值较小（-0.03），但分层收益差异明显

---

## 7. 规范遵循

### 7.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

### 7.2 输出目录规范

遵循 `PROJECT.md`:
- 结果输出到 `backtest/result/` 目录

### 7.3 数据加载规范

遵循 PROJECT.md 数据完整性校验规范：
- 校验文件存在
- 校验 JSON 解析
- 校验结构完整性

---

## 8. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-01 | v1.23 | 移除 docstring 中 factor_direction 预判，修复损坏文档 |
| 2026-06-01 | v1.22 | 适配 ClassVar[Sequence[str]] 架构 |
| 2026-06-01 | v1.0 | 初始版本，创建 return_5d 分层回测脚本 |