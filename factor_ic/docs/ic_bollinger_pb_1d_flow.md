# Bollinger_PB_1D IC 计算流程文档

> 生成时间: 2026-05-20 02:20 (北京时间)
> 实测数据时间: 2026-05-20 02:20 (北京时间)
> 审阅版本: v3.9
> 更新内容:
>   ...
>   44. 修复布林带 %B 计算隐式 NaN 传播：显式检查 pd.isna(diff) + 补充 MODULE.md 布林带 %B 计算显式处理 NaN 规范
>   43. 修复异常链风格不一致：ValueError 裸 raise 补充注释说明 + 补充 MODULE.md 异常链保留规范
>   42. 修复静默吞掉异常问题：区分 FileNotFoundError（可恢复）和 JSONDecodeError/PermissionError（严重）+ 补充 MODULE.md 异常处理必须区分严重错误和可恢复错误规范
>   41. 修复增量路径空列表 IndexError：检查 all_dates 长度 + 补充 MODULE.md 列表索引访问前必须检查长度规范
>   40. 修复接口设计不一致：删除 load_data_from_cache 的 factor_col 参数（布林带因子固定使用 close）+ 补充 MODULE.md 布林带因子固定使用 close 列规范
>   39. 修复 load_data_from_cache 设计缺陷：强制加载和过滤 'close' 列（布林带依赖）+ 补充 MODULE.md 布林带因子必须加载 close 列规范
>   38. 修复增量路径合并时过滤 None 导致丢失跳过日期：保留所有日期（包括 None IC 值）+ 补充 MODULE.md 增量路径 None 值保留规范
>   37. 修复增量路径因子值有效性检查缺失：添加 bollinger_pb_1d NaN 诊断 + 补充 MODULE.md 增量路径因子值有效性检查规范
>   36. 修复 calculate_daily_ic_series required_fields 校验列表缺失 p_value/p_value_display + 补充 MODULE.md 函数返回值契约校验规范
>   35. 修复增量路径 factor_stats 字段缺失：添加 factor_stats 到 merged_data + 补充 MODULE.md 增量路径返回结构一致性规范
>   34. 修复增量路径 period 字段语义错误：直接使用 raw_metadata（与全量路径一致）+ 补充 MODULE.md 增量路径 period 字段规范
>   33. 修复增量路径 rolling_ic_mean 长度不一致：基于 all_dates 计算而非 valid_dates 子集 + 补充 MODULE.md 增量路径 rolling_ic_mean 规范
>   32. 修复 %B 计算浮点数除零判断：从 diff==0 改为 np.abs(diff)<1e-10（精度容差）+ 补充 MODULE.md 浮点数等值比较规范
>   31. 修复布林带标准差 ddof 参数：从默认 ddof=1（样本标准差）改为 ddof=0（总体标准差）+ 补充 MODULE.md 布林带标准差 ddof 参数规范
>   29. 修复增量路径 ic_metrics 缺少 p_value/p_value_display 字段（KeyError）+ 补充 MODULE.md ic_metrics 字段规范
>   29. 修复增量路径 factor_direction/economic_significance 字段名不一致（KeyError）+ 补充 MODULE.md factor_direction/economic_significance/statistical_significance 字段规范
>   28. 修复增量路径 ic_metrics 缺少 p_value/p_value_display 字段（KeyError）+ 补充 MODULE.md ic_metrics 字段规范
>   27. 修复增量路径 rolling_ic_mean NaN 处理缺失：显式转换 NaN → None（与全量路径一致）+ 补充 MODULE.md 两条路径一致性要求
>   26. 修复缩进错误：'icir' 和 'sample_stats' 字段缩进不一致（IndentationError）+ 补充 MODULE.md 字典结构缩进规范
>   25. 删除冗余 max 比较逻辑：total_days 直接使用 raw_metadata，遵循 MODULE.md total_days 使用规范
>   3. 修复 total_days 计算错误：使用 raw_metadata['total_days'] 而非 len(dates)
>   4. 添加 avg_stocks_period 字段：明确口径范围
>   5. 添加 DEFAULT_MIN_STOCKS 常量：统一管理参数
>   6. 遵循 PROJECT.md 参数传递规范：min_stocks 通过函数签名传递
>   7. 遵循 PROJECT.md 异常处理类型保留规范：数据验证错误保留原始类型
>   8. 遵循 PROJECT.md 输出字段口径规范：avg_stocks_period 子字段描述口径范围
>   9. 遵循 PROJECT.md avg_stocks_per_day 计算口径规范：基于 dropna 后数据
>   10. 添加增量模式：_incremental_update() 和 _full_recalculate() 分离
>   11. 添加命令行参数：--force-full 强制全量计算
>   12. 添加日期类型转换：pd.to_datetime + errors='coerce' + NaT 检查
>   13. 添加输入验证：列存在检查 + 可用列列表（遵循 PROJECT.md 输入验证规范）
>   14. 添加函数返回值契约校验：校验 calculate_ic_with_direction_verification 返回字段（遵循 MODULE.md 函数返回值契约规范）
>   15. 添加 ic_series 显式排序：ic_series.sort_index() + 防御性校验（遵循 MODULE.md ic_series 排序规范）
>   16. 添加 NaN → None 处理：rolling_ic_mean 在数据生成阶段处理 NaN（遵循 MODULE.md NaN 处理规范）
>   17. 删除死代码 merged_df：遵循 MODULE.md 数据传递规范，不在调用 calculate_ic_with_direction_verification 前合并数据
>   18. 删除死代码 calculate_bollinger_bands 和 calculate_percent_b：遵循 MODULE.md 设计演进清理规范，向量化版本替代后删除单股票版本
>   19. 修复布林带 min_periods 参数：从 min_periods=1 改为 min_periods=n，遵循布林带标准定义（MODULE.md 技术指标参数规范）
>   20. 修复 _incremental_update 缺失 rolling_ic_mean 字段：在 merged_data 中添加该字段，遵循 MODULE.md 增量更新返回数据规范
>   21. 修复完成信息字段错误：从 total_days 改为 valid_days，遵循 MODULE.md 打印信息规范
>   22. 补充 MODULE.md ic_series.index 类型规范（字符串而非 datetime），明确两条路径一致性保障
>   23. 修复 %B 计算 NaN 处理缺失：添加 diff.isna() 判断，遵循 MODULE.md %B 计算规范
>   24. 删除冗余参数 period_start/period_end：直接使用 raw_metadata，遵循 MODULE.md 函数参数设计规范 + period.start/end 语义规范

