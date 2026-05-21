# factor_ic/common 公共模块

> 版本: v1.0
> 创建时间: 2026-05-22
> 最后更新: 2026-05-22

## 设计目标

**核心问题：** 5个因子IC脚本存在大量重复代码（45%-70%），新增因子开发成本高。

**解决方案：** 抽取公共模块，新增因子只需实现因子计算逻辑。

| 模块 | 功能 | 每脚本减少行数 |
|------|------|----------------|
| `data_loader.py` | 数据加载（gzip解压、日期转换、列验证） | ~80-120行 |
| `ic_result_builder.py` | IC结果构建（统一输出结构） | ~60-100行 |
| `incremental_engine.py` | 增量更新引擎 | ~150-200行 |
| `factor_ic_runner.py` | 主入口模板 | ~100-150行 |

**预期效果：** 新增因子脚本从 ~700-1100行 降至 ~50-200行。

---

## convert_types.py — 类型转换模块

**文件路径：** `factor_ic/common/convert_types.py`

### 核心函数

```python
def convert_to_native_types(obj: Any) -> Any:
    """
    递归转换 numpy/pandas 类型为 Python 原生类型
    
    解决 JSON 序列化时 numpy 类型无法直接序列化的问题。
    """
```

### 类型检查规范（2026-05-22）

| 类型 | 检查方式 | 说明 |
|------|---------|------|
| numpy整数 | `isinstance(obj, np.integer)` | 抽象基类覆盖所有子类 |
| numpy浮点 | `isinstance(obj, np.floating)` | 抽象基类覆盖所有子类 |
| numpy布尔 | `isinstance(obj, np.bool_)` | **必须显式分开**，不能与 bool 合并 |
| Python布尔 | `isinstance(obj, bool)` | **必须在 integer 之前**，因为 bool 是 int 子类 |
| Python整数 | 直接返回 | 不需要类型检查（原生类型） |
| Python浮点 | `isinstance(obj, float)` | 用 `math.isnan` 检查 NaN（标准库） |

### NaN 检查规范（重要）

**必须使用类型匹配的 isnan 函数：**

| 浮点类型 | 正确写法 | 错误写法 |
|---------|---------|---------|
| numpy浮点 | `np.isnan(obj)` | `math.isnan(obj)` |
| Python float | `math.isnan(obj)` | `np.isnan(obj)` |

**错误写法示例：**
```python
# 错误写法（语义不准确）
elif isinstance(obj, float):
    if np.isnan(obj):  # numpy 函数处理 Python 类型
        return None

# 正确写法（类型匹配）
elif isinstance(obj, float):
    if math.isnan(obj):  # 标准库处理 Python 类型
        return None
```

**原因：**
1. `np.isnan` 是为 numpy 类型设计的，处理 Python float 是额外支持
2. `math.isnan` 是标准库函数，专为 Python float 设计，语义更准确
3. 类型匹配更轻量、语义清晰，减少不必要的依赖

**参考：** convert_types.py 源码注释（2026-05-22 更新）

### isinstance 多类型检查规范（重要）

**禁止合并写法：**
```python
# 错误写法（脆弱，依赖分支顺序）
elif isinstance(obj, (np.bool_, bool)):
    return bool(obj)

# 正确写法（显式分开处理）
elif isinstance(obj, np.bool_):
    return bool(obj)
elif isinstance(obj, bool):
    return obj
```

**原因：**
1. bool 是 int 的子类，`isinstance(True, int)` 返回 True
2. 若有人在未来添加 `isinstance(obj, int)` 分支在 bool 检查之前，合并写法会将 True/False 误判为整数
3. 显式分开处理：意图清晰，防止分支顺序变化导致的隐蔽 bug

### 单例检查规范（重要）

**必须用 `is` 判断单例对象：**

| 单例对象 | 正确写法 | 错误写法 |
|---------|---------|---------|
| pd.NaT | `obj is pd.NaT` | `isinstance(obj, type(pd.NaT))` |
| pd.NA | `obj is pd.NA` | `isinstance(obj, type(pd.NA))` |
| None | `obj is None` | `isinstance(obj, type(None))` |

**错误写法示例：**
```python
# 错误写法（冗余 + 依赖私有类）
elif obj is pd.NA or isinstance(obj, type(pd.NA)):
    return None

# 正确写法（单例用 is 即可）
elif obj is pd.NA:
    return None
```

**原因：**
1. 单例对象（如 pd.NA、pd.NaT、None）全局唯一，`is` 检查完全覆盖
2. `isinstance(obj, type(singleton))` 依赖私有内部类（如 `pandas.core.arrays.masked.NAType`），跨版本不稳定
3. isinstance 检查单例是冗余的，增加不必要的类型查找开销

**参考：** convert_types.py 源码注释（2026-05-22 更新）

### 分支依赖关系（重要）

**pd.Series.tolist() 与 pd.NA 处理的依赖关系：**

```
pd.Series 分支 → obj is pd.NA 分支
```

**原因：**
- 扩展类型 Series（如 `pd.Series([1, pd.NA], dtype='Int64')`）的 `.tolist()` 返回 `[1, pd.NA]`，而非 `[1, None]`
- 后续递归调用 `convert_to_native_types` 会处理列表中的 pd.NA
- 若误删 `obj is pd.NA` 分支，扩展类型 Series 的缺失值无法转换为 None

**维护警告：**
- `pd.Series` 分支依赖 `obj is pd.NA` 分支正确工作
- 删除 `pd.NA` 分支前必须确认无扩展类型 Series 使用场景

**参考：** convert_types.py 第98-103行注释（2026-05-22 更新）

---

## data_completeness.py — 数据完整性检查模块

**文件路径：** `factor_ic/common/data_completeness.py`

### 核心函数

| 函数 | 用途 |
|------|------|
| `check_data_completeness()` | 检查数据完整性，返回处理模式（full/incremental/skip） |
| `get_factor_data_dates()` | 获取因子数据日期列表 |
| `get_cache_latest_date()` | 获取缓存最新日期 |
| `get_cache_info()` | 获取缓存信息摘要 |
| `_extract_dates_from_cache()` | 公共函数：从缓存数据提取日期（内部使用） |

### 日期提取规范（重要）

**缓存日期提取必须使用公共函数 `_extract_dates_from_cache()`：**

