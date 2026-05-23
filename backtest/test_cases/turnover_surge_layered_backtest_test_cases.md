# 换手率突增分层回测测试用例

**测试日期**: 2026-05-23
**因子名称**: turnover_surge_1d
**测试状态**: 待编写

---

## 1. 正常数据场景

### 1.1 分层收益计算正确

**测试输入**:
- 因子数据: 1482714 条记录，2999 只股票
- 换手率数据: turnover_rate_data.json.gz
- 收益数据: forward_return_1d
- 分层阈值: [0, 0.5, 1.0, 1.5, 2.0, 3.0]
- 因子方向: negative（反向因子）

**预期输出**:
- 5 个分层，每层有完整统计指标
- Layer 1→5 收益单调递增（反向因子）
- 多空组合收益计算正确

**验证步骤**:
```python
# 加载结果
result = json.load(open('backtest/result/turnover_surge_layered_backtest.json'))

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
- 分层阈值: [0, 0.5, 1.0, 1.5, 2.0, 3.0]

**预期输出**:
- n_days_total = 0
- 空数据提示信息
- 结构完整（layer_stats 存在但值为空）

**验证步骤**:
```python
result = run_turnover_surge_layered_backtest(...)
assert result['meta']['n_days_total'] == 0
assert 'layer_stats' in result
assert result['layer_stats']['layer_1']['n_stocks_avg'] == 0
```

### 2.2 换手率数据缺失

**测试输入**:
- turnover_rate_data.json.gz 文件不存在

**预期输出**:
- FileNotFoundError 异常
- 退出码 2

---

## 3. 异常数据场景

### 3.1 NaN 处理

**测试输入**:
- 因子数据含 NaN 值（avg_turnover 接近零）

**预期输出**:
- NaN 被过滤，不影响分层计算
- 输出 JSON 不含 NaN（转为 None）

**验证步骤**:
```python
import json
result = json.load(open('backtest/result/turnover_surge_layered_backtest.json'))
# JSON 加载成功，无 ValueError（NaN 已处理）
```

### 3.2 换手率突增极端值

**测试输入**:
- turnover_surge > 10（极端突增）

**预期输出**:
- 归入 Layer 5（边界处理）
- 边界警告日志

---

## 4. 因子计算场景

### 4.1 turnover_surge 计算正确

**测试输入**:
- turnover_rate 数据: 含换手率序列
- surge_window: 5

**预期输出**:
- surge = 当日换手率 / 过去 5 日均值（不含当日）
- surge 范围 ≥ 0

**验证步骤**:
```python
factor_df = calculate_turnover_surge(factor_df, surge_window=5)
assert 'turnover_surge' in factor_df.columns
assert factor_df['turnover_surge'].min() >= 0
```

### 4.2 除零防护

**测试输入**:
- 过去 5 日完全无交易（avg_turnover = 0）

**预期输出**:
- turnover_surge 标记为 NaN
- 警告日志记录

---

## 5. 实际测试结果

| 测试场景 | 输入 | 输出 | 状态 |
|---------|------|------|------|
| 正常数据 | 1482714 条记录 | 510 天回测 | ✓ |
| turnover_surge 范围 | surge_window=5 | 0.01 ~ 470.28 | ✓ |
| 分层阈值 | [0, 0.5, 1, 2, 5, 500] | 5层划分 | ✓ |
| 多空收益 | 反向因子 | 多头 66.49%, 空头 -37.66% | ✓ |
| 多空夏普 | 多空组合 | 4.89 (优异) | ✓ |
| 单调性 | Layer1→5 | 相关系数 -0.9573 (good) | ✓ |
| 数据合并 | 3个数据源 | 1482714 条记录 | ✓ |

---

## 6. 待补充测试

- [ ] 单元测试文件 `test_turnover_surge_layered_backtest.py`
- [ ] 边界值测试（thresholds 越界）
- [ ] 参数校验测试（factor_direction 非法值）
- [ ] 换手率数据合并测试（merge 正确性）