---

## 概述

本文档描述布林带%B 因子 IC 计算的完整流程，遵循 PROJECT.md 规范。

**更新模式（遵循 PROJECT.md 增量模式规范）：**

```
三种更新模式:
- skip: 数据完备，直接返回缓存
- incremental: 只计算缺失日期 IC，合并后重算统计指标
- full: 全量重算所有日期 IC

模式判断: check_data_completeness('bollinger_pb_1d')
强制全量: --force-full 参数
```

---

## 因子定义

```
布林带%B（Bollinger Band %B）因子定义：
- Middle Band = SMA(Close, N)
- Upper Band = Middle Band + K × StdDev(Close, N)
- Lower Band = Middle Band - K × StdDev(Close, N)
- %B = (Close - Lower Band) / (Upper Band - Lower Band)

参数：
- N = 20（移动平均周期）
- K = 2.0（标准差倍数）

边界处理：
- %B > 1：价格突破上轨，超买信号
- %B = 1：价格在上轨
- 0 < %B < 1：价格在布林带内
- %B = 0：价格在下轨
- %B < 0：价格跌破下轨，超卖信号

因子逻辑：
- %B > 1：超买，预期回落
- %B < 0：超卖，预期反弹
- 使用反向排名（%B值高排名低）
```

---

## 核心函数

### 1. load_data_from_cache()

**功能：** 从缓存加载因子数据和收益数据

**输入：**
- `factor_col: str = 'close'` — 因子列名
- `return_col: str = 'forward_return_1d'` — 收益列名

**输出：**
- `(factor_df, return_df, raw_metadata)`
- `raw_metadata` 包含 `period_start`, `period_end`, `total_days`

**异常处理（遵循 PROJECT.md 异常处理类型保留规范）：**

```
except FileNotFoundError → RuntimeError（基础设施错误，包装）
except JSONDecodeError → RuntimeError（基础设施错误，包装）
except KeyError → RuntimeError（基础设施错误，包装）
except ValueError → raise（数据验证错误，直接传递）
except Exception → RuntimeError（未预期异常，包装）
```

---

### 2. calculate_bollinger_pb_1d_factor()

**功能：** 计算布林带%B 因子

**输入：**
- `factor_df: DataFrame` — 包含 date, asset, close 的数据
- `n: int = 20` — 移动平均周期
- `k: float = 2.0` — 标准差倍数

**输出：**
- `(factor_df, stats)`
- `factor_df` 添加 `bollinger_pb_1d` 列
- `stats` 包含因子计算统计信息

---

### 3. calculate_daily_ic_series()

**功能：** 计算每日 IC 时间序列

**输入：**
- `factor_df: DataFrame` — 因子数据（已过滤缺失值）
- `return_df: DataFrame` — 收益数据（已过滤缺失值）
- `raw_metadata: dict` — 原始数据元信息
- `min_stocks: int` — 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
- `period_start: str` — 数据起始日期
- `period_end: str` — 数据结束日期