```python
# 错误写法（逻辑不一致）
# get_cache_latest_date() 优先顶层 dates
# get_cache_info() 只读 ic_series.dates
# 同一文件返回不同日期

# 正确写法（统一处理）
def get_cache_latest_date(factor_name: str):
    dates, latest_date = _extract_dates_from_cache(result)
    return latest_date

def get_cache_info(factor_name: str):
    dates, latest_date = _extract_dates_from_cache(data)
    info['n_days'] = len(dates)
    info['latest_date'] = latest_date
```

**公共函数逻辑（`_extract_dates_from_cache()`）：**
1. 优先读取顶层 `dates` 字段（新格式）
2. 兼容旧格式：`ic_series.dates`
3. 格式统一：处理 `"2026-04-03 00:00:00"` → `"2026-04-03"`
4. 返回 `(dates, latest_date)` 元组

**原因：**
- 统一日期提取逻辑，避免不同函数返回不同日期
- 格式统一处理，防止 `"YYYY-MM-DD HH:MM:SS"` 格式污染下游逻辑

**参考：** data_completeness.py 第80-117行（公共函数定义）

### JSON 数据日期提取规范（重要）

**日期格式必须在源头统一标准化为 YYYY-MM-DD：**

```python
# 错误写法（格式不一致）
# get_factor_data_dates() 返回 "2026-04-03 00:00:00"
# _extract_dates_from_cache() 返回 "2026-04-03"
# 字符串比较 "2026-04-03 00:00:00" > "2026-04-03" 结果错误

# 正确写法（源头统一标准化）
def get_factor_data_dates():
    dates = meta.get('dates', [])
    if dates:
        # 格式统一：处理 "2026-04-03 00:00:00" → "2026-04-03"
        normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]
        dates = normalized_dates
    return dates
```

**标准化位置：**
- `get_factor_data_dates()`：因子数据源日期提取时标准化
- `_extract_dates_from_cache()`：缓存数据日期提取时标准化

**标准化顺序（重要）：必须先标准化，再去重排序**

```python
# 错误写法（顺序错误）
dates = sorted(set(dates))  # 先去重排序
normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]  # 后标准化
dates = normalized_dates  # 可能产生重复（"2026-04-03" + "2026-04-03 12:00:00" → 两个 "2026-04-03")

# 正确写法（先 str() 转换，再截断，最后去重排序）
dates = [str(d) for d in dates]  # 先统一转换为字符串（防止 datetime 对象）
normalized_dates = [d.split()[0] if ' ' in d else d for d in dates]  # 再截断时间戳
dates = sorted(set(normalized_dates))  # 最后去重排序
```

**完整标准化流程：**
1. **str() 转换**：将 datetime/int/Timestamp 等非字符串类型转换为字符串（防止 TypeError）
2. **截断时间戳**：处理 `"2026-04-03 00:00:00"` → `"2026-04-03"`（确保格式一致）
3. **去重排序**：sorted + set 去除截断后的重复项

**原因：**
1. 若原始数据存在 `"2026-04-03"` 和 `"2026-04-03 12:00:00"` 混合格式
2. 先去重排序无法去除截断后的重复项（sorted + set 在截断之前完成）
3. meta.dates 可能包含 datetime 对象，`' ' in d` 检查会抛出 TypeError
4. 先 str() 转换确保类型一致，再截断，最后去重排序

**参考：** data_completeness.py 第71-80行（2026-05-22 更新）

**原因：**
1. JSON 中的日期可能包含时间戳 `"YYYY-MM-DD HH:MM:SS"` 或 datetime 对象
2. 字符串比较依赖格式一致性：`"2026-04-03 00:00:00" > "2026-04-03"` 因空格导致错误结果
3. 标准化必须在源头进行，而非在使用前临时处理

**影响范围：**
- `check_data_completeness()` 使用 `d > cache_latest` 进行日期比较
- 所有日期比较逻辑依赖 YYYY-MM-DD 格式一致性

**参考：** data_completeness.py 第70-78行、第106-115行（2026-05-22 更新）

**从 JSON 数据中提取日期时，必须强制转换为字符串：**

```python
# 错误写法（类型不一致隐患）
dates = sorted(set(r.get('date') for r in data.get('data', []) if r.get('date')))

# 正确写法（强制 str 转换，防止 TypeError）
dates = sorted(set(str(r['date']) for r in data.get('data', []) if r.get('date') is not None))
```

**原因：**
1. JSON 中的 date 字段可能是 datetime、int、Timestamp 等非字符串类型
2. `sorted()` 对混合类型会抛出 TypeError（如 `sorted(['2026-01-01', datetime(2026,1,2)])`）
3. `str()` 强制转换确保类型一致性，避免运行时错误

**过滤条件：**
- 使用 `r.get('date') is not None` 而非 `if r.get('date')`
- `if r.get('date')` 会过滤掉空字符串 `''`，但空字符串可能是有效日期（不应过滤）
- `is not None` 只过滤真正的缺失值，语义更准确

**参考：** data_completeness.py 第66-69行（2026-05-22 更新）

---

## data_loader.py — 数据加载公共模块

**文件路径：** `factor_ic/common/data_loader.py`

### 核心函数

```python
def load_factor_return_data(
    factor_cols: List[str],
    return_col: str = 'forward_return_1d',
    factor_cache_path: Optional[Path] = None,
    return_cache_path: Optional[Path] = None,
    dropna_cols: Optional[List[str]] = None,
    validate_date_alignment: bool = True,
    additional_factor_files: Optional[Dict[str, Path]] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    从缓存加载因子数据和收益数据
    
    返回:
        (factor_df, return_df, raw_metadata)
        - raw_metadata: 原始数据元信息（period_start, period_end, total_days, avg_stocks_per_day）
    """
```

### 功能列表

| 功能 | 描述 | 防御性检查 |
|------|------|------------|
| gzip解压 + JSON加载 | 从缓存读取数据 | FileNotFoundError（可恢复） |
| 日期类型转换 | 统一为 YYYY-MM-DD | NaT检查 + 无效样本显示 |
| 列存在验证 | 检查必需列存在 | KeyError + 显示可用列列表 |
| dropna前记录metadata | 原始数据范围 | 保留原始语义 |
| dropna过滤 | 去除缺失值 | 指定过滤列 |
| 日期对齐验证 | 因子 vs 收益日期 | 选择交集日期（可选） |
| 额外因子文件合并 | 如换手率数据 | 内连接合并 |

