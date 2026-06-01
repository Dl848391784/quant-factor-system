# 振幅分层回测测试用例

**测试日期**: 2026-06-01
**因子名称**: amplitude_1d
**测试状态**: 待验证

---

## 1. 正常数据场景

### 1.1 分层收益计算正确

**测试输入**:
- 因子数据: 需实时计算 amplitude
- 因子公式: amplitude = (high - low) / close
- 收益数据: forward_return_1d
- 分层方式: percentile（5层，每层20%）

**预期输出**:
- 5 个分层，每层有完整统计指标
- 多空组合收益计算正确

**验证步骤**:
```python
result = json.load(open('backtest/result/amplitude_layered_backtest.json'))

# 验证分层数量
assert result['meta']['n_layers'] == 5

# 验证每层统计完整
for layer_id in range(1, 6):
    stats = result['layer_stats'].get(f'layer_{layer_id}')
    assert stats is not None
    assert 'n_stocks_avg' in stats
    assert 'annual_return' in stats
```

---

## 2. 边界数据场景

### 2.1 数据量不足

**测试输入**:
- 因子数据: 少于 min_stocks_per_layer（10）

**预期输出**:
- n_days_total = 0
- 空数据提示信息

---

## 3. 异常数据场景

### 3.1 NaN 处理

**测试输入**:
- 因子数据含 NaN 值（停牌股票）

**预期输出**:
- NaN 被过滤，不影响分层计算
- 输出 JSON 不含 NaN（转为 None）

---

## 4. 因子计算验证

### 4.1 amplitude 计算正确

**测试输入**:
- high: 12.0
- low: 10.0
- close: 11.0

**预期输出**:
- amplitude = (12.0 - 10.0) / 11.0 = 0.1818

**验证步骤**:
```python
from data_fetchers.factor_calculator import calculate_amplitude
import pandas as pd

df = pd.DataFrame({
    'date': ['2024-04-12'],
    'asset': ['000001'],
    'high': [12.0],
    'low': [10.0],
    'close': [11.0]
})
result = calculate_amplitude(df)
assert abs(result['amplitude'].iloc[0] - 0.1818) < 0.001
```

---

## 5. 实际测试结果

| 测试场景 | 输入 | 输出 | 状态 |
|---------|------|------|------|
| 正常数据 | 实时计算 amplitude | 待验证 | 待验证 |
| 分层方式 | percentile（5层） | 20%/层 | 待验证 |
| 因子方向 | 从IC派生 | 待验证 | 待验证 |

---

## 6. 待补充测试

- [x] pytest 测试文件已存在
- [ ] 因子计算边界值测试（close=0）
- [ ] 参数校验测试