---

### 4. _full_recalculate()

**功能：** 全量重新计算所有日期 IC

**输入：**
- `output_file: Path` — 输出文件路径
- `n: int = 20` — 布林带移动平均周期
- `k: float = 2.0` — 布林带标准差倍数
- `min_stocks: int = DEFAULT_MIN_STOCKS` — 最小股票数阈值

**输出：**
- IC 数据字典
- `update_mode: 'full'`

---

### 5. _incremental_update()

**功能：** 只计算缺失日期 IC，合并后重算统计指标

**输入：**
- `missing_dates: list` — 缺失日期列表
- `output_file: Path` — 输出文件路径
- `n: int = 20` — 布林带移动平均周期
- `k: float = 2.0` — 布林带标准差倍数
- `min_stocks: int = DEFAULT_MIN_STOCKS` — 最小股票数阈值

**输出：**
- IC 数据字典
- `update_mode: 'incremental'`
- `incremental_days: int` — 新增日期数

**流程（遵循 PROJECT.md 增量计算规范）：**

```
[1/4] 读取现有缓存
[2/4] 加载全量数据，计算因子，筛选缺失日期
[3/4] 计算新日期 IC（复用 calculate_single_day_ic）
[4/4] 合并数据，去重，重算统计指标（复用 calculate_ic_statistics）
```

---

### 6. generate_bollinger_pb_1d_ic_data()

**功能：** 主入口函数

**输入：**
- `output_file: Path | str | None = None` — 输出文件路径
- `force_full: bool = False` — 强制全量计算
- `n: int = 20` — 布林带移动平均周期
- `k: float = 2.0` — 布林带标准差倍数
- `min_stocks: int = DEFAULT_MIN_STOCKS` — 最小股票数阈值

**输出：**
- IC 数据字典

**模式判断流程（遵循 PROJECT.md 增量模式规范）：**

```
if force_full → _full_recalculate()
else:
    mode = check_data_completeness('bollinger_pb_1d')
    if mode == 'skip' → 返回缓存
    if mode == 'incremental' → _incremental_update()
    if mode == 'full' → _full_recalculate()
```

---

## 字段定义

### sample_stats 字段

| 字段 | 类型 | 语义 | 计算方式 |
|------|------|------|---------|
| `total_days` | int | 原始缓存日期数（含无效日期） | `raw_metadata['total_days']` |
| `valid_days` | int | 有效 IC 天数 | `len(dates)` |
| `avg_stocks_per_day` | int | 平均每日股票数 | `int(factor_df.groupby('date').size().mean())` |
| `avg_stocks_period` | dict | 口径范围 | `{start, end, description}` |

**口径差异说明（遵循 PROJECT.md avg_stocks_per_day 计算口径规范）：**

```
| 字段 | 数据基准 | 说明 |
|------|---------|------|
| total_days | dropna 前（原始缓存） | 因子缓存的日期数，包含 NaN 日期 |
| avg_stocks_per_day | dropna 后（有效数据） | 因子值非 NaN 的日期数，不含 NaN 日期 |
| valid_days | IC 计算后（有效 IC） | 股票数 >= min_stocks 的日期数 |
```

---

## 参数传递规范

遵循 PROJECT.md 参数传递规范：

```python
# 默认参数常量
DEFAULT_MIN_STOCKS = 10

# 函数签名
def generate_bollinger_pb_1d_ic_data(
    min_stocks: int = DEFAULT_MIN_STOCKS  # 通过函数签名传递
) -> dict:
    # 内部调用也传递该参数
    calculate_daily_ic_series(..., min_stocks=min_stocks)
```

---

## 异常处理规范

遵循 PROJECT.md 异常处理类型保留规范：

```python
try:
    factor_df, return_df, raw_metadata = load_data_from_cache()
    
    if factor_df['asset'].nunique() < min_stocks:
        raise ValueError(f"股票数量不足: ...")
        
except FileNotFoundError as e:
    # 基础设施错误：包装为 RuntimeError
    raise RuntimeError(f"缓存文件不存在...") from e
    
except ValueError as e:
    # 数据验证错误：直接传递，保留原始类型
    raise  # 不包装
```

---

## 输出文件

**路径：** `factor_ic/result/ic_bollinger_pb_1d_analysis_result.json`

**格式：** JSON，utf-8 编码，indent=2

---

## 运行示例

### 增量模式（默认）

```bash
cd /home/admin/projects/factor_ic_analyzer
python factor_ic/ic_bollinger_pb_1d.py
```

**输出：**