### 使用示例

```python
from factor_ic.common.data_loader import load_factor_return_data

# RSI因子（直接用缓存列）
factor_df, return_df, raw_metadata = load_factor_return_data(
    factor_cols=['rsi_6']
)

# KDJ因子（需要 close, high, low）
factor_df, return_df, raw_metadata = load_factor_return_data(
    factor_cols=['close', 'high', 'low']
)

# 换手率突增（需要额外文件）
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
factor_df, return_df, raw_metadata = load_factor_return_data(
    factor_cols=['close'],
    additional_factor_files={
        'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    }
)

# 查看原始数据范围
print(f"原始数据: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
print(f"原始天数: {raw_metadata['total_days']}")
print(f"原始平均股票数: {raw_metadata['avg_stocks_per_day']}")
```

### 辅助函数

| 函数 | 用途 |
|------|------|
| `get_cache_dir()` | 获取缓存目录路径 |
| `get_factor_cache_path()` | 获取因子缓存文件路径 |
| `get_return_cache_path()` | 获取收益缓存文件路径 |

### 规范要点

1. `raw_metadata` 在 dropna 之前记录，保留原始数据语义
2. `period_start/end` 为字符串格式 `YYYY-MM-DD`
3. 日期转换后 `isin` 操作类型匹配
4. 列缺失时显示可用列列表（用户友好）
5. **参数污染禁止**：函数内禁止修改参数（特别是可变参数如 List[str]）

### 参数污染规范（重要）

**禁止修改传入的参数：**

```python
# 错误写法（参数污染）
def load_factor_return_data(factor_cols: List[str], additional_factor_files: Dict = None):
    if additional_factor_files:
        # 直接修改参数，污染调用方，调用方无感知
        factor_cols = list(set(factor_cols) | set(additional_factor_files.keys()))
        # set 合并后丢失顺序

# 正确写法（使用独立变量）
def load_factor_return_data(factor_cols: List[str], additional_factor_files: Dict = None):
    all_factor_cols = factor_cols  # 独立变量，不污染调用方
    if additional_factor_files:
        # 保持顺序：先 factor_cols，再追加不在 factor_cols 的额外列
        all_factor_cols = factor_cols + [k for k in additional_factor_files.keys() if k not in factor_cols]
```

**原因：**
1. Python 参数是引用传递，修改参数会影响调用方
2. 调用方传入 `factor_cols=['close']`，函数内修改为 `['close', 'turnover_rate']`
3. 调用方后续代码可能依赖原 `factor_cols`，导致逻辑错误
4. `list(set(...))` 丢失顺序，语义不确定

**影响范围：**
- `load_factor_return_data()` 的 `factor_cols` 参数
- 任何可变参数（List、Dict、Set）的函数内修改

**参考：** data_loader.py 第120行（all_factor_cols 独立变量定义）

### dropna_cols 默认值规范（重要）

**默认值应在参数修改之前确定：**

```python
# 错误写法（隐式包含额外列）
def load_factor_return_data(factor_cols, additional_factor_files=None):
    all_factor_cols = factor_cols
    if additional_factor_files:
        all_factor_cols = factor_cols + list(additional_factor_files.keys())
    # dropna_cols 默认值在参数修改之后确定，隐式包含额外列
    dropna_cols = all_factor_cols

# 正确写法（在修改之前确定）
def load_factor_return_data(factor_cols, additional_factor_files=None):
    # 在修改 factor_cols 之前，确定 dropna_cols 默认值
    default_dropna_cols = factor_cols
    
    all_factor_cols = factor_cols
    if additional_factor_files:
        all_factor_cols = factor_cols + list(additional_factor_files.keys())
    # dropna_cols 默认值基于原始 factor_cols，不含额外列
    dropna_cols = default_dropna_cols
```

**原因：**
1. 用户传入 `factor_cols=['close']`，预期 dropna 默认只过滤 'close'
2. 若 dropna_cols 在参数修改之后确定，会隐式包含额外列（如 'turnover_rate'）
3. 隐式行为导致过多数据被过滤，用户未预期
4. 若用户需要过滤额外列，需显式传入 `dropna_cols` 参数

**参考：** data_loader.py 第122行（default_dropna_cols 定义）

### inner join 数据丢失告知规范（重要）

**合并额外因子文件时必须告知数据丢失情况：**

```python
# 错误写法（静默丢失数据）
factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
print(f"  - 合并 {col_name} 后: {len(factor_df)} 行")  # 只打印结果行数

# 正确写法（告知数据丢失）
rows_before = len(factor_df)
factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
rows_after = len(factor_df)
rows_lost = rows_before - rows_after

if rows_lost > 0:
    print(f"  - 合并 {col_name} 后: {rows_after} 行（丢失 {rows_lost} 行，{rows_lost/rows_before*100:.1f}%）")
else:
    print(f"  - 合并 {col_name} 后: {rows_after} 行（无数据丢失）")
```

**原因：**
1. inner join 会静默丢弃不匹配的行（如额外因子文件缺少某些日期/股票）
2. 只打印合并后行数，用户无法感知数据丢失
3. 数据丢失可能导致下游分析结果偏差，排查困难
4. 打印丢失行数和百分比，帮助用户判断数据质量

**输出示例：**
- 有数据丢失：`合并 turnover_rate 后: 15000 行（丢失 500 行，3.2%）`
- 无数据丢失：`合并 turnover_rate 后: 15500 行（无数据丢失）`

**参考：** data_loader.py 第142-154行（合并前后对比行数）

### raw_metadata 计算规范（重要）

**必须在所有 merge 前快照原始数据：**

