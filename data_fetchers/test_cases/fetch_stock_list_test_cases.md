     1|# fetch_stock_list 测试用例
     2|
     3|> 版本: v1.0
     4|> 创建时间: 2026-05-27 06:10 北京时间
     5|
     6|---
     7|
     8|## 正常测试
     9|
    10|### TC001: 模块导入测试
    11|
    12|**输入**: 导入模块
    13|
    14|**预期**: 导入成功，__all__ 包含 5 个函数
    15|
    16|```bash
    17|python3 -c "from data_fetchers.fetch_stock_list import refresh_stock_cache, load_cache, get_cached_stock_codes, is_valid_main_board_stock, determine_market; print('导入成功')"
    18|```
    19|
    20|### TC002: 主板股票筛选测试
    21|
    22|**输入**: 沪市主板股票代码
    23|
    24|**预期**: 返回 True
    25|
    26|```bash
    27|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('600000', '浦发银行'))"
    28|```
    29|
    30|**预期输出**: `True`
    31|
    32|### TC003: 创业板剔除测试
    33|
    34|**输入**: 创业板股票代码
    35|
    36|**预期**: 返回 False
    37|
    38|```bash
    39|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('300001', '特锐德'))"
    40|```
    41|
    42|**预期输出**: `False`
    43|
    44|### TC004: 科创板剔除测试
    45|
    46|**输入**: 科创板股票代码
    47|
    48|**预期**: 返回 False
    49|
    50|```bash
    51|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('688001', '华兴源创'))"
    52|```
    53|
    54|**预期输出**: `False`
    55|
    56|### TC005: ST股票剔除测试
    57|
    58|**输入**: ST股票名称
    59|
    60|**预期**: 返回 False
    61|
    62|```bash
    63|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('600001', 'ST康美'))"
    64|```
    65|
    66|**预期输出**: `False`
    67|
    68|### TC006: 市场判断测试
    69|
    70|**输入**: 沪市股票代码
    71|
    72|**预期**: 返回 'sh'
    73|
    74|```bash
    75|python3 -c "from data_fetchers.fetch_stock_list import determine_market; print(determine_market('600000'))"
    76|```
    77|
    78|**预期输出**: `sh`
    79|
    80|### TC007: __all__ 导出测试
    81|
    82|**输入**: 检查 __all__
    83|
    84|**预期**: 包含 5 个函数名
    85|
    86|```bash
    87|python3 -c "from data_fetchers.fetch_stock_list import __all__; print(__all__)"
    88|```
    89|
    90|**预期输出**: `['refresh_stock_cache', 'load_cache', 'get_cached_stock_codes', 'is_valid_main_board_stock', 'determine_market']`
    91|
    92|---
    93|
    94|## 边界测试
    95|
    96|### TC008: 空股票代码测试
    97|
    98|**输入**: 空字符串
    99|
   100|**预期**: 返回 False（无效主板股票）
   101|
   102|```bash
   103|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('', '测试'))"
   104|```
   105|
   106|**预期输出**: `False`
   107|
   108|### TC009: 未知市场测试
   109|
   110|**输入**: 非主板代码
   111|
   112|**预期**: 返回 'unknown'
   113|
   114|```bash
   115|python3 -c "from data_fetchers.fetch_stock_list import determine_market; print(determine_market('999999'))"
   116|```
   117|
   118|**预期输出**: `unknown`
   119|
   120|### TC010: 缓存不存在测试
   121|
   122|**输入**: 无缓存文件时加载
   123|
   124|**预期**: 返回 None
   125|
   126|```bash
   127|# 需要先删除缓存文件
   128|python3 -c "from data_fetchers.fetch_stock_list import load_cache; print(load_cache())"
   129|```
   130|
   131|**预期输出**: `None`（如果缓存不存在）
   132|
   133|---
   134|
   135|## 集成测试
   136|
   137|### TC011: 完整流程测试
   138|
   139|**输入**: 执行 refresh_stock_cache
   140|
   141|**预期**: 返回成功结果
   142|
   143|```bash
   144|python data_fetchers/fetch_stock_list.py
   145|```
   146|
   147|**预期输出**:
   148|- 日志文件: `logs/fetch_stock_list_2026-05-27.log`
   149|- 缓存文件: `data_fetchers/result/stock_list.json`
   150|- 结果文件: `result/stock_list_meta.json`
   151|- 总数: 约 3000 只
   152|
   153|---
   154|
   155|## 验证命令清单
   156|
   157|```bash
   158|# 1. 验证导入
   159|cd /home/admin/projects/factor_ic_analyzer
   160|python3 -c "from data_fetchers.fetch_stock_list import refresh_stock_cache, load_cache, get_cached_stock_codes, is_valid_main_board_stock, determine_market; print('导入成功')"
   161|
   162|# 2. 验证 __all__
   163|python3 -c "from data_fetchers.fetch_stock_list import __all__; print(__all__)"
   164|
   165|# 3. 验证筛选逻辑
   166|python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; assert is_valid_main_board_stock('600000', '浦发银行') == True; assert is_valid_main_board_stock('300001', '特锐德') == False; assert is_valid_main_board_stock('688001', '华兴源创') == False; print('筛选逻辑验证通过')"
   167|
   168|# 4. 运行完整流程
   169|python data_fetchers/fetch_stock_list.py
   170|
   171|# 5. 检查输出文件
   172|ls -la data_fetchers/result/stock_list.json result/stock_list_meta.json logs/fetch_stock_list_*.log
   173|```