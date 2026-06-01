# 隔夜收益率分层回测测试用例

**测试日期**: 2026-06-01
**因子名称**: overnight_ret_1d
**测试状态**: 已验证（2026-06-01 11:37 北京时间）

---

## 1. 正常数据场景

### 1.1 分层收益计算正确

**测试输入**:
- 因子数据: 需实时计算 overnight_ret
- 因子公式: overnight_ret = (今日开盘 - 昨日收盘) / 昨日收盘
- 收益数据: forward_return_1d
- 分层方式: percentile（5层，每层20%）
- 因子方向: positive（正向因子）

**预期输出**:
- 5 个分层，每层有完整统计指标
- Layer 1→5 收益单调递增（正向因子）
- 多空组合收益计算正确（做多高层，做空低层）

**验证步骤**:
```python
# 加载结果
result = json.load(open('backtest/result/overnight_ret_layered_backtest.json'))

# 验证分层数量
assert result['meta']['n_layers'] == 5

# 验证每层统计完整
for layer_id in range(1, 6):
    stats = result['layer_stats'].get(f'layer_{layer_id}')
    assert stats is not None
    assert 'n_stocks_avg' in stats
    assert 'annual_return' in stats
    assert 'sharpe_ratio' in stats

# 验证单调性（正向因子）
monotonicity = result['monotonicity']
assert monotonicity['quality'] in ['excellent', 'good', 'fair']
assert monotonicity['correlation'] > 0  # 正向因子正相关
```

---

## 2. 边界数据场景

### 2.1 数据量不足

**测试输入**:
- 因子数据: 少于 min_stocks_per_layer（10）

**预期输出**:
- n_days_total = 0
- 空数据提示信息
- 结构完整（layer_stats 存在但值为空）

**验证步骤**:
```python
result = run_overnight_ret_layered_backtest(...)
assert result['meta']['n_days_total'] == 0
assert 'layer_stats' in result
assert result['layer_stats']['layer_1']['n_stocks_avg'] == 0
```

### 2.2 open/close 列缺失

**测试输入**:
- factor_ic_data.json.gz 中缺少 open 或 close 列

**预期输出**:
- ValueError 异常
- 退出码 4

---

## 3. 异常数据场景

### 3.1 NaN 处理

**测试输入**:
- 因子数据含 NaN 值（停牌股票）

**预期输出**:
- NaN 被过滤，不影响分层计算
- 输出 JSON 不含 NaN（转为 None）

**验证步骤**:
```python
import json
result = json.load(open('backtest/result/overnight_ret_layered_backtest.json'))
# JSON 加载成功，无 ValueError（NaN 已处理）
```

### 3.2 隔夜收益率极端值

**测试输入**:
- overnight_ret 接近 ±10%（涨跌停边界）

**预期输出**:
- percentile 分层自动适应
- 归入对应层（Layer 1 或 Layer 5）

---

## 4. 因子计算验证

### 4.1 overnight_ret 计算正确

**测试输入**:
- date: 2024-04-12
- asset: 000001
- open: 10.5
- close (昨日): 10.0

**预期输出**:
- overnight_ret = (10.5 - 10.0) / 10.0 = 0.05

**验证步骤**:
```python
from data_fetchers.factor_calculator import calculate_overnight_return
import pandas as pd

df = pd.DataFrame({
    'date': ['2024-04-12'],
    'asset': ['000001'],
    'open': [10.5],
    'close': [10.0]
})
result = calculate_overnight_return(df)
assert result['overnight_ret'].iloc[0] == 0.05
```

---

## 5. 因子方向验证

### 5.1 factor_direction 与 IC 结果一致

**测试输入**:
- IC 分析结果: ic_mean = 0.021187 > 0

**预期输出**:
- factor_direction = 'positive'
- 多头取高层（Layer 4-5）
- 空头取低层（Layer 1-2）

**验证步骤**:
```python
# 检查脚本配置
from backtest.layered_backtest_overnight_ret_1d import OvernightRetLayerConfig
config = OvernightRetLayerConfig()
assert config.factor_direction == 'positive'
```

---

## 6. 实际测试结果（2026-06-01 11:37 北京时间）

| 测试场景 | 输入 | 输出 | 状态 |
|---------|------|------|------|
| 正常数据 | 实时计算 overnight_ret | 514 天回测 | ✓ 已验证 |
| overnight_ret 范围 | [-0.67, 0.11]（实测） | percentile 分层 | ✓ 已验证 |
| 分层方式 | percentile（5层） | 20%/层 | ✓ 已验证 |
| 因子方向 | positive | 做多高层 | ✓ 已验证 |
| 多空夏普比率 | 多空组合 | 1.20 | ✓ 已验证 |
| 单调性相关系数 | Layer1→5 | 0.8753 (good) | ✓ 已验证 |

---

## 7. 待补充测试

- [ ] 单元测试文件 `test_overnight_ret_layered_backtest.py`
- [ ] 因子计算边界值测试（昨日收盘=0）
- [ ] 参数校验测试（factor_direction 非法值）
- [ ] 与其他因子对比测试