```python
# 错误写法（在 inner join 后计算，已不是"原始缓存"数据）
factor_df = pd.merge(factor_df, additional_df, on=['date', 'asset'], how='inner')
# inner join 会丢失数据，导致 avg_stocks_per_day 不准确
raw_avg_stocks_per_day = int(factor_df.groupby('date').size().mean())

# 正确写法（在所有 merge 前快照）
factor_df = _convert_date_column(factor_df, '因子')
# 在加载额外因子文件前，快照原始数据范围
raw_period_start = str(factor_df['date'].min())
raw_period_end = str(factor_df['date'].max())
raw_total_days = factor_df['date'].nunique()
raw_avg_stocks_per_day = round(factor_df.groupby('date').size().mean(), 1)

# 后续 merge 不影响 raw_metadata
if additional_factor_files:
    factor_df = pd.merge(factor_df, additional_df, ...)
```

**精度处理：**
- 使用 `round(x, 1)` 保留一位小数（如 155.7）
- 禁止 `int()` 直接截断（如 int(155.7) = 155，不是四舍五入）
- avg_stocks_per_day 是浮点数，不应强制截断为整数

**原因：**
1. raw_metadata 应反映原始缓存数据，而非 merge/dropna 后的数据
2. inner join 会丢失数据，导致 avg_stocks_per_day 不准确
3. int() 直接截断精度丢失，round() 四舍五入更合理

**参考：** data_loader.py 第120-127行（在 merge 前快照原始数据）

### DataFrame 函数修改规范（重要）

**函数不应修改传入的 DataFrame（遵循最小惊讶原则）：**

```python
# 错误写法（直接修改传入对象）
def _convert_date_column(df: pd.DataFrame) -> pd.DataFrame:
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    return df  # 同时修改了原始 df，违反最小惊讶原则

# 正确写法（使用 .copy() 创建副本）
def _convert_date_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()  # 创建副本，确保不修改原始对象
    df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
    return df  # 返回新对象，原始对象不变
```

**原则：**
1. 函数有返回值时，不应同时修改传入对象
2. 用户期望函数返回新对象，而非修改传入对象
3. 使用 `.copy()` 创建副本，确保不修改原始对象
4. 若必须修改传入对象，应在函数名和文档中明确声明（如 `_modify_xxx_inplace`）

**原因：**
1. DataFrame 是可变对象，直接修改会影响调用方
2. 调用方可能后续使用原始 DataFrame，修改导致逻辑错误
3. 违反最小惊讶原则，用户未预期传入对象被修改

**参考：** data_loader.py 第263行（df.copy() 创建副本）

### reset_index 规范（重要）

**过滤/筛选操作后必须 reset_index：**

```python
# 错误写法（reset_index 缺失）
factor_df = factor_df.dropna(subset=dropna_cols)  # dropna 后索引断裂
factor_df = factor_df[factor_df['date'].isin(common_dates)]  # isin 筛选后索引断裂
# 后续操作可能因索引断裂导致错误

# 正确写法（统一 reset_index）
factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
factor_df = factor_df[factor_df['date'].isin(common_dates)].reset_index(drop=True)
# 所有过滤操作后统一重置索引，行为一致
```

**原因：**
1. dropna/isin 等过滤操作会导致索引断裂（不连续）
2. 索引断裂可能导致下游操作错误（如 iloc/loc 混用）
3. 与前面 dropna 后的 reset_index 行为一致，保持统一性
4. `reset_index(drop=True)` 避免保留旧索引列

**适用场景：**
- dropna 过滤缺失值后
- isin 筛选日期/股票后
- merge 合并数据后（可选，视场景）
- 任何导致行数减少的操作后

**参考：** data_loader.py 第225-226行（日期对齐后 reset_index）

### 未使用 import 规范（重要）

**禁止导入未使用的模块：**

```python
# 错误写法（未使用 import）
import numpy as np  # 代码中无 np 引用
import pandas as pd
...

# 正确写法（只导入需要的模块）
import gzip
import json
import pandas as pd
from pathlib import Path
```

**原因：**
1. 未使用 import 增加代码噪音，降低可读性
2. 可能误导读者认为模块被使用
3. 部分工具（如 lint）会检测未使用 import 并报错
4. 保持代码整洁，只导入真正需要的模块

**参考：** data_loader.py 第17-22行（import 列表）

### 列表浅拷贝规范（重要）

**列表赋值必须使用显式拷贝（防止引用污染）：**

```python
# 错误写法（浅拷贝，引用同一对象）
default_dropna_cols = factor_cols  # 浅拷贝，引用调用方传入的列表
all_factor_cols = factor_cols      # 同上，注释说"独立变量"但实际是引用
# 调用方修改 factor_cols 会影响函数内的 default_dropna_cols

# 正确写法（显式拷贝，创建新列表对象）
default_dropna_cols = list(factor_cols)  # 真正的副本，不污染调用方
all_factor_cols = list(factor_cols)      # 真正的副本，不污染调用方
# 调用方修改 factor_cols 不影响函数内的副本
```

**原因：**
1. Python 列表赋值是浅拷贝（引用传递），而非深拷贝
2. `a = b` 让 a 和 b 指向同一对象，修改一个会影响另一个
3. 函数参数是调用方传入的列表，函数内赋值仍引用原列表
4. 注释说"独立变量"但实际是引用，语义矛盾，误导维护者
5. 使用 `list()` 创建新列表对象，确保真正的独立

**适用场景：**
- 函数参数是可变对象（List、Dict、Set）
- 需要在函数内修改副本而不影响调用方
- 注释说"独立变量"或"副本"时必须使用显式拷贝

**参考：** data_loader.py 第132-135行（list() 创建副本）

### 列验证规范（重要）

**在 merge/select 前验证列是否存在：**

```python
# 错误写法（列未验证，pandas 抛出不友好的 KeyError）
factor_df = pd.merge(factor_df, additional_df[['date', 'asset', col_name]], ...)
# 若 col_name 不存在，pandas KeyError: "['col_name'] not in index"

# 正确写法（在 merge 前验证，提供友好错误信息）
if col_name in additional_df.columns:
    additional_df[col_name] = pd.to_numeric(additional_df[col_name], errors='coerce')
else:
    available_cols = sorted([c for c in additional_df.columns if c not in ['date', 'asset']])
    raise KeyError(
        f"额外因子文件 '{file_path}' 缺少指定列: '{col_name}'\n"
        f"可用列: {available_cols}"
    )

factor_df = pd.merge(factor_df, additional_df[['date', 'asset', col_name]], ...)
```

