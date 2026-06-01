# 量比因子分层回测流程文档

**创建日期**: 2026-05-23
**最后更新**: 2026-06-01 (v1.24架构适配：factor_col ClassVar + layer_names/layer_descriptions分离)
**因子名称**: volume_ratio_1d
**因子方向**: 反向因子（ic_mean = -0.0346）

---

## 1. 因子概述

### 1.1 因子定义

量比因子衡量当日成交量相对于历史均值的变化程度：

```
volume_ratio_5 = 当日成交量 / 过去 5 日平均成交量
```

其中：
- 数据已在统一数据源 factor_ic_data.json.gz 中预计算
- 因子列名: volume_ratio_5
- 因子值恒 ≥ 0

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | ≥ 0（无上界） |
| 实测范围 | 0.1 ~ 4.97 |
| 正常值 | ratio ≈ 1（当日成交量等于历史均值） |
| 放量信号 | ratio > 1（成交量高于均值） |
| 缩量信号 | ratio < 1（成交量低于均值） |

### 1.3 IC 分析结果

```json
{
  "ic_mean": -0.034561,
  "icir": 0.3264,
  "p_value": 3.55e-15
}
```

**结论**: IC 绝对值 > 0.03，有一定预测能力，统计显著。

---

## 2. 分层配置

### 2.1 分层模式

**percentile 5层（每层20%）** - 遵循 PROJECT.md v1.5 规范

| Layer | percentile范围 | 名称 | 含义 |
|-------|---------------|------|------|
| 1 | 0-20% | 极低层(量比极低) | 成交量远低于均值（缩量） |
| 2 | 20-40% | 偏低层(量比偏低) | 成交量低于均值 |
| 3 | 40-60% | 正常层(量比适中) | 成交量接近均值 |
| 4 | 60-80% | 偏高层(量比偏高) | 成交量偏高 |
| 5 | 80-100% | 极高层(量比极高) | 成交量极放量 |

### 2.2 多空组合

```python
factor_direction = 'negative'  # 反向因子（ic_mean < 0）
long_layers = [1, 2]   # 做多缩量组（低值层）
short_layers = [4, 5]  # 做空放量组（高值层）
```

策略逻辑（运行时派生）：
- factor_direction='negative'（从 IC 文件派生，ic_mean=-0.0346）
- long_layers=[1,2]（做多缩量组）
- short_layers=[4,5]（做空放量组）

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 数据加载

### 3.1 数据来源

量比因子数据已在统一数据源中预计算：

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 统一数据源 | factor_ic_data.json.gz | date, asset, volume_ratio_5, forward_return_1d |

**注意**: volume_ratio_5 已预计算，无需 factor_calculator。

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_volume_ratio_1d.py
```

### 4.2 核心特点（v1.24 理想形态）

- **薄声明**: factor_name/factor_col/layer_names/layer_descriptions 全部 ClassVar
- **预计算因子**: factor_col='volume_ratio_5' 显式声明（数据列名 ≠ factor_name）
- **layer_names**: 纯标签（lowest/lower/...），用于目录/列名
- **layer_descriptions**: 含中文（极低层(量比极低)/...），用于日志显示
- **CLI 调用**: 只传 config_cls，元数据全部在配置类中

```python
class VolumeRatioLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = 'volume_ratio'
    factor_col: ClassVar[str] = 'volume_ratio_5'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest', 'lower', 'normal', 'higher', 'highest'
    )
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(量比极低)', '偏低层(量比偏低)', 
        '正常层(量比适中)', '偏高层(量比偏高)', '极高层(量比极高)'
    )

if __name__ == '__main__':
    factor_cli_main(VolumeRatioLayerConfig)
```

---

## 5. 输出结果

### 5.1 输出文件

遵循 PROJECT.md 输出目录规范，结果输出到 `backtest/result/`：

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/volume_ratio_layered_backtest.json` |
| 每日明细 | `backtest/result/volume_ratio_layered_backtest_daily.json.gz` |

### 5.2 回测结果摘要（2026-06-01 运行）

| 指标 | 值 |
|------|-----|
| 回测天数 | 515 天 |
| 股票数量 | 577 只/层 |
| 分层模式 | percentile 5层 |
| 多头年化收益 | 30.93% |
| 空头年化收益 | 12.88% |
| 多空年化收益 | 18.06% |
| 多空夏普比率 | 2.25 |
| 单调性相关系数 | -0.8963 (good) |

---

## 6. 分层效果评估

### 6.1 单调性分析

- 单调性相关系数 -0.8963（good）
- 反向因子单调性良好：Layer 1→5 收益递减（符合预期）
- Layer 1 (极缩量) 累计收益 87%，Layer 5 (极放量) 累计收益 3%

### 6.2 结论

量比因子表现良好：
- 单调性良好，分层效果显著
- 缩量组（Layer 1,2）表现优于放量组
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

|| 日期 | 版本 | 变更内容 |
||------|------|----------|
|| 2026-06-01 | v1.23 | 移除 docstring 中 factor_direction 预判，添加 ic_source 注释说明 |
|| 2026-06-01 | v1.22 | 适配 ClassVar[Sequence[str]] 架构，指定 factor_col='volume_ratio_5' |
|| 2026-05-23 | v1.0 | 初始版本，创建量比分层回测脚本 |