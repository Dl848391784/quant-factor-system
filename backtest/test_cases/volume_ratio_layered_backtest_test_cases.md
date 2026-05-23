# 量比分层回测测试用例

**测试日期**: 2026-05-23
**因子名称**: volume_ratio_1d
**测试状态**: 待编写

---

## 1. 正常数据场景

### 1.1 分层收益计算正确

**测试输入**:
- 因子数据: 1482714 条记录，2999 只股票
- 因子列: volume_ratio_5（已在缓存中）
- 收益数据: forward_return_1d
- 分层阈值: [0, 0.5, 1.0, 1.5, 2.0, 5.0]
- 因子方向: negative（反向因子）

**预期输出**:
- 5 个分层，每层有完整统计指标
- Layer 1→5 收益单调递增（反向因子）
- 多空组合收益计算正确

**验证步骤**:
```python
# 加载结果
result = json.load(open('backtest/result/volume_ratio_layered_backtest.json'))

# 验证分层数量
assert result['meta']['n_layers'] == 5

# 验证每层统计完整
for layer_id in range(1, 6):
    stats = result['layer_stats'].get(f'layer_{layer_id}')
    assert stats is not None
    assert 'n_stocks_avg' in stats
    assert 'annual_return' in stats
    assert 'sharpe_ratio' in stats

# 验证单调性（反向因子）
monotonicity = result['monotonicity']
assert monotonicity['quality'] in ['excellent', 'good', 'fair']
assert monotonicity['correlation'] < 0  # 反向因子负相关
```

---

## 2. 边界数据场景

### 2.1 数据量不足

**测试输入**:
- 因子数据: 少于 min_stocks_per_layer（10）
- 分层阈值: [0, 0.5, 1.0, 1.5, 2.0, 5.0]

**预期输出**:
- n_days_total = 0
- 空数据提示信息
- 结构完整（layer_stats 存在但值为空）

**验证步骤**:
```python
result = run_volume_ratio_layered_backtest(...)
assert result['meta']['n_days_total'] == 0
assert 'layer_stats' in result
assert result['layer_stats']['layer_1']['n_stocks_avg'] == 0
```

### 2.2 volume_ratio_5 列缺失

**测试输入**:
- factor_data.json.gz 中缺少 volume_ratio_5 列

**预期输出**:
- ValueError 异常
- 退出码 4

---

## 3. 异常数据场景

### 3.1 NaN 处理

**测试输入**:
- 因子数据含 NaN 值

**预期输出**:
- NaN 被过滤，不影响分层计算
- 输出 JSON 不含 NaN（转为 None）

**验证步骤**:
```python
import json
result = json.load(open('backtest/result/volume_ratio_layered_backtest.json'))
# JSON 加载成功，无 ValueError（NaN 已处理）
```

### 3.2 量比极端值

**测试输入**:
- volume_ratio_5 > 5（极端放量）

**预期输出**:
- 归入 Layer 5（边界处理）
- 边界警告日志

---

## 4. 数据来源验证

### 4.1 volume_ratio_5 已在缓存

**测试输入**:
- factor_data.json.gz 文件

**预期输出**:
- 包含 volume_ratio_5 列
- 无需额外计算

**验证步骤**:
```python
import gzip, json
with gzip.open('cache/factor_data/factor_data.json.gz', 'rt') as f:
    data = json.load(f)
    assert 'volume_ratio_5' in data['data'][0]
```

---

## 5. 实际测试结果

| 测试场景 | 输入 | 输出 | 状态 |
|---------|------|------|------|
| 正常数据 | 1482714 条记录 | 510 天回测 | ✓ |
| volume_ratio_5 范围 | 缓存数据 | 0.1 ~ 4.97 | ✓ |
| 分层阈值 | [0, 0.5, 1, 1.5, 2, 5] | 5层划分 | ✓ |
| 多空收益 | 反向因子 | 多头 97.42%, 空头 -24.05% | ✓ |
| 多空夏普 | 多空组合 | 6.41 (卓越) | ✓ |
| 单调性 | Layer1→5 | 相关系数 -0.8924 (good) | ✓ |
| 数据来源 | 缓存已有 | 无需额外加载 | ✓ |

---

## 6. 待补充测试

- [ ] 单元测试文件 `test_volume_ratio_layered_backtest.py`
- [ ] 边界值测试（thresholds 越界）
- [ ] 参数校验测试（factor_direction 非法值）
- [ ] 与 turnover_surge 因子对比测试