**原因：**
1. pandas 原生 KeyError 信息不友好，不显示可用列
2. 用户无法快速定位问题，排查困难
3. 提供可用列列表，帮助用户修正参数
4. 验证时机应在 merge/select 前而非操作后

**适用场景：**
- merge 合并 DataFrame 前
- select 选择列前（`df[['col1', 'col2']]`）
- dropna 指定列前

**参考：** data_loader.py 第148-155行（列验证 + 友好错误信息）

### 列表去重保序规范（重要）

**合并列表时必须去重并保持顺序：**

```python
# 错误写法（不去重，可能产生重复列）
select_cols = ['date', 'asset'] + factor_cols
# 若 factor_cols=['date', 'rsi_6']，select_cols=['date', 'asset', 'date', 'rsi_6']
# factor_df 出现重复 'date' 列，下游操作异常

# 正确写法（去重保序）
select_cols = list(dict.fromkeys(['date', 'asset'] + factor_cols))
# 结果：['date', 'asset', 'rsi_6']（去重后顺序正确）
```

**原理：**
- `dict.fromkeys(iterable)` 创建字典，键来自 iterable，值全为 None
- 字典键天然去重，保留首次出现顺序（Python 3.7+）
- `list(dict.fromkeys(...))` 转为列表，实现去重保序

**原因：**
1. 用户可能传入 `factor_cols=['date', 'rsi_6']`（包含基础列）
2. 直接合并会导致重复列名，DataFrame 操作异常
3. `set()` 去重但丢失顺序，`dict.fromkeys()` 去重保序
4. 保持顺序确保 'date'、'asset' 在前，方便调试

**适用场景：**
- 合并列表时去重（如 `base_cols + user_cols`）
- DataFrame 列选择前去重（防止重复列）
- 需要保持首次出现顺序的场景

**参考：** data_loader.py 第204行（dict.fromkeys 去重保序）

### dropna_cols 参数验证规范（重要）

**使用 dropna 前验证列是否存在：**

```python
# 错误写法（列未验证，pandas 抛出不友好的 KeyError）
factor_df = factor_df.dropna(subset=dropna_cols)
# 若 dropna_cols=['invalid_col']，pandas KeyError: "['invalid_col'] not in index"

# 正确写法（在 dropna 前验证，提供友好错误信息）
missing_dropna_cols = [col for col in dropna_cols if col not in factor_df.columns]
if missing_dropna_cols:
    available_cols = sorted([c for c in factor_df.columns if c not in ['date', 'asset']])
    raise KeyError(
        f"dropna_cols 包含不存在的列: {missing_dropna_cols}\n"
        f"可用列: {available_cols}"
    )

factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
```

**原因：**
1. 用户显式传入 dropna_cols 参数时，可能包含不存在的列名
2. pandas 原生 KeyError 信息不友好，不显示可用列
3. 提供可用列列表，帮助用户快速修正参数
4. 与其他参数验证风格一致（如 factor_cols、return_col）

**适用场景：**
- 用户显式传入 dropna_cols 参数
- dropna 操作前验证列是否存在
- 任何使用 subset 参数的 pandas 操作前

**参考：** data_loader.py 第218-226行（dropna 前验证列）

### 基础列验证时机规范（重要）

**基础列验证应在数据加载后立即执行：**

```python
# 错误写法（验证时机晚，错误难以定位）
factor_df = pd.DataFrame(factor_data['data'])
print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
# 若 asset 列不存在，KeyError 抛出在打印语句，难以定位问题根源
# 用户可能以为是打印语句错误，而非数据缺少 asset 列

# 正确写法（加载后立即验证，提供明确错误信息）
factor_df = pd.DataFrame(factor_data['data'])

# 基础列验证（加载后立即验证）
for col in ['date', 'asset']:
    if col not in factor_df.columns:
        raise KeyError(f"因子数据缺少必需列: '{col}'，无法继续处理")

print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
```

**原因：**
1. 基础列（date, asset）是所有后续操作的依赖，必须首先验证
2. 验证时机应在数据加载后立即执行，而非打印语句前
3. 打印语句中访问列时，若列不存在会抛出 KeyError，错误位置难以定位
4. 提前验证提供明确错误信息，帮助用户定位问题根源

**验证顺序：**
1. 加载数据 → 立即验证基础列 → 打印统计信息
2. 日期转换 → 验证因子列/收益列 → 其他操作
3. 基础列验证必须最先执行，其他验证可按逻辑顺序执行

**参考：** data_loader.py 第100-106行（加载后立即验证基础列）

### JSON键验证规范（重要）

**JSON数据加载后应立即验证关键键存在：**

```python
# 错误写法（键未验证，抛出难以定位的 KeyError）
factor_data = json.load(f)
factor_df = pd.DataFrame(factor_data['data'])
# 若 factor_data 缺少 'data' 键，pd.DataFrame 抛出 KeyError: "data"
# 错误位置在 DataFrame 构造，而非 JSON 加载，难以定位

# 正确写法（加载后立即验证键）
factor_data = json.load(f)

# 验证 JSON 结构键存在
if 'data' not in factor_data:
    raise KeyError(
        f"因子缓存文件 '{factor_cache_path}' 缺少 'data' 键\n"
        f"JSON 结构: {list(factor_data.keys())}"
    )

factor_df = pd.DataFrame(factor_data['data'])
```

**原因：**
1. JSON 文件可能缺少 'data' 键（格式错误、损坏、版本不匹配）
2. pd.DataFrame(factor_data['data']) 若键不存在，抛出 KeyError
3. 错误位置在 DataFrame 构造，而非 JSON 加载，难以定位问题根源
4. 提前验证键存在，提供明确错误信息（显示 JSON 结构）

**验证顺序：**
1. 加载 JSON → 立即验证关键键（'data'）→ 构建 DataFrame
2. 验证基础列 → 打印统计信息 → 其他操作

**参考：** data_loader.py 第100-105行（JSON 键验证）

### 除零防护规范（重要）

**除法运算前应检查除数是否为零：**

```python
# 错误写法（除零风险）
rows_before = len(factor_df)
rows_lost = rows_before - rows_after
pct = rows_lost / rows_before * 100  # 若 rows_before == 0，抛出 ZeroDivisionError

# 正确写法（检查除数）
rows_before = len(factor_df)
rows_lost = rows_before - rows_after

if rows_lost > 0:
    if rows_before > 0:
        pct = rows_lost / rows_before * 100
        print(f"丢失 {rows_lost} 行，{pct:.1f}%")
    else:
        print(f"丢失 {rows_lost} 行，原始数据为空")
```

