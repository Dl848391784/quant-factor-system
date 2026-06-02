# 尾盘量价强度因子 IC 计算器测试用例

> 版本: v1.0
> 创建时间: 2026-06-02 15:18 北京时间

## 测试覆盖

| 测试项 | pytest 函数 | 状态 |
|--------|-------------|------|
| 正常计算 | `test_normal_calculation` | ✅ |
| prices[0] 除零防护 | `test_zero_price_protection` | ✅ |
| volume 除零防护 | `test_zero_volume_protection` | ✅ |
| 数据不完整防护 | `test_incomplete_data_protection` | ✅ |
| 文件不存在异常 | `test_file_not_found` | ✅ |

## 测试数据设计

### 正常计算场景

```python
factor_df = {
    'date': ['2026-06-01', '2026-06-01'],
    'asset': ['000001', '000002'],
    'volume': [1000000, 2000000]
}

tail_df = {
    'date': ['2026-06-01', '2026-06-01'],
    'asset': ['000001', '000002'],
    'prices': [[10.0, ..., 11.0], [20.0, ..., 21.0]],  # 13个元素
    'volumes': [[10000] * 13, [20000] * 13]
}

# 预期结果：
# asset 000001: 尾盘涨跌幅=0.1, 尾盘量比=0.13, 尾盘量价强度=0.013
# asset 000002: 尾盘涨跌幅=0.05, 尾盘量比=0.13, 尾盘量价强度=0.0065
```

### 除零防护场景

```python
# prices[0] = 0 → NaN
tail_df['prices'] = [[0.0, ..., 1.0]]

# volume = 0 → NaN
factor_df['volume'] = [0]
```

### 数据不完整场景

```python
# prices/volumes 长度 < 13 → NaN
tail_df['prices'] = [[10.0, 10.1]]  # 只有2个元素
```

## 运行测试

```bash
cd /home/admin/projects/factor_ic_analyzer
pytest factor_ic/test_cases/test_ic_tail_price_volume_intensity.py -v
```