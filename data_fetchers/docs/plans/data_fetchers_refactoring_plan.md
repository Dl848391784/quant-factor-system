# Data Fetchers 重构计划

**版本:** v1.0  
**日期:** 2026-05-27  
**目标:** 按职责拆分 fetch_factor_cache.py 和 data_loader.py，统一因子计算逻辑

---

## 一、重构目标

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| data_loader.py | 2643行 | ~500行 |
| fetch_factor_cache.py | 1210行 | ~300行 |
| factor_ic/ic_*.py | 含 calculate 函数 | 只有 IC 计算 |
| 单文件最大行数 | 2643行 | ~450行 |

---

## 二、目录结构变化

### 重构后结构：
```
data_fetchers/
├── data_loader.py           # ~500行：只负责数据获取
├── factor_calculator.py     # ~350行：统一因子计算
├── fetch_factor_cache.py    # ~300行：调度入口
├── batch_processor.py       # ~450行：批次处理 + N-way合并
├── factor_generator.py      # ~400行：数据合并，调用 factor_calculator
├── common/
│   ├── memory_utils.py      # ~80行：内存监控工具
│   └── dataframe_utils.py   # ~50行：DataFrame验证工具
│   └── cache_manager.py     # 已有
│   └── http_client.py       # 已有
│   └── paths.py             # 已有
│   └── stock_utils.py       # 已有
│   └── logger_config.py     # 已有

factor_ic/
├── ic_rsi_1d.py             # 简化：只有 main() + IC 计算
├── ic_volume_ratio_1d.py    # 简化：只有 main() + IC 计算
├── ic_bollinger_pb_1d.py    # 简化：删除 calculate_bollinger_pb()
├── ic_kdj_j_1d.py           # 简化：删除 calculate_kdj_j()
├── ic_turnover_surge_1d.py  # 简化：删除 calculate_turnover_surge()
```

---

## 三、各文件职责

### 3.1 data_fetchers/data_loader.py（简化后）
- **职责:** 从 API 获取股票历史数据（OHLCV）
- **保留函数:**
  - `RealDataLoader.__init__`
  - `_fetch_stock_batch_parallel`
  - `get_stock_history`
  - 缓存路径管理
- **删除函数:**
  - `get_main_board_stocks` 系列（已废弃）
  - `_wilder_smoothing_rsi`（移到 factor_calculator）
  - `_calculate_rsi_vectorized`（移到 factor_calculator）
  - `winsorize_factor`、`calculate_rank_ic`（冗余）

### 3.2 data_fetchers/factor_calculator.py（新建）
- **职责:** 统一因子计算逻辑
- **包含函数:**
  - `_wilder_smoothing_rsi` - Wilder 平滑算法
  - `calculate_rsi` - RSI 计算
  - `calculate_volume_ratio` - 量比计算
  - `calculate_forward_return` - 前瞻收益
  - `calculate_bollinger_pb` - 布林带 %B
  - `calculate_kdj_j` - KDJ J值
  - `calculate_turnover_surge` - 换手率激增

### 3.3 data_fetchers/batch_processor.py（新建）
- **职责:** 批次处理 + N-way 合并
- **包含函数:**
  - `BatchStream` 类 - 批次流式读取
  - `save_batch_cache_sorted` - 批次保存
  - `n_way_merge_deduplicate` - N-way 合并
  - `format_final_output` - 输出格式化
  - `cleanup_batch_files` - 清理临时文件

### 3.4 data_fetchers/fetch_factor_cache.py（简化）
- **职责:** 入口调度
- **保留函数:**
  - `main()` - 入口
  - `fetch_batch_stocks` - 改为调用 factor_calculator
  - `validate_final_data` - 数据验证

### 3.5 data_fetchers/common/memory_utils.py（新建）
- **职责:** 内存监控工具
- **包含函数:**
  - `get_memory_usage_mb`
  - `get_memory_info_str`

### 3.6 data_fetchers/common/dataframe_utils.py（新建）
- **职责:** DataFrame 验证工具
- **包含函数:**
  - `validate_dataframe_columns`

---

## 四、执行步骤

### Step 1: 新建 common 工具文件
- 创建 `common/memory_utils.py`
- 创建 `common/dataframe_utils.py`
- 更新 `common/__init__.py` 导出

### Step 2: 新建 factor_calculator.py
- 从 `data_loader.py` 提取 RSI 计算函数
- 从 `factor_ic/ic_*.py` 提取因子计算函数
- 整合为统一接口

### Step 3: 新建 batch_processor.py
- 从 `fetch_factor_cache.py` 提取 BatchStream 类
- 从 `fetch_factor_cache.py` 提取合并逻辑

### Step 4: 简化 data_loader.py
- 删除冗余函数
- 保留核心数据获取逻辑

### Step 5: 简化 fetch_factor_cache.py
- 改为调用新模块
- 删除已提取的函数

### Step 6: 更新 factor_generator.py
- 导入改为 `from data_fetchers.factor_calculator import ...`

### Step 7: 简化 factor_ic/ic_*.py
- 删除 calculate 函数
- 改用 `from data_fetchers.factor_calculator import ...`

### Step 8: 更新 MODULE.md
- 添加新模块规范
- 更新版本历史

---

## 五、验证检查项

```
□ 语法检查：python -m py_compile 所有修改文件
□ 导入验证：python -c "from data_fetchers.factor_calculator import ..."
□ 功能验证：运行 fetch_factor_cache.py 验证数据输出
□ 功能验证：运行 factor_generator.py 验证数据合并
□ 功能验证：运行 ic_rsi_1d.py 验证 IC 计算
□ 行数检查：确认单文件不超过 500 行
□ MODULE.md 更新：版本历史 + 新模块规范
```

---

## 六、风险控制

- **分步执行:** 每步完成后验证，再继续下一步
- **语法检查:** 每次修改后立即 `python -m py_compile`
- **Git commit:** 每个阶段完成后 commit，不等待全部完成