**原因：**
1. rows_before 可能为 0（数据为空、merge 后清空）
2. 直接除法 rows_lost / rows_before 会抛出 ZeroDivisionError
3. 分支检查 rows_before > 0 防止除零错误
4. 特殊情况（rows_before == 0）提供友好提示

**适用场景：**
- 任何除法运算（计算百分比、比例）
- 计算统计指标（IC、相关性）
- 数据丢失率计算

**参考：** data_loader.py 第199-204行（除零防护）

---

## 日志规范

**遵循 PROJECT.md 项目级日志规范（第380-500行）。**

### 核心要点

| 规范内容 | PROJECT.md 定义位置 |
|---------|---------------------|
| 日志框架 | Python 标准库 `logging` 模块（第384-392行） |
| 日志级别 | DEBUG/INFO/WARNING/ERROR/CRITICAL（第423-438行） |
| 日志路径 | 脚本当前目录下 `logs/` 子目录（第441-460行） |
| 文件命名 | `<脚本名>_YYYY-MM-DD.log`（第473-492行） |
|| 日志格式 | `%(asctime)s | %(levelname)-8s | %(name)s | %(message)s`（第494-500行） |
|| 公共模块日志传递 | PROJECT.md 第783-857行（重要） |

### 公共模块日志传递规范（重要）

**核心原则：公共模块不独立创建 logger，由调用方传入。**

遵循 PROJECT.md 第783-857行规范：
- 公共函数签名：`def public_function(..., logger=None)`
- 调用方传入：`load_data_from_cache(..., logger=logger)`
- 日志定位：调用方的日志文件

**logger 参数命名规范（防止遮蔽）：**

| 问题 | 错误做法 | 正确做法 |
|------|---------|---------|
| 参数遮蔽模块级变量 | `def func(logger=None)` + 模块级 `logger = get_logger()` | 使用已导入的 get_logger，不重复导入 |
| fallback 重复导入 | `from .logger_config import get_logger` 在函数内再次导入 | 删除函数内导入，使用模块级已导入的 get_logger |

**正确示例：**

```python
# 模块级导入（一次导入）
from .logger_config import get_logger
logger = get_logger(__name__)  # 模块级 logger（给 main 使用）

def public_function(..., logger=None):
    """
    参数:
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
    """
    # fallback 使用已导入的 get_logger（不重复导入）
    if logger is None:
        logger = get_logger(__name__)
    
    logger.info("操作完成")
```

**禁止行为：**

```
❌ 函数内重复导入 get_logger（浪费资源）
❌ 参数名与模块级变量同名且无明确 fallback 逻辑（遮蔽混淆）
❌ 公共模块独立创建 logger（无法定位调用方）
```

### 迁移计划

**Phase 1**：已完成（PROJECT.md 规范定义）
**Phase 2**：替换 `factor_ic/common/*.py` 中所有 print → logging（待执行）
**Phase 3**：替换 `factor_ic/*.py` 中所有 print → logging（待执行）

**详细规范请参考：** `PROJECT.md` 第380-500行（日志规范章节）

---

## ic_result_builder.py — IC结果构建公共模块

**文件路径：** `factor_ic/common/ic_result_builder.py`

### 核心函数

```python
def build_ic_result(
    ic_result: Dict,
    raw_metadata: Dict,
    factor_name: str,
    return_period: str = '1d',
    data_source: str = '',
    factor_col: str = '',
    update_mode: str = 'full'
) -> Dict:
    """
    构建 IC 分析完整结果（符合 MODULE.md 输出结构统一性规范）
    
    参数:
        ic_result: calculate_ic_with_direction_verification 返回值
        raw_metadata: load_factor_return_data 返回的原始数据元信息
        factor_name: 因子名称（如 'rsi_1d', 'volume_ratio_1d')
    
    返回:
        符合 MODULE.md 规范的完整 JSON 结构字典
    """
```

### 功能列表

| 功能 | 描述 | 输出字段 |
|------|------|----------|
| 结果组装 | 将 ic_calculator 返回值转换为完整结构 | 所有顶层字段 |
| rolling_ic_mean | 20日窗口滚动均值（min_periods=10） | `rolling_ic_mean` |
| sample_stats | 样本统计 + 口径范围说明 | `sample_stats` |
| summary | 综合评价 + 推荐 | `summary` |
| factor_stats | 因子基本信息 | `factor_stats` |
| error_result | 错误情况默认结构 | 所有字段（默认值） |

### 使用示例

```python
from factor_ic.common.data_loader import load_factor_return_data
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification
from factor_ic.common.ic_result_builder import build_ic_result, save_ic_result

# 加载数据
factor_df, return_df, raw_metadata = load_factor_return_data(
    factor_cols=['rsi_6']
)

# 计算 IC
ic_result = calculate_ic_with_direction_verification(
    factor_df=factor_df,
    return_df=return_df,
    factor_col='rsi_6',
    return_col='forward_return'
)

# 构建完整结果
result = build_ic_result(
    ic_result=ic_result,
    raw_metadata=raw_metadata,
    factor_name='rsi_1d',
    data_source='cache/factor_data/factor_data.json.gz',
    factor_col='rsi_6'
)

# 保存
save_ic_result(result)
```

### 辅助函数

| 函数 | 用途 |
|------|------|
| `build_sample_stats()` | 单独构建样本统计字段 |
| `build_rolling_ic_mean()` | 单独计算滚动均值 |
| `build_error_result()` | 构建错误默认结构 |
| `get_ic_output_path()` | 获取输出文件路径 |
| `save_ic_result()` | 保存结果到 JSON |

### 规范要点

1. 所有字段符合 MODULE.md "输出结构统一性规范"
2. rolling_ic_mean 前 9 个为 None（min_periods=10）
3. sample_stats.avg_stocks_period 包含口径说明
4. summary 基于五维度判断生成推荐

### 模块内部函数复用规范（重要）

**DRY原则：模块内公共函数必须复用，禁止重复实现相同逻辑**

