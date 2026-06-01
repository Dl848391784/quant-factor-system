# 价格位置因子分层回测流程文档

**创建日期**: 2026-06-01
**最后更新**: 2026-06-01 (v1.25架构适配)
**因子名称**: price_position_1d
**因子方向**: 反向因子（ic_mean = -0.0131）

---

## 1. 因子概述

### 1.1 因子定义

价格位置因子衡量当前价格在过去N日高低点中的相对位置：

```
price_position = (close - low_N) / (high_N - low_N)
```

其中：
- 因子需实时计算，不在统一数据源中预计算
- required_cols: ['close', 'high', 'low']
- 理论范围: [0, 1]

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | [0, 1] |
| 低值含义 | 价格接近N日最低点 |
| 高值含义 | 价格接近N日最高点 |
| 中值含义 | 价格在中位附近 |

### 1.3 IC 分析结果

```json
{
  "ic_mean": -0.013066,
  "icir": 0.098,
  "p_value": 0.0127
}
```

**结论**: IC 绝对值 < 0.03，预测能力较弱，但统计显著（p < 0.05）。

---

## 2. 分层配置

### 2.1 分层模式

**percentile 5层（每层约20%）**

| Layer | percentile范围 | 标签 | 描述 |
|-------|---------------|------|------|
| 1 | 0-20% | lowest | 极低层(接近N日最低) |
| 2 | 20-40% | lower | 偏低层(低于中位) |
| 3 | 40-60% | normal | 正常层(在中位附近) |
| 4 | 60-80% | higher | 偏高层(高于中位) |
| 5 | 80-100% | highest | 极高层(接近N日最高) |

### 2.2 多空组合

```python
factor_direction = 'negative'  # 反向因子（ic_mean < 0）
long_layers = [1, 2]   # 做多低价位
short_layers = [4, 5]  # 做空高价位
```

---

## 3. 数据加载

### 3.1 数据来源

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 统一数据源 | factor_ic_data.json.gz | date, asset, close, high, low, forward_return_1d |

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_price_position_1d.py
```

### 4.2 核心特点（v1.25 理想形态）

- **薄声明**: factor_name/layer_names/layer_descriptions 全部 ClassVar
- **需计算因子**: 传入 factor_calculator=calculate_price_position
- **layer_names**: 纯标签（lowest/lower/...），用于目录/列名
- **layer_descriptions**: 含中文，用于日志显示

```python
class PricePositionLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = 'price_position'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest', 'lower', 'normal', 'higher', 'highest'
    )
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(接近N日最低)', '偏低层(低于中位)',
        '正常层(在中位附近)', '偏高层(高于中位)', '极高层(接近N日最高)'
    )

if __name__ == '__main__':
    factor_cli_main(PricePositionLayerConfig, calculate_price_position)
```

---

## 5. 输出结果

### 5.1 输出文件

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/price_position_layered_backtest.json` |
| 每日明细 | `backtest/result/price_position_layered_backtest_daily.json.gz` |

### 5.2 回测结果摘要（2026-06-01 运行）

| 指标 | 值 |
|------|-----|
| 回测天数 | 515 天 |
| 分层模式 | percentile 5层 |
| Layer 1 累计收益 | 29.02% |
| Layer 2 累计收益 | 69.69% |
| Layer 3 累计收益 | 58.05% |
| Layer 4 累计收益 | 36.11% |
| Layer 5 累计收益 | 74.11% |

---

## 6. 分层效果评估

### 6.1 单调性分析

- 分层收益无明显单调性（Layer 5 收益最高）
- IC 绝对值较小（-0.013），因子预测能力较弱
- 建议进一步优化因子计算窗口或组合使用

### 6.2 结论

price_position 因子单独使用效果不佳：
- IC 绝对值 < 0.03，预测能力较弱
- 分层收益无单调性
- 可能需要与其他因子组合使用

---

## 7. 规范遵循

### 7.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

---

## 8. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-01 | v1.25 | v1.25架构适配：layer_names/layer_descriptions分离+pytest测试+流程文档 |