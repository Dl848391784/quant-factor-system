# fetch_stock_list 测试用例

> 版本: v1.0
> 创建时间: 2026-05-27 06:10 北京时间

---

## 正常测试

### TC001: 模块导入测试

**输入**: 导入模块

**预期**: 导入成功，__all__ 包含 5 个函数

```bash
python3 -c "from data_fetchers.fetch_stock_list import refresh_stock_cache, load_cache, get_cached_stock_codes, is_valid_main_board_stock, determine_market; print('导入成功')"
```

### TC002: 主板股票筛选测试

**输入**: 沪市主板股票代码

**预期**: 返回 True

```bash
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('600000', '浦发银行'))"
```

**预期输出**: `True`

### TC003: 创业板剔除测试

**输入**: 创业板股票代码

**预期**: 返回 False

```bash
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('300001', '特锐德'))"
```

**预期输出**: `False`

### TC004: 科创板剔除测试

**输入**: 科创板股票代码

**预期**: 返回 False

```bash
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('688001', '华兴源创'))"
```

**预期输出**: `False`

### TC005: ST股票剔除测试

**输入**: ST股票名称

**预期**: 返回 False

```bash
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('600001', 'ST康美'))"
```

**预期输出**: `False`

### TC006: 市场判断测试

**输入**: 沪市股票代码

**预期**: 返回 'sh'

```bash
python3 -c "from data_fetchers.fetch_stock_list import determine_market; print(determine_market('600000'))"
```

**预期输出**: `sh`

### TC007: __all__ 导出测试

**输入**: 检查 __all__

**预期**: 包含 5 个函数名

```bash
python3 -c "from data_fetchers.fetch_stock_list import __all__; print(__all__)"
```

**预期输出**: `['refresh_stock_cache', 'load_cache', 'get_cached_stock_codes', 'is_valid_main_board_stock', 'determine_market']`

---

## 边界测试

### TC008: 空股票代码测试

**输入**: 空字符串

**预期**: 返回 False（无效主板股票）

```bash
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; print(is_valid_main_board_stock('', '测试'))"
```

**预期输出**: `False`

### TC009: 未知市场测试

**输入**: 非主板代码

**预期**: 返回 'unknown'

```bash
python3 -c "from data_fetchers.fetch_stock_list import determine_market; print(determine_market('999999'))"
```

**预期输出**: `unknown`

### TC010: 缓存不存在测试

**输入**: 无缓存文件时加载

**预期**: 返回 None

```bash
# 需要先删除缓存文件
python3 -c "from data_fetchers.fetch_stock_list import load_cache; print(load_cache())"
```

**预期输出**: `None`（如果缓存不存在）

---

## 集成测试

### TC011: 完整流程测试

**输入**: 执行 refresh_stock_cache

**预期**: 返回成功结果

```bash
python data_fetchers/fetch_stock_list.py
```

**预期输出**:
- 日志文件: `logs/fetch_stock_list_2026-05-27.log`
- 缓存文件: `cache/stock_list.json`
- 结果文件: `result/stock_list_meta.json`
- 总数: 约 3000 只

---

## 验证命令清单

```bash
# 1. 验证导入
cd /home/admin/projects/factor_ic_analyzer
python3 -c "from data_fetchers.fetch_stock_list import refresh_stock_cache, load_cache, get_cached_stock_codes, is_valid_main_board_stock, determine_market; print('导入成功')"

# 2. 验证 __all__
python3 -c "from data_fetchers.fetch_stock_list import __all__; print(__all__)"

# 3. 验证筛选逻辑
python3 -c "from data_fetchers.fetch_stock_list import is_valid_main_board_stock; assert is_valid_main_board_stock('600000', '浦发银行') == True; assert is_valid_main_board_stock('300001', '特锐德') == False; assert is_valid_main_board_stock('688001', '华兴源创') == False; print('筛选逻辑验证通过')"

# 4. 运行完整流程
python data_fetchers/fetch_stock_list.py

# 5. 检查输出文件
ls -la cache/stock_list.json result/stock_list_meta.json logs/fetch_stock_list_*.log
```