| 场景 | 正确做法 | 错误做法 |
|------|---------|---------|
| build_ic_result 需要滚动均值 | 调用 `build_rolling_ic_mean(ic_series)` | 直接实现 `ic_series.rolling(window=20, min_periods=10).mean()` |

**原因：**
1. 避免后续修改窗口参数时需改多处
2. 公共函数已有完整注释和测试
3. 语义清晰，易于维护

### 后缀处理规范（重要）

**只处理后缀，避免误处理字符串中间的匹配**

| 场景 | 正确做法 | 错误做法 |
|------|---------|---------|
| 移除因子名 `_1d` 后缀 | `name[:-3] if name.endswith('_1d') else name` | `name.replace('_1d', '')` |

**示例对比：**
```python
# 错误写法（误处理中间的 _1d）
factor_name = 'my_1d_factor_1d'
clean = factor_name.replace('_1d', '')  # → 'my_factor'（错误！）

# 正确写法（只处理后缀）
clean = factor_name[:-3] if factor_name.endswith('_1d') else factor_name  # → 'my_1d_factor'
```

---

## incremental_engine.py — 增量更新引擎

**文件路径：** `factor_ic/common/incremental_engine.py`

### 核心函数

```python
def incremental_update_ic(
    output_path: Path,
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    raw_metadata: Dict,
    factor_name: str,
    factor_col: str,
    return_col: str = 'forward_return',
    min_stocks: int = 10
) -> Dict:
    """
    执行增量更新
    
    流程:
        1. 读取现有缓存
        2. 确定缺失日期
        3. 计算缺失日期 IC（复用 calculate_single_day_ic）
        4. 合并数据（去重，新值覆盖旧值）
        5. 重算统计指标（复用 calculate_ic_statistics）
        6. 构建输出并保存
    """
```

### 功能列表

| 功能 | 描述 | 规范要点 |
|------|------|----------|
| 缓存读取 | 读取现有 IC 结果 | FileNotFoundError → 全量，JSONDecodeError → 严重错误 |
| 缺失日期筛选 | 因子日期 - 缓存日期 | 全量加载 + 日期差集 |
| 逐日 IC 计算 | 复用 calculate_single_day_ic | 确保算法一致性 |
| 数据合并 | 字典去重（新值优先） | overlap_dates 记录覆盖事件 |
| 统计重算 | 复用 calculate_ic_statistics | 不手工构建统计字段 |
| 模式判断 | should_use_incremental() | force_full → 全量 |

### 辅助函数

| 函数 | 用途 |
|------|------|
| `get_cache_latest_date()` | 获取缓存最新日期 |
| `read_existing_cache()` | 读取现有缓存数据 |
| `calculate_missing_dates_ic()` | 计算缺失日期 IC |
| `merge_ic_data()` | 合并 IC 数据（去重） |
| `recalculate_statistics()` | 重算统计指标 |
| `should_use_incremental()` | 判断是否使用增量模式 |

### 使用示例

```python
from factor_ic.common.incremental_engine import incremental_update_ic, should_use_incremental
from factor_ic.common.data_loader import load_factor_return_data

# 加载全量数据
factor_df, return_df, raw_metadata = load_factor_return_data(
    factor_cols=['rsi_6']
)

# 判断模式
output_path = get_ic_output_path('rsi', '1d')
use_incremental = should_use_incremental(output_path, factor_df, force_full=False)

if use_incremental:
    # 增量更新
    result = incremental_update_ic(
        output_path=output_path,
        factor_df_full=factor_df,
        return_df_full=return_df,
        raw_metadata=raw_metadata,
        factor_name='rsi_1d',
        factor_col='rsi_6'
    )
else:
    # 全量计算（使用 calculate_ic_with_direction_verification）
    ...
```

### 规范要点

**保存逻辑必须统一使用 save_ic_result：**

```python
# 错误写法（增量模式裸写，全量模式不一致）
# 全量模式
save_ic_result(result, output_path)  # 封装调用

# 增量模式（错误）
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(convert_to_native_types(result), f, ensure_ascii=False, indent=2)  # 裸写

# 正确写法（全量/增量统一使用 save_ic_result）
save_ic_result(result, output_path)  # 全量模式
save_ic_result(result, output_path)  # 增量模式
```

**原因：**
1. 全量/增量模式应使用统一的保存逻辑，便于维护
2. `save_ic_result` 内置异常处理（PermissionError、OSError），磁盘满/权限错误时有友好日志
3. 裸写 `json.dump` 无异常处理，磁盘满/权限错误时直接抛出未捕获异常
4. 封装函数便于统一修改保存逻辑（如添加校验、更改格式）

**适用场景：**
- 全量模式保存
- 增量模式保存
- 任何 IC 结果保存场景

**参考：** factor_ic_runner.py 第244-245行、ic_result_builder.py 第422-433行（2026-05-22 更新）

---

### incremental_engine 规范要点（旧版保留）

1. 增量模式必须复用 calculate_single_day_ic（算法一致性）
2. 合并时使用字典去重（新值覆盖旧值）
3. overlap_dates 必须记录（事件追踪）
4. rolling_ic_mean 需对齐回 all_dates（None 填充）

---

## factor_ic_runner.py — 主入口模板

**文件路径：** `factor_ic/common/factor_ic_runner.py`

### 核心函数

```python
def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    return_period: str = '1d',
    return_col: str = 'forward_return_1d',
    factor_cols: Optional[List[str]] = None,
    min_stocks: int = 10,
    force_full: bool = False,
    output_path: Optional[Path] = None,
    custom_factor_calculation: Optional[Callable] = None
) -> Dict:
    """
    因子 IC 分析统一主入口
    
    流程:
        1. 判断模式（全量/增量/跳过）
        2. 加载数据
        3. 执行计算
        4. 构建输出
        5. 保存结果
    """
```

### 功能列表

| 功能 | 描述 | 规范要点 |
|------|------|----------|
| 模式判断 | should_use_incremental() | force_full → 全量 |
| 数据加载 | load_factor_return_data() | 支持额外因子文件 |
| 全量计算 | calculate_ic_with_direction_verification() | 五维度判断 |
| 增量更新 | incremental_update_ic() | 补充五维度判断 |
| 结果构建 | build_ic_result() | 符合输出结构规范 |
| 结果保存 | save_ic_result() | 自动路径生成 |

