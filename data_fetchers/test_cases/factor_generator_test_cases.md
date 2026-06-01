     1|# factor_generator.py 测试用例
     2|
     3|> 版本: v1.0
     4|> 创建时间: 2026-05-25 10:27 北京时间
     5|> 脚本路径: `data_fetchers/factor_generator.py`
     6|
     7|---
     8|
     9|## 测试环境
    10|
    11|**前置条件**:
    12|- 输入数据文件存在：
    13|  - `data_fetchers/result/factor_data.json.gz`
    14|  - `data_fetchers/result/turnover_rate_data.json.gz`
    15|
    16|**运行方式**:
    17|```bash
    18|python data_fetchers/factor_generator.py
    19|```
    20|
    21|---
    22|
    23|## 测试用例清单
    24|
    25|### TC001: 导入验证
    26|
    27|**测试内容**: 验证模块导入成功
    28|
    29|**测试步骤**:
    30|```python
    31|from data_fetchers.factor_generator import generate_all_factors, get_module_logger
    32|```
    33|
    34|**预期结果**:
    35|- `generate_all_factors` 导入成功
    36|- `get_module_logger` 导入成功
    37|
    38|---
    39|
    40|### TC002: get_module_logger 验证
    41|
    42|**测试内容**: 验证 get_module_logger 返回正确的 logger
    43|
    44|**测试步骤**:
    45|```python
    46|import logging
    47|
    48|# 测试 1: 不传参数返回模块级 logger
    49|module_logger = get_module_logger()
    50|assert module_logger.name == 'data_fetchers.factor_generator'
    51|
    52|# 测试 2: 传入自定义 logger
    53|custom_logger = logging.getLogger('my_app')
    54|returned_logger = get_module_logger(custom_logger)
    55|assert returned_logger.name == 'my_app'
    56|
    57|# 测试 3: 传入非 Logger 类型抛 TypeError
    58|try:
    59|    get_module_logger('invalid')
    60|except TypeError:
    61|    pass  # 预期抛出 TypeError
    62|```
    63|
    64|**预期结果**:
    65|- 不传参数返回 `'data_fetchers.factor_generator'` logger
    66|- 传入自定义 logger 返回该 logger
    67|- 传入非 Logger 类型抛 `TypeError`
    68|
    69|---
    70|
    71|### TC003: generate_all_factors 验证
    72|
    73|**测试内容**: 验证 generate_all_factors 返回正确的元数据结构
    74|
    75|**测试步骤**:
    76|```python
    77|import logging
    78|from data_fetchers.common.logger_config import setup_logger
    79|
    80|logger = setup_logger('test_factor_generator', level=logging.INFO)
    81|metadata = generate_all_factors(logger=logger)
    82|```
    83|
    84|**预期结果**:
    85|- 返回类型为 `dict`
    86|- 返回不为空
    87|
    88|---
    89|
    90|### TC004: 返回字段验证
    91|
    92|**测试内容**: 验证 metadata 返回字段完整性
    93|
    94|**测试步骤**:
    95|```python
    96|required_fields = [
    97|    'generated_at',
    98|    'elapsed_seconds',
    99|    'total_records',
   100|    'valid_records',
   101|    'valid_records_percent',
   102|    'factor_columns',
   103|    'input_sources',
   104|    'output_path'
   105|]
   106|
   107|for field in required_fields:
   108|    assert field in metadata, f"缺少必需字段: {field}"
   109|```
   110|
   111|**预期结果**:
   112|- 所有必需字段存在：
   113|  - `generated_at`（生成时间）
   114|  - `elapsed_seconds`（运行耗时）
   115|  - `total_records`（总记录数）
   116|  - `valid_records`（有效记录数）
   117|  - `valid_records_percent`（有效记录百分比）
   118|  - `factor_columns`（因子列列表）
   119|  - `input_sources`（输入源）
   120|  - `output_path`（输出路径）
   121|
   122|---
   123|
   124|### TC005: 因子列验证
   125|
   126|**测试内容**: 验证 factor_columns 返回正确的因子列
   127|
   128|**测试步骤**:
   129|```python
   130|expected_factors = ['bollinger_pb', 'kdj_j', 'turnover_surge']
   131|assert metadata['factor_columns'] == expected_factors
   132|```
   133|
   134|**预期结果**:
   135|- `factor_columns` 为 `['bollinger_pb', 'kdj_j', 'turnover_surge']`
   136|
   137|---
   138|
   139|### TC006: 有效记录数验证
   140|
   141|**测试内容**: 验证 valid_records 返回正确的有效记录数
   142|
   143|**测试步骤**:
   144|```python
   145|for factor, count in metadata['valid_records'].items():
   146|    assert count > 0, f"{factor} 有效记录数为 0"
   147|    assert isinstance(count, int), f"{factor} 有效记录数不是 int 类型"
   148|```
   149|
   150|**预期结果**:
   151|- 所有因子有效记录数 > 0
   152|- 有效记录数为 `int` 类型
   153|
   154|---
   155|
   156|### TC007: 有效记录百分比验证
   157|
   158|**测试内容**: 验证 valid_records_percent 返回正确的百分比
   159|
   160|**测试步骤**:
   161|```python
   162|for factor, percent in metadata['valid_records_percent'].items():
   163|    assert 0 <= percent <= 100, f"{factor} 百分比超出范围"
   164|    assert isinstance(percent, float), f"{factor} 百分比不是 float 类型"
   165|```
   166|
   167|**预期结果**:
   168|- 所有百分比在 [0, 100] 范围内
   169|- 百分比为 `float` 类型
   170|
   171|---
   172|
   173|### TC008: 输出文件验证
   174|
   175|**测试内容**: 验证输出文件存在且结构正确
   176|
   177|**测试步骤**:
   178|```python
   179|import gzip
   180|import json
   181|from pathlib import Path
   182|
   183|output_path = Path(metadata['output_path'])
   184|assert output_path.exists(), f"输出文件不存在: {output_path}"
   185|
   186|with gzip.open(output_path, 'rt') as f:
   187|    output_data = json.load(f)
   188|
   189|assert 'dates' in output_data, "输出缺少 dates 字段"
   190|assert 'data' in output_data, "输出缺少 data 字段"
   191|assert len(output_data['dates']) > 0, "dates 列表为空"
   192|assert len(output_data['data']) > 0, "data 列表为空"
   193|```
   194|
   195|**预期结果**:
   196|- 输出文件存在
   197|- 输出包含 `dates` 和 `data` 字段
   198|- `dates` 和 `data` 不为空
   199|
   200|---
   201|
   202|### TC009: 输出数据字段验证
   203|
   204|**测试内容**: 验证输出数据包含正确的因子列
   205|
   206|**测试步骤**:
   207|```python
   208|expected_columns = [
   209|    'date', 'asset', 'open', 'close', 'high', 'low',
   210|    'rsi_6', 'volume_ratio_5',
   211|    'bollinger_pb', 'kdj_j', 'turnover_surge'
   212|]
   213|
   214|first_record = output_data['data'][0]
   215|for col in expected_columns:
   216|    assert col in first_record, f"输出数据缺少列: {col}"
   217|```
   218|
   219|**预期结果**:
   220|- 每条记录包含所有 11 个字段
   221|
   222|---
   223|
   224|### TC010: 运行耗时验证
   225|
   226|**测试内容**: 验证 elapsed_seconds 为合理的数值
   227|
   228|**测试步骤**:
   229|```python
   230|assert metadata['elapsed_seconds'] > 0, "运行耗时应 > 0"
   231|assert isinstance(metadata['elapsed_seconds'], float), "运行耗时应为 float 类型"
   232|```
   233|
   234|**预期结果**:
   235|- `elapsed_seconds` > 0
   236|- `elapsed_seconds` 为 `float` 类型
   237|
   238|---
   239|
   240|## 异常测试用例
   241|
   242|### TC_ERR001: 输入文件不存在
   243|
   244|**测试内容**: 验证输入文件不存在时抛出 FileNotFoundError
   245|
   246|**测试步骤**:
   247|```python
   248|try:
   249|    generate_all_factors(
   250|        factor_data_path='nonexistent.json.gz',
   251|        turnover_data_path='nonexistent.json.gz'
   252|    )
   253|except FileNotFoundError:
   254|    pass  # 预期抛出 FileNotFoundError
   255|```
   256|
   257|**预期结果**:
   258|- 抛出 `FileNotFoundError`
   259|
   260|---
   261|
   262|### TC_ERR002: JSON 解析失败
   263|
   264|**测试内容**: 验证 JSON 解析失败时抛出 ValueError
   265|
   266|**测试步骤**:
   267|```python
   268|# 创建无效 JSON 文件
   269|import gzip
   270|invalid_path = Path('invalid.json.gz')
   271|with gzip.open(invalid_path, 'wt') as f:
   272|    f.write('not valid json')
   273|
   274|try:
   275|    generate_all_factors(factor_data_path=invalid_path)
   276|except ValueError:
   277|    pass  # 预期抛出 ValueError
   278|finally:
   279|    invalid_path.unlink()
   280|```
   281|
   282|**预期结果**:
   283|- 抛出 `ValueError`
   284|
   285|---
   286|
   287|### TC_ERR003: 数据缺少必需字段
   288|
   289|**测试内容**: 验证数据缺少 `data` 字段时抛出 ValueError
   290|
   291|**测试步骤**:
   292|```python
   293|import gzip
   294|import json
   295|
   296|# 创建缺少 data 字段的 JSON
   297|invalid_data_path = Path('no_data_field.json.gz')
   298|with gzip.open(invalid_data_path, 'wt') as f:
   299|    json.dump({'metadata': {}}, f)
   300|
   301|try:
   302|    generate_all_factors(factor_data_path=invalid_data_path)
   303|except ValueError as e:
   304|    assert '缺少' in str(e)
   305|finally:
   306|    invalid_data_path.unlink()
   307|```
   308|
   309|**预期结果**:
   310|- 抛出 `ValueError`，错误信息包含"缺少"
   311|
   312|---
   313|
   314|## 版本历史
   315|
   316|| 版本 | 日期 | 更新内容 |
   317||------|------|---------|
   318|| v1.0 | 2026-05-25 | 创建测试用例文档（10 项正常测试 + 3 项异常测试） |
   319|
   320|---
   321|
   322|*创建时间: 2026-05-25 10:27 北京时间*