# factor_generator.py 测试用例

> 版本: v1.0
> 创建时间: 2026-05-25 10:27 北京时间
> 脚本路径: `data_fetchers/factor_generator.py`

---

## 测试环境

**前置条件**:
- 输入数据文件存在：
  - `cache/factor_data/factor_data.json.gz`
  - `cache/factor_data/turnover_rate_data.json.gz`

**运行方式**:
```bash
python data_fetchers/factor_generator.py
```

---

## 测试用例清单

### TC001: 导入验证

**测试内容**: 验证模块导入成功

**测试步骤**:
```python
from data_fetchers.factor_generator import generate_all_factors, get_module_logger
```

**预期结果**:
- `generate_all_factors` 导入成功
- `get_module_logger` 导入成功

---

### TC002: get_module_logger 验证

**测试内容**: 验证 get_module_logger 返回正确的 logger

**测试步骤**:
```python
import logging

# 测试 1: 不传参数返回模块级 logger
module_logger = get_module_logger()
assert module_logger.name == 'data_fetchers.factor_generator'

# 测试 2: 传入自定义 logger
custom_logger = logging.getLogger('my_app')
returned_logger = get_module_logger(custom_logger)
assert returned_logger.name == 'my_app'

# 测试 3: 传入非 Logger 类型抛 TypeError
try:
    get_module_logger('invalid')
except TypeError:
    pass  # 预期抛出 TypeError
```

**预期结果**:
- 不传参数返回 `'data_fetchers.factor_generator'` logger
- 传入自定义 logger 返回该 logger
- 传入非 Logger 类型抛 `TypeError`

---

### TC003: generate_all_factors 验证

**测试内容**: 验证 generate_all_factors 返回正确的元数据结构

**测试步骤**:
```python
import logging
from data_fetchers.common.logger_config import setup_logger

logger = setup_logger('test_factor_generator', level=logging.INFO)
metadata = generate_all_factors(logger=logger)
```

**预期结果**:
- 返回类型为 `dict`
- 返回不为空

---

### TC004: 返回字段验证

**测试内容**: 验证 metadata 返回字段完整性

**测试步骤**:
```python
required_fields = [
    'generated_at',
    'elapsed_seconds',
    'total_records',
    'valid_records',
    'valid_records_percent',
    'factor_columns',
    'input_sources',
    'output_path'
]

for field in required_fields:
    assert field in metadata, f"缺少必需字段: {field}"
```

**预期结果**:
- 所有必需字段存在：
  - `generated_at`（生成时间）
  - `elapsed_seconds`（运行耗时）
  - `total_records`（总记录数）
  - `valid_records`（有效记录数）
  - `valid_records_percent`（有效记录百分比）
  - `factor_columns`（因子列列表）
  - `input_sources`（输入源）
  - `output_path`（输出路径）

---

### TC005: 因子列验证

**测试内容**: 验证 factor_columns 返回正确的因子列

**测试步骤**:
```python
expected_factors = ['bollinger_pb', 'kdj_j', 'turnover_surge']
assert metadata['factor_columns'] == expected_factors
```

**预期结果**:
- `factor_columns` 为 `['bollinger_pb', 'kdj_j', 'turnover_surge']`

---

### TC006: 有效记录数验证

**测试内容**: 验证 valid_records 返回正确的有效记录数

**测试步骤**:
```python
for factor, count in metadata['valid_records'].items():
    assert count > 0, f"{factor} 有效记录数为 0"
    assert isinstance(count, int), f"{factor} 有效记录数不是 int 类型"
```

**预期结果**:
- 所有因子有效记录数 > 0
- 有效记录数为 `int` 类型

---

### TC007: 有效记录百分比验证

**测试内容**: 验证 valid_records_percent 返回正确的百分比

**测试步骤**:
```python
for factor, percent in metadata['valid_records_percent'].items():
    assert 0 <= percent <= 100, f"{factor} 百分比超出范围"
    assert isinstance(percent, float), f"{factor} 百分比不是 float 类型"
```

**预期结果**:
- 所有百分比在 [0, 100] 范围内
- 百分比为 `float` 类型

---

### TC008: 输出文件验证

**测试内容**: 验证输出文件存在且结构正确

**测试步骤**:
```python
import gzip
import json
from pathlib import Path

output_path = Path(metadata['output_path'])
assert output_path.exists(), f"输出文件不存在: {output_path}"

with gzip.open(output_path, 'rt') as f:
    output_data = json.load(f)

assert 'dates' in output_data, "输出缺少 dates 字段"
assert 'data' in output_data, "输出缺少 data 字段"
assert len(output_data['dates']) > 0, "dates 列表为空"
assert len(output_data['data']) > 0, "data 列表为空"
```

**预期结果**:
- 输出文件存在
- 输出包含 `dates` 和 `data` 字段
- `dates` 和 `data` 不为空

---

### TC009: 输出数据字段验证

**测试内容**: 验证输出数据包含正确的因子列

**测试步骤**:
```python
expected_columns = [
    'date', 'asset', 'open', 'close', 'high', 'low',
    'rsi_6', 'volume_ratio_5',
    'bollinger_pb', 'kdj_j', 'turnover_surge'
]

first_record = output_data['data'][0]
for col in expected_columns:
    assert col in first_record, f"输出数据缺少列: {col}"
```

**预期结果**:
- 每条记录包含所有 11 个字段

---

### TC010: 运行耗时验证

**测试内容**: 验证 elapsed_seconds 为合理的数值

**测试步骤**:
```python
assert metadata['elapsed_seconds'] > 0, "运行耗时应 > 0"
assert isinstance(metadata['elapsed_seconds'], float), "运行耗时应为 float 类型"
```

**预期结果**:
- `elapsed_seconds` > 0
- `elapsed_seconds` 为 `float` 类型

---

## 异常测试用例

### TC_ERR001: 输入文件不存在

**测试内容**: 验证输入文件不存在时抛出 FileNotFoundError

**测试步骤**:
```python
try:
    generate_all_factors(
        factor_data_path='nonexistent.json.gz',
        turnover_data_path='nonexistent.json.gz'
    )
except FileNotFoundError:
    pass  # 预期抛出 FileNotFoundError
```

**预期结果**:
- 抛出 `FileNotFoundError`

---

### TC_ERR002: JSON 解析失败

**测试内容**: 验证 JSON 解析失败时抛出 ValueError

**测试步骤**:
```python
# 创建无效 JSON 文件
import gzip
invalid_path = Path('invalid.json.gz')
with gzip.open(invalid_path, 'wt') as f:
    f.write('not valid json')

try:
    generate_all_factors(factor_data_path=invalid_path)
except ValueError:
    pass  # 预期抛出 ValueError
finally:
    invalid_path.unlink()
```

**预期结果**:
- 抛出 `ValueError`

---

### TC_ERR003: 数据缺少必需字段

**测试内容**: 验证数据缺少 `data` 字段时抛出 ValueError

**测试步骤**:
```python
import gzip
import json

# 创建缺少 data 字段的 JSON
invalid_data_path = Path('no_data_field.json.gz')
with gzip.open(invalid_data_path, 'wt') as f:
    json.dump({'metadata': {}}, f)

try:
    generate_all_factors(factor_data_path=invalid_data_path)
except ValueError as e:
    assert '缺少' in str(e)
finally:
    invalid_data_path.unlink()
```

**预期结果**:
- 抛出 `ValueError`，错误信息包含"缺少"

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-25 | 创建测试用例文档（10 项正常测试 + 3 项异常测试） |

---

*创建时间: 2026-05-25 10:27 北京时间*