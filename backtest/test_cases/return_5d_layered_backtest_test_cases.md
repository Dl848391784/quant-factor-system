# 5日累计涨幅因子分层回测测试用例

> 版本: v1.0  
> 作者: 云瑶  
> 创建日期: 2026-06-01  

---

## 测试范围

| 测试类型 | 覆盖内容 |
|----------|----------|
| 配置类属性 | factor_name, ic_meta, n_layers, layer_names, factor_direction |
| 因子计算 | calculate_return_5d 函数 |
| 回测结果 | JSON 输出结构 |
| 执行集成 | factor_cli_main 调用 |

---

## TC001: 配置类属性验证

### TC001-01: factor_name 类属性

**测试点**：factor_name 作为 ClassVar 存在且值正确

```python
assert Return5dLayerConfig.factor_name == 'return_5d'
```

**预期**：通过

**状态**：待验证

---

### TC001-02: ic_meta 字段完整性

**测试点**：ic_meta 包含所有必需字段

```python
required_keys = ['date', 'source', 'ic_mean', 'icir', 'p_value', 'direction']
assert all(k in Return5dLayerConfig.ic_meta for k in required_keys)
```

**预期**：通过

**状态**：待验证

---

### TC001-03: n_layers 显式声明

**测试点**：n_layers=5 显式声明，不依赖基类默认值

```python
config = Return5dLayerConfig()
assert config.n_layers == 5
```

**预期**：通过

**状态**：待验证

---

### TC001-04: layer_names 无固定阈值

**测试点**：layer_names 不包含固定阈值数值（percentile 模式）

```python
for name in config.layer_names.values():
    assert not any(c.isdigit() and '%' in name for c in name)
```

**预期**：通过

**状态**：待验证

---

### TC001-05: factor_direction 类型约束

**测试点**：factor_direction 只能是 'positive' 或 'negative'

```python
from typing import get_args
valid_values = get_args(Literal['positive', 'negative'])
assert config.factor_direction in valid_values
```

**预期**：通过

**状态**：待验证

---

## TC002: 因子计算验证

### TC002-01: 基本计算

**测试点**：5日涨幅计算正确

```python
close = [100.0, 102.0, 101.0, 103.0, 105.0, 110.0]
# return_5d[5] = 110/100 - 1 = 0.10
```

**预期**：return_5d[5] = 0.10

**状态**：待验证

---

### TC002-02: 下跌计算

**测试点**：5日下跌计算正确

```python
close = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]
# return_5d[5] = 95/100 - 1 = -0.05
```

**预期**：return_5d[5] = -0.05

**状态**：待验证

---

### TC002-03: NaN 处理

**测试点**：前5天数据无完整5日历史，返回 NaN

```python
close = [100.0, 101.0, 102.0]  # 只有3天数据
# return_5d[0-4] = NaN
```

**预期**：前5天为 NaN

**状态**：待验证

---

## TC003: 回测结果验证

### TC003-01: 结果文件存在

**测试点**：回测结果文件生成

```bash
ls backtest/result/return_5d_layered_backtest.json
```

**预期**：文件存在

**状态**：待验证

---

### TC003-02: 结果结构完整

**测试点**：JSON 输出包含必需字段

```python
result = json.load(open('backtest/result/return_5d_layered_backtest.json'))
required_keys = ['meta', 'layer_stats', 'monotonicity', 'long_short']
assert all(k in result for k in required_keys)
```

**预期**：通过

**状态**：待验证

---

## pytest 测试覆盖

| 测试文件 | 说明 |
|----------|------|
| `test_cases/test_layered_backtest_return_5d_1d.py` | pytest 测试文件 |

**覆盖测试**：
- [ ] 配置类属性验证
- [ ] 因子计算验证
- [ ] 回测结果结构验证
- [ ] 执行集成验证

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v1.0 | 2026-06-01 | 初始版本（配套 Round 1 创建） |

