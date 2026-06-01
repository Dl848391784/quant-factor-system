# 量比分层回测测试用例

**测试日期**: 2026-06-01
**因子名称**: volume_ratio_1d
**测试状态**: ✓ 全部通过（18项）

---

## 1. 配置类验证（TestVolumeRatioLayerConfig）

### TC001-01: factor_name 类属性
- 输入: VolumeRatioLayerConfig.factor_name
- 预期: 'volume_ratio'
- 状态: ✓ PASS

### TC001-02: layer_names 类属性为 Sequence[str]
- 输入: VolumeRatioLayerConfig.layer_names
- 预期: len=5, layer_names[0]='极低层(量比极低)'
- 状态: ✓ PASS

### TC001-03: ic_source 默认路径
- 输入: VolumeRatioLayerConfig().ic_source_resolved
- 预期: 'factor_ic/result/ic_volume_ratio_1d_analysis_result.json'
- 状态: ✓ PASS

### TC001-04: factor_direction = negative（从 IC 文件派生）
- 输入: VolumeRatioLayerConfig().factor_direction
- 预期: 'negative'（ic_mean=-0.0346）
- 状态: ✓ PASS

### TC001-05: n_layers 由 len(layer_names) 派生
- 输入: VolumeRatioLayerConfig().n_layers
- 预期: 5
- 状态: ✓ PASS

### TC001-06: layer_names_dict 运行时生成
- 输入: VolumeRatioLayerConfig().layer_names_dict
- 预期: {'1': '极低层(量比极低)', ..., '5': '极高层(量比极高)'}
- 状态: ✓ PASS

### TC001-07: layer_names 语义描述
- 输入: VolumeRatioLayerConfig().layer_names
- 预期: 每项包含'量比'
- 状态: ✓ PASS

### TC001-08: layer_names 无固定阈值
- 输入: VolumeRatioLayerConfig().layer_names
- 预期: percentile模式无固定阈值
- 状态: ✓ PASS

### TC001-09: factor_direction = negative
- 输入: VolumeRatioLayerConfig().factor_direction
- 预期: 'negative'
- 状态: ✓ PASS

### TC001-10: factor_direction 类型约束
- 输入: VolumeRatioLayerConfig().factor_direction
- 预期: Literal['positive', 'negative'] 中之一
- 状态: ✓ PASS

### TC001-11: long_layers/short_layers 由 factor_direction 派生
- 输入: VolumeRatioLayerConfig().long_layers, short_layers
- 预期: long=[1,2], short=[4,5]（反向因子）
- 状态: ✓ PASS

---

## 2. 预计算因子特性验证（TestVolumeRatioPrecomputed）

### TC002-01: 预计算因子无需 calculator
- 输入: hasattr(VolumeRatioLayerConfig, 'factor_calculator')
- 预期: False
- 状态: ✓ PASS

---

## 3. 回测结果验证（TestLayeredBacktestResult）

### TC003-01: 结果文件存在
- 输入: Path('backtest/result/volume_ratio_layered_backtest.json')
- 预期: exists()
- 状态: ✓ PASS

### TC003-02: 结果结构完整
- 输入: result.keys()
- 预期: ['meta', 'layer_stats', 'monotonicity', 'long_short']
- 状态: ✓ PASS

### TC003-03: meta 字段
- 输入: result['meta']
- 预期: factor_name='volume_ratio', factor_direction='negative', n_layers=5
- 状态: ✓ PASS

### TC003-04: layer_stats 完整
- 输入: len(result['layer_stats'])
- 预期: 5
- 状态: ✓ PASS

---

## 4. 执行集成验证（TestLayeredBacktestExecution）

### TC004-01: 配置类可实例化
- 输入: VolumeRatioLayerConfig()
- 预期: n_layers=5, factor_direction='negative'
- 状态: ✓ PASS

### TC004-02: factor_direction 决定多空组合
- 输入: VolumeRatioLayerConfig().factor_direction
- 预期: 'negative'（反向因子）
- 状态: ✓ PASS

---

## 5. 特殊场景说明

### 5.1 factor_col 与 factor_name 不同

数据源列名为 `volume_ratio_5`，与 `factor_name='volume_ratio'` 不同。

脚本调用时需指定：
```python
factor_cli_main(
    config_cls=VolumeRatioLayerConfig,
    factor_col='volume_ratio_5',
    required_factor_cols=['volume_ratio_5']
)
```

### 5.2 预计算因子特点

- 无需 factor_calculator 参数
- 必须指定 factor_col 和 required_factor_cols

---

## 6. 测试文件位置

```
backtest/test_cases/test_layered_backtest_volume_ratio_1d.py
```

---

## 7. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-01 | v1.1 | 创建 pytest 测试文件，18项测试全部通过 |
| 2026-05-23 | v1.0 | 初始测试用例文档（待编写） |