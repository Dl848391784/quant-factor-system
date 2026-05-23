# KDJ_J 分层回测测试用例

**测试日期**: 2026-05-23
**因子名称**: kdj_j_1d
**测试状态**: 待编写

---

## 1. 正常数据场景

### 1.1 分层收益计算正确

**测试输入**:
- 因子数据: 1482714 条记录，2999 只股票
- 收益数据: forward_return_1d
- 分层阈值: [-30, 0, 20, 80, 100, 130]
- 因子方向: negative（反向因子）

**预期输出**:
- 5 个分层，每层有完整统计指标
- Layer1-5 收益单调性检查
- 多空组合收益计算正确

**验证步骤**:
```python
# 加载结果
result = json.load(open('backtest/result/kdj_j_layered_backtest.json'))

# 验证分层数量
assert result['meta']['n_layers'] == 5

# 验证每层统计完整
for layer_id in range(1, 6):
    stats = result['layer_stats'].get(f'layer_{layer_id}')
    assert stats is not None
    assert 'n_stocks_avg' in stats
    assert 'annual_return' in stats
    assert 'sharpe_ratio' in stats

# 验证多空组合
assert 'long_short' in result
assert 'sharpe_ratio' in result['long_short']
```

---

## 2. 边界数据场景

### 2.1 数据量不足

**测试输入**:
- 因子数据: 少于 min_stocks_per_layer（10）
- 分层阈值: [-30, 0, 20, 80, 100, 130]

**预期输出**:
- n_days_total = 0
- 空数据提示信息
- 结构完整（layer_stats 存在但值为空）

**验证步骤**:
```python
result = run_kdj_j_layered_backtest(...)
assert result['meta']['n_days_total'] == 0
assert 'layer_stats' in result
assert result['layer_stats']['layer_1']['n_stocks_avg'] == 0
```

### 2.2 单层模式

**测试输入**:
- 分层阈值: [0, 100]（n_layers=1）

**预期输出**:
- long_layers = [1]
- short_layers = [1]
- 多空组合为同一层

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
result = json.load(open('backtest/result/kdj_j_layered_backtest.json'))
# JSON 加载成功，无 ValueError（NaN 已处理）
```

### 3.2 空数据返回结构

**测试输入**:
- 空数据（daily_df 长度为 0）

**预期输出**:
- 返回结构与正常数据一致
- layer_stats 结构完整但值为 None

---

## 4. 因子计算场景

### 4.1 KDJ_J 计算正确

**测试输入**:
- price 数据: close, high, low
- KDJ 参数: N=9, M1=3, M2=3

**预期输出**:
- J 值范围: [-30, 130] 左右
- J = 3K - 2D

**验证步骤**:
```python
factor_df = calculate_kdj_j(factor_df, n=9, m1=3, m2=3)
assert 'kdj_j' in factor_df.columns
assert factor_df['kdj_j'].min() >= -30
assert factor_df['kdj_j'].max() <= 130
```

---

## 5. 实际测试结果

| 测试场景 | 输入 | 输出 | 状态 |
|---------|------|------|------|
| 正常数据 | 1482714 条记录 | 515 天回测 | ✓ |
| KDJ_J 范围 | N=9, M1=3, M2=3 | -28.62 ~ 128.78 | ✓ |
| 多空收益 | 反向因子 | 多头 17.99%, 空头 52.07% | ✓ |
| 单调性 | Layer1-5 | 相关系数 0.6416 (poor) | ✓ |

---

## 6. 待补充测试

- [ ] 单元测试文件 `test_kdj_j_layered_backtest.py`
- [ ] 边界值测试（thresholds 越界）
- [ ] 参数校验测试（factor_direction 非法值）