### 快捷函数

| 函数 | 用途 | 适用场景 |
|------|------|----------|
| `run_simple_factor_ic()` | 简单因子（直接用缓存列） | RSI、量比 |
| `run_complex_factor_ic()` | 复杂因子（需预处理） | KDJ、布林带 |

### 快捷函数语义清晰规范（重要）

**函数参数必须与函数名语义一致：**

```python
# 错误设计（语义矛盾）
def run_complex_factor_ic(
    factor_name: str,
    factor_col: str,
    factor_cols: List[str],
    custom_factor_calculation: Optional[Callable] = None  # Optional 与 "complex" 语义矛盾
):
    # 若传 None，等价于 run_simple_factor_ic，功能重叠
    # 调用者可能误用：run_complex_factor_ic('rsi', 'rsi_6', ['rsi_6'])  # 静默跳过自定义计算

# 正确设计（语义清晰）
def run_complex_factor_ic(
    factor_name: str,
    factor_col: str,
    factor_cols: List[str],
    custom_factor_calculation: Callable  # 必须参数，与 "complex" 语义一致
):
    # 若无需自定义计算，调用者应使用 run_simple_factor_ic
    # 强制参数防止误用：run_complex_factor_ic('rsi', 'rsi_6', ['rsi_6'])  # TypeError
```

**原因：**
1. 函数名定义了用途：`simple` = 无需自定义计算，`complex` = 必须有自定义计算
2. Optional 参数破坏语义，导致两个函数功能重叠
3. 调用者可能误用，传 None 导致复杂因子计算被静默跳过
4. 必须参数强制调用者选择正确的函数，防止误用

**适用场景：**
- 任何快捷函数设计，参数必须与函数名语义一致
- 函数名暗示"必须"时，参数不应 Optional
- 功能重叠时，应明确区分（必须参数 vs 可选参数）

**参考：** factor_ic_runner.py 第353行（2026-05-22 更新）

### 使用示例

```python
from factor_ic.common.factor_ic_runner import run_simple_factor_ic, run_complex_factor_ic

# 简单因子（直接用缓存列）
result = run_simple_factor_ic('rsi', 'rsi_6')
result = run_simple_factor_ic('volume_ratio', 'volume_ratio_5')

# 复杂因子（需自定义计算）
def calculate_kdj_j(factor_df):
    # KDJ 计算逻辑
    low_min = factor_df.groupby('asset')['low'].transform(lambda x: x.rolling(9, min_periods=9).min())
    high_max = factor_df.groupby('asset')['high'].transform(lambda x: x.rolling(9, min_periods=9).max())
    rsv = (factor_df['close'] - low_min) / (high_max - low_min) * 100
    k = rsv.ewm(alpha=1/3, adjust=False).mean()
    d = k.ewm(alpha=1/3, adjust=False).mean()
    j = 3 * k - 2 * d
    factor_df['kdj_j'] = j
    return factor_df

result = run_complex_factor_ic(
    factor_name='kdj_j',
    factor_col='kdj_j',
    factor_cols=['close', 'high', 'low'],
    custom_factor_calculation=calculate_kdj_j
)
```

### 规范要点（重要）

**日志访问字段必须使用 .get() 防止 KeyError：**

```python
# 错误写法（直接访问字段，KeyError 会被 except 误报）
try:
    ic_result = calculate_ic_with_direction_verification(...)
    _logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")  # 若 ic_mean 缺失，KeyError
except Exception as e:
    _logger.error(f"IC 计算失败: {e}")  # 实际是日志格式化失败，误报为 IC 计算失败

# 正确写法（使用 .get() 防止 KeyError）
try:
    ic_result = calculate_ic_with_direction_verification(...)
    _logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")  # 安全访问
except Exception as e:
    _logger.error(f"IC 计算失败: {e}")  # 真正的 IC 计算错误
```

**嵌套字段需双重保护：**

```python
# 错误写法（嵌套访问无保护）
_logger.info(f"t 统计量: {ic_result['statistical_significance']['t_stat']:.2f}")
# 若 statistical_significance 缺失，KeyError；若 t_stat 缺失，KeyError

# 正确写法（双重 .get() 保护）
t_stat = ic_result.get('statistical_significance', {}).get('t_stat', 0.0)
_logger.info(f"t 统计量: {t_stat:.2f}")
```

**保持全量/增量模式一致性：**

```python
# 增量模式（正确示例）
_logger.info(
    f"五维度补充完成: 有效天数={len(valid_ic)}, "
    f"IC均值={stats_result.get('ic_mean', 0.0):.4f}, "
    f"ICIR={stats_result.get('icir', 0.0):.2f}"
)

# 全量模式（应与增量模式一致）
_logger.info(f"IC 均值: {ic_result.get('ic_mean', 0.0):.4f}")
_logger.info(f"ICIR: {ic_result.get('icir', 0.0):.2f}")
```

**原因：**
1. try 块内的 KeyError 会被 except Exception 捕获，掩盖真实原因
2. 日志格式化失败会被误报为"IC 计算失败"，用户难以定位问题
3. 嵌套字段访问需双重保护，防止任一层级缺失导致 KeyError
4. 全量/增量模式应使用一致的访问方式，便于维护

**参考：** factor_ic_runner.py 第277-283行（2026-05-22 更新）

---

### 新增因子开发流程

```
1. 确定因子类型：
   - 简单因子（缓存列直接可用）→ 使用 run_simple_factor_ic()
   - 复杂因子（需预处理）→ 使用 run_complex_factor_ic()

2. 实现因子计算逻辑（复杂因子）：
   - 定义 custom_factor_calculation 函数
   - 输入: factor_df（包含原始列）
   - 输出: factor_df（添加 factor_col 列）

3. 调用主入口：
   result = run_xxx_factor_ic(...)

4. 检查结果：
   - update_mode: full/incremental/skip/failed
   - ic_mean, icir, p_value
   - 五维度判断结论

总代码量：~50-200行（仅因子计算逻辑）
```

### CLI 支持

```bash
# 简单因子
python -m factor_ic.common.factor_ic_runner --factor rsi --col rsi_6

# 强制全量
python -m factor_ic.common.factor_ic_runner --factor volume_ratio --col volume_ratio_5 --force-full
```