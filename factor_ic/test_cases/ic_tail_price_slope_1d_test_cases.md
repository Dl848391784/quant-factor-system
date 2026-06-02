# 尾盘价格趋势斜率因子 IC 计算器测试用例

> 版本: v1.0
> 创建时间: 2026-06-02 17:00 北京时间

## 测试覆盖

| 测试项 | pytest 函数 | 状态 |
|--------|-------------|------|
| 正常计算（上涨趋势） | `test_normal_calculation_uptrend` | ✅ |
| 正常计算（下跌趋势） | `test_normal_calculation_downtrend` | ✅ |
| mean_price 除零防护 | `test_zero_mean_price_protection` | ✅ |
| 数据不完整防护 | `test_incomplete_data_protection` | ✅ |
| 数据污染防护（NaN） | `test_nan_data_protection` | ✅ |
| 文件不存在异常 | `test_file_not_found` | ✅ |

## 测试数据设计

### 正常计算场景（上涨趋势）

```python
factor_df = {
    'date': ['2026-06-01', '2026-06-01'],
    'asset': ['000001', '000002']
}

tail_df = {
    'date': ['2026-06-01', '2026-06-01'],
    'asset': ['000001', '000002'],
    'prices': [[10.0, 10.1, 10.2, ..., 11.0], [20.0, 20.1, ..., 21.0]]  # 13个元素，线性上涨
}

# 预期结果：
# asset 000001: prices = [10.0, ..., 11.0]，斜率 > 0（上涨趋势）
# asset 000002: prices = [20.0, ..., 21.0]，斜率 > 0（上涨趋势）
```

### 正常计算场景（下跌趋势）

```python
factor_df = {
    'date': ['2026-06-01'],
    'asset': ['000001']
}

tail_df = {
    'date': ['2026-06-01'],
    'asset': ['000001'],
    'prices': [[11.0, 10.9, 10.8, ..., 10.0]]  # 13个元素，线性下跌
}

# 预期结果：斜率 < 0（下跌趋势）
```

### 除零防护场景

```python
# mean_price = 0 → NaN
tail_df['prices'] = [[0.0] * 13]  # 全零价格
```

### 数据不完整场景

```python
# prices 长度 < 13 → NaN
tail_df['prices'] = [[10.0, 10.1]]  # 只有2个元素
```

### 数据污染场景

```python
# prices 包含 NaN → NaN
tail_df['prices'] = [[10.0, 10.1, np.nan, 10.3, ..., 11.0]]  # 包含 NaN 值
```

## 运行测试

```bash
cd /home/admin/projects/factor_ic_analyzer
pytest factor_ic/test_cases/test_ic_tail_price_slope_1d.py -v
```

## 版本历史

1. v1.0 (2026-06-02): 初始版本，创建测试用例文档