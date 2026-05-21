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