```
============================================================
布林带%B_1D IC 计算器（增量模式）
============================================================
[增量模式] 缺失 1 天数据，执行增量更新

[1/4] 读取现有缓存...
  - 现有数据: 513 天

[2/4] 加载缺失日期数据（1 天）...
  ...

[3/4] 计算新日期 IC...
  - 计算完成: 1 天，其中 0 天有效 IC

[4/4] 合并数据并重新计算统计指标...
  - 合并后总计: 513 天（去重后）

============================================================
增量更新完成！新增 1 天，总计 513 天
============================================================
```

### 全量模式（强制）

```bash
python factor_ic/ic_bollinger_pb_1d.py --force-full
```

**输出：**

```
============================================================
布林带%B_1D IC 计算器（全量模式）
============================================================
参数: N=20, K=2.0

[1/3] 从缓存加载因子和收益数据...

[数据加载] 从缓存读取数据...
  - 因子数据: 1482714 行, 2999 只股票
  - 收益数据: 1482714 行, 2999 只股票
  - 原始数据范围: 2024-02-06 ~ 2026-05-15, 545 个交易日

数据统计:
  - 原始日期范围: 2024-02-06 ~ 2026-05-15
  - 原始交易日数: 545
  - 股票数量: 2999

[2/3] 计算布林带%B 因子...
  ...

  有效记录数: 1,425,736（min_periods=n，前19交易日NaN）

  因子统计:
    均值:   0.5131
    标准差: 0.3250

  超买(%B>1):  100,310 (7.04%)
  超卖(%B<0):  55,577 (3.90%)
  布林带内:   1,269,849 (89.07%)

[3/3] 计算每日 IC...
  - IC 均值: -0.0408
  - ICIR: 0.29
  - 正比例: 38.6%
  - t 统计量: -7.09 显著

============================================================
完成！共计算 495 天有效 IC 数据（原始数据 545 天）
============================================================
```

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-19 | 初始版本，参照 ic_rsi_1d.py v1.52 规范创建 |
| v1.1 | 2026-05-19 | 添加增量模式，命令行参数 --force-full |
| v1.2 | 2026-05-19 | 添加日期类型转换（遵循 PROJECT.md 日期类型一致性规范），添加输入验证（遵循 PROJECT.md 输入验证规范） |
| v1.3 | 2026-05-19 | 添加函数返回值契约校验（遵循 MODULE.md 规范），添加 ic_series 显式排序（遵循 MODULE.md 规范），添加 NaN → None 处理（遵循 MODULE.md 规范） |
| v1.4 | 2026-05-19 | 删除死代码 merged_df，补充 MODULE.md 数据传递规范 |
| v1.5 | 2026-05-19 | 删除死代码 calculate_bollinger_bands 和 calculate_percent_b，补充 MODULE.md 设计演进清理规范 |
| v1.6 | 2026-05-19 | 修复布林带 min_periods 参数（min_periods=1 → min_periods=n），补充 MODULE.md 技术指标参数规范 |
| v1.7 | 2026-05-19 | 修复 _incremental_update 缺失 rolling_ic_mean 字段 + 修复完成信息字段错误（total_days → valid_days），补充 MODULE.md 增量更新返回数据规范 |
| v1.8 | 2026-05-19 | 补充 MODULE.md ic_series.index 类型规范（字符串而非 datetime），明确两条路径一致性保障 |
| v1.9 | 2026-05-19 | 修复 %B 计算 NaN 处理缺失 + 补充 MODULE.md %B 计算规范 |
| v2.0 | 2026-05-19 | 删除冗余参数 period_start/period_end + 补充 MODULE.md 函数参数设计规范 + period.start/end 语义规范 |
| v2.1 | 2026-05-19 | 删除冗余 max 比较逻辑：total_days 直接使用 raw_metadata + 补充 MODULE.md total_days 使用规范 |
| v2.2 | 2026-05-19 | 修复缩进错误（IndentationError）：'icir' 和 'sample_stats' 字段缩进不一致 + 补充 MODULE.md 字典结构缩进规范 |
| v2.3 | 2026-05-19 | 修复增量路径 rolling_ic_mean NaN 处理缺失（显式转换 NaN → None）+ 补充 MODULE.md 两条路径一致性要求 |
| v2.4 | 2026-05-19 | 修复增量路径 ic_metrics 缺少 p_value/p_value_display 字段（KeyError）+ 补充 MODULE.md ic_metrics 字段规范 |
| v3.9 | 2026-05-20 | 修复布林带 %B 计算隐式 NaN 传播（显式检查 pd.isna）+ 补充 MODULE.md 布林带 %B 计算显式处理 NaN 规范 |
| v3.8 | 2026-05-20 | 修复异常链风格不一致（ValueError 裸 raise 补充注释）+ 补充 MODULE.md 异常链保留规范 |

---

*最后更新: 2026-05-20 02:20:00 (北京时间)*