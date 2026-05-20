# RSI_1D IC 计算流程文档

> 生成时间: 2026-05-20 16:30 (北京时间)
> 审阅版本: v1.53
> 实测数据时间: 2026-05-20
> 更新内容: 
>   1. 增量计算单日 IC 改用 calculate_single_day_ic 核心函数（遵循 PROJECT.md 规范）
>   2. 移除直接调用 scipy.stats.spearmanr，确保增量与全量计算算法一致
>   3. 增量合并添加去重验证，防止日期重叠污染数据
>   4. 使用字典去重，新值优先覆盖旧值
>   5. [v1.36] 修复增量模式 total_days 语义与全量不一致问题
>   6. [v1.36] 增量模式 total_days 改用 max(raw_metadata['total_days'], factor_df_full['date'].nunique())
>   7. [v1.36] 保包含无效日期，语义与全量模式一致，total_days >= valid_days
>   8. [v1.37] 明确 avg_stocks_per_day 增量模式语义限制
>   9. [v1.37] avg_stocks_per_day/n_assets 只反映当前因子缓存范围，不含历史缓存中已不在当前数据源的日期
>   10. [v1.37] 用户可通过 total_days 判断数据范围，理解统计口径
>   11. [v1.38] 新增增量更新诊断规范：区分"数据源无数据"和"缓存缺失"
>   12. [v1.38] 缺失日期不在缓存范围时打印警告和诊断信息
>   13. [v1.38] 所有缺失日期均不在缓存范围时建议执行全量重算
>   14. [v1.39] 新增增量更新事件记录规范：重叠覆盖事件必须记录到返回数据和 JSON 文件
>   15. [v1.39] 新增 incremental_events 字段：overwritten_dates, overwritten_count, description
>   16. [v1.39] 上游调用方可感知重叠覆盖事件，下次可复现问题
>   17. [v1.40] 新增增量计算进度显示规范：完整展示总计算天数、有效天数、无效天数
>   18. [v1.40] 修复信息展示不完整问题：打印"100 天计算，80 天有效，20 天跳过"
>   19. [v1.40] 用户可判断数据源覆盖范围和数据质量
>   20. [v1.41] 新增异常处理规范：必须保留原始异常类型和堆栈信息
>   21. [v1.41] _full_recalculate 异常处理改为分层捕获：FileNotFoundError/JSONDecodeError/KeyError/ValueError
>   22. [v1.41] 使用 raise ... from e 语法保留堆栈信息，用户可追溯问题来源
>   23. [v1.42] 新增参数传递规范：关键参数必须通过函数签名传递，禁止多处硬编码
>   24. [v1.42] 添加 DEFAULT_MIN_STOCKS 常量，统一管理 min_stocks 阈值
>   25. [v1.42] 所有函数签名接受 min_stocks 参数，消除硬编码分散问题
>   26. [v1.42] 用户可配置参数，无需修改多处代码
>   27. [v1.43] 新增返回值标记规范：三种模式返回值必须标记 update_mode 字段
>   28. [v1.43] skip 模式返回值添加 update_mode='skip' 标记
>   29. [v1.43] skip-fallback 场景返回值添加 fallback_event 字段记录原计划与实际执行模式
>   30. [v1.43] 调用方可通过返回值区分"缓存读取"和"意外触发全量计算"，避免长时间计算时毫不知情
>   31. [v1.43] fallback_event 字段包含：original_mode, actual_mode, trigger_reason, error_message, description
>   32. [v1.44] 新增错误信息格式规范：枚举类错误必须包含合法值列表
>   33. [v1.44] 未知模式 RuntimeError 补充合法值列表 ['skip', 'incremental', 'full']
>   34. [v1.44] 参考 KeyError 处理格式（第120-125行可用列列表），统一错误信息风格
>   35. [v1.45] 新增 convert_to_native_types 行为验证规范：必须有单元测试验证 NaN → None → null
>   36. [v1.45] 新增 test_convert_types.py 测试文件，验证 JSON 序列化行为一致性
>   37. [v1.45] 引用 PROJECT.md NaN 处理规范，明确 convert_to_native_types 是兜底保障
>   38. [v1.46] 新增函数签名变更同步规范：返回值变更时必须同步更新类型注解和 docstring
>   39. [v1.46] load_data_from_cache 返回值从2个变成3个，类型注解同步更新为 Tuple[..., ..., dict]
>   40. [v1.46] docstring 返回值描述同步更新，明确三个返回值及其语义
>   41. [v1.47] 新增等价性验证三重保障机制规范：代码架构 + 单元测试 + 文档规范
>   42. [v1.47] 新增 TestAlgorithmEquivalence.test_full_incremental_equivalence_multi_day：验证多日期场景等价性
>   43. [v1.47] 补充 Step 4.5 强制保障机制章节：明确方向处理无反转逻辑
>   44. [v1.48] 新增日期字符串比较规范：比较操作前必须添加格式断言（遵循 PROJECT.md 规范）
>   45. [v1.48] 增量模式 period 比较前添加 YYYY-MM-DD 格式验证，防御未来其他代码路径引入未转换日期
>   46. [v1.49] 新增字典构建规范：字段应集中定义在构建阶段，避免分散赋值
>   47. [v1.49] 删除 update_mode 重复赋值，确保字段定义位置唯一
>   48. [v1.50] 新增输出字段口径规范：统计字段必须明确口径范围
>   49. [v1.50] avg_stocks_per_day 字段添加 avg_stocks_period 子字段描述口径范围
>   50. [v1.50] 删除误导性注释，通过结构化字段让用户感知统计口径
>   51. [v1.51] 修复 ValueError 异常处理：删除 RuntimeError 包装，直接 raise（遵循 PROJECT.md 异常处理类型保留规范）
>   52. [v1.51] 数据验证错误保留原始异常类型，调用方可用 except ValueError 捕获
>   53. [v1.51] 补充 PROJECT.md 「异常处理类型保留规范」章节：区分基础设施错误和数据验证错误
>   54. [v1.52] 补充 PROJECT.md 「avg_stocks_per_day 计算口径规范」章节
>   55. [v1.52] 明确 avg_stocks_per_day 基于 dropna 后数据，与 total_days 口径不同
>   56. [v1.52] 解释均值偏高原因：NaN 日期被排除，这些日期通常股票数较少
>   57. [v1.52] 提供口径一致性检查表，确保用户理解统计含义
>   58. [v1.53] 修复 ic_metrics 字段缺失问题：添加 p_value 和 p_value_display（遵循 MODULE.md 输出结构规范）
>   59. [v1.53] 导入 calculate_ic_statistics 移至顶部（遵循 PEP8 导入规范）
>   60. [v1.53] required_fields 校验添加 p_value、p_value_display
>   61. [v1.53] 全量/增量路径 ic_metrics 结构一致，跨脚本验证通过（RSI/布林带/KDJ 三脚本 5 字段一致）
>

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    ic_rsi_1d.py 主流程                           │
├─────────────────────────────────────────────────────────────────┤
│  入口: generate_rsi_ic_data()                                    │
│    ↓                                                             │
│  [1] 参数类型转换 → output_file 统一转为 Path                      │
│    ↓                                                             │
│  [2] 数据完整性检查 → 决定是否需要计算                             │
│    ↓                                                             │
│  [3] 从缓存加载因子数据和收益数据                                   │
│    ↓                                                             │
│  [4] 调用 calculate_ic_with_direction_verification()             │
│      - 先用原始 RSI 值计算正向 IC（Spearman）                      │
│      - 根据 IC 均值和 p 值判断因子方向                             │
│      - 输出 factor_direction 和 direction_confidence             │
│    ↓                                                             │
│  [5] 保存结果到 JSON 文件                                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 参数类型转换

```
generate_rsi_ic_data(output_file) 入口
    │
    ├── output_file is None?
    │       │
    │       ├── Yes → output_file = get_ic_output_path('rsi_1d')  # 返回 Path
    │       │
    │       └── No → output_file = Path(output_file)  # str → Path
    │
    └── output_file 现为 Path 对象，后续可安全使用 .parent.mkdir()
```

**规范依据**：PROJECT.md 参数类型约定

---

### Step 2: 增量判断（数据完整性检查）

```
check_data_completeness('rsi_1d')
    │
    ├── mode='skip'（缓存已最新）
    │       │
    │       ├── 读取缓存成功 ──→ return 缓存数据
    │       │
    │       └── 读取缓存失败 ──→ print warning ──→ fallback 到全量计算
    │           │                   （无 return，代码继续向下执行）
    │           │
    │           └── 这是合理的容错设计，不是 bug
    │               必须有注释说明 fallback 行为
    │
    ├── mode='incremental'（有缺失日期）
    │       │
    │       └── 调用 _incremental_update()
    │               │
    │               ├── 合并日期-IC值配对
    │               │   paired = zip(existing) + zip(new)
    │               │
    │               ├── 按日期升序排序（关键步骤）
    │               │   paired.sort(key=lambda x: x[0])
    │               │
    │               ├── 解构为 dates 和 ic_values
    │               │   all_dates = [p[0] for p in paired]
    │               │   all_ic_values = [p[1] for p in paired]
    │               │
    │               ├── 保留位置信息（过滤 None）
    │               │   valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
    │               │   valid_dates = [all_dates[i] for i in valid_indices]  # 按日期升序
    │               │   valid_ic = [all_ic_values[i] for i in valid_indices]
    │               │
    │               ├── 创建 ic_series（遵循输入约束）
    │               │   ic_series = pd.Series(valid_ic, index=valid_dates)
    │               │   # 约束：valid_dates 必须按日期升序排列
    │               │   # （calculate_ic_statistics 输入约束：索引顺序决定输出顺序）
    │               │
    │               ├── 计算统计指标
    │               │   result = calculate_ic_statistics(ic_series)
    │               │   # 输出：rolling_ic_mean 长度 = len(ic_series)
    │               │
    │               ├── 防御性验证（v1.19 新增）
    │               │   if len(rolling_ic_mean_raw) != len(valid_ic):
    │               │       raise RuntimeError("长度不匹配，可能索引错位")
    │               │
    │               └── 将 rolling_ic_mean 映射回 all_dates
    │                   │   valid_indices_set = set(valid_indices)  # O(1) 查找
    │                   │
    │                   │   for i in range(len(all_dates)):
    │                   │       if i in valid_indices_set:
    │                   │           aligned.append(rolling_ic_mean_raw[idx])
    │                   │       else:
    │                   │           aligned.append(None)
    │                   │
    │                   （None 日期填 None，与 dates/ic_values 长度一致）
    │
    └── mode='full'（缓存不存在或 force_full=True）
            │
            └── 进入全量计算流程
```

**三种模式完整行为流程（遵循 PROJECT.md 异常处理规范）**：

| 模式 | 条件 | 正常行为 | 异常行为 |
|------|------|---------|---------|
| `skip` | 缓存已最新 | 返回现有缓存数据 | fallback 到全量计算 |
| `incremental` | 有缺失日期 | 追加新日期 IC | fallback 到全量计算 |
| `full` | 缓存不存在 | 全量计算 | 抛出异常（数据源不可用） |

---

### Step 2.1: 返回值标记规范（v1.43 新增）

**遵循 PROJECT.md 返回值标记规范：三种模式返回值必须标记 update_mode 字段，调用方可感知实际执行的模式。**

```
generate_rsi_ic_data() 返回值结构
    │
    ├── mode='skip'（缓存已最新，读取成功）
    │       │
    │       └── 返回值包含：
    │           {
    │               ...原有缓存数据...,
    │               'update_mode': 'skip'  // 标记：从缓存读取
    │           }
    │           // 调用方判断：result['update_mode'] == 'skip' → 无计算开销
    │
    ├── mode='skip' + fallback（缓存读取失败，触发全量计算）
    │       │
    │       └── 返回值包含：
    │           {
    │               ...全量计算数据...,
    │               'update_mode': 'full',  // 标记：实际执行了全量计算
    │               'fallback_event': {
    │                   'original_mode': 'skip',           // 原本期望的模式
    │                   'actual_mode': 'full',             // 实际执行的模式
    │                   'trigger_reason': 'cache_read_failed', // 触发原因
    │                   'error_message': str(e),           // 原始错误信息
    │                   'description': f"缓存读取失败，触发全量计算。原始错误: {e}"
    │               }
    │           }
    │           // 调用方判断：result['update_mode'] == 'full' && 'fallback_event' in result → 意外触发全量计算
    │           // 重要场景：全量计算耗时很长，调用方需要感知，避免毫不知情
    │
    ├── mode='incremental'（有缺失日期）
    │       │
    │       └── 返回值包含：
    │           {
    │               ...合并后数据...,
    │               'update_mode': 'incremental',  // 标记：增量更新
    │               'incremental_events': {
    │                   'overwritten_dates': [...],
    │                   'overwritten_count': N,
    │                   'description': "..."
    │               }
    │           }
    │           // 调用方判断：result['update_mode'] == 'incremental' → 增量计算
    │
    └── mode='full'（缓存不存在或 force_full=True）
            │
            └── 返回值包含：
                {
                    ...全量计算数据...,
                    'update_mode': 'full'  // 标记：全量计算（正常路径）
                }
                // 调用方判断：result['update_mode'] == 'full' && 'fallback_event' not in result → 正常全量计算
```

**返回值标记设计原则（遵循 PROJECT.md 规范）**：

| 场景 | update_mode | 附加字段 | 调用方判断逻辑 |
|------|------------|---------|---------------|
| 正常 skip | `'skip'` | 无 | `update_mode == 'skip'` → 从缓存读取 |
| skip-fallback | `'full'` | `fallback_event` | `update_mode == 'full' && 'fallback_event' in result` → 意外触发全量 |
| 正常 incremental | `'incremental'` | `incremental_events` | `update_mode == 'incremental'` → 增量更新 |
| 正常 full | `'full'` | 无 | `update_mode == 'full' && 'fallback_event' not in result` → 正常全量 |

**为何必须标记返回值（设计动机）**：

```
问题背景：
1. mode='skip' 时读取缓存失败会 fallback 到全量计算
2. fallback 后返回值与正常全量计算返回值结构相同
3. 调用方拿到的是"正常返回值"，无法区分来源
4. 若全量计算耗时很长（如计算1000天IC），调用方毫不知情

解决方案：
1. 返回值必须标记 update_mode 字段
2. fallback 场景必须添加 fallback_event 字段记录原计划与实际执行模式
3. 调用方可通过返回值感知实际发生了什么，避免长时间计算时毫不知情

设计一致性：
- 增量模式已有 update_mode='incremental' + incremental_events 设计
- skip-fallback 场景采用相同设计模式（update_mode + fallback_event）
- 确保所有重要事件都能通过返回值传递给调用方
```

**调用方典型判断代码示例**：

```python
result = generate_rsi_ic_data()

if result['update_mode'] == 'skip':
    print("从缓存读取，无计算开销")
elif result['update_mode'] == 'incremental':
    print(f"增量更新，新增 {result['incremental_days']} 天")
elif result['update_mode'] == 'full':
    if 'fallback_event' in result:
        event = result['fallback_event']
        print(f"意外触发全量计算！原计划: {event['original_mode']}, 实际: {event['actual_mode']}")
        print(f"触发原因: {event['trigger_reason']}")
        print(f"错误信息: {event['error_message']}")
        # 重要：调用方需要记录此事件，因为全量计算耗时可能很长
    else:
        print("正常全量计算")
```

---

### Step 3: 数据加载

```
load_data_from_cache()
    │
    ├── 加载因子缓存: cache/factor_data/factor_data.json.gz
    │   │
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, rsi_6]
    │   │
    │   ├── [计算原始数据范围]（v1.28 新增，dropna 前）
    │   │   │
    │   │   ├── raw_period_start = factor_df['date'].min()
    │   │   ├── raw_period_end = factor_df['date'].max()
    │   │   ├── raw_total_days = factor_df['date'].nunique()
    │   │   │
    │   │   └── 语义定义（遵循 PROJECT.md 输出字段语义规范）：
    │   │       - 基于原始缓存数据（dropna 前），而非过滤后数据
    │   │       - 用于 period 和 sample_stats.total_days 计算
    │   │
    │   └── 过滤缺失值（dropna）
    │       - 某日期所有股票因子值为 NaN → 该日期被过滤
    │
    ├── 加载收益缓存: cache/factor_data/return_data.json.gz
    │   │
    │   ├── 解压 gzip → JSON
    │   ├── 转为 DataFrame
    │   ├── 提取列: [date, asset, forward_return_1d]
    │   ├── 重命名: forward_return_1d → forward_return
    │   └── 过滤缺失值
    │
    ├── [日期类型转换]（v1.27 新增异常处理）
    │   │
    │   ├── 使用 pd.to_datetime(..., errors='coerce') 处理异常格式
    │   │   - 无效格式（如 "N/A"、空字符串）转为 NaT，不抛 ParserError
    │   │
    │   ├── 检查 NaT 数量
    │   │   - nat_count > 0 → 抛 ValueError，包含无效样本
    │   │   - 错误信息格式：
    │   │       "因子数据中存在 X 个无效日期格式"
    │   │       "无效日期示例: ['N/A', '', 'Invalid', ...]"
    │   │       "请检查缓存数据源是否包含脏数据"
    │   │
    │   └── 转换为字符串 "YYYY-MM-DD"
    │       - 确保 isin 操作类型匹配
    │
    └── 返回 (factor_df, return_df, raw_metadata)
        - factor_df, return_df: 过滤后的数据
        - raw_metadata: {period_start, period_end, total_days}（原始数据范围）
```

**数据源定义规范（遵循 PROJECT.md）：**

`period` 和 `total_days` 必须基于**原始缓存数据**（dropna 前），而非过滤后的数据。

**为何必须使用原始数据：**

```
load_data_from_cache 中的 dropna 操作可能过滤掉某些日期的全部股票：
1. 某日期所有股票因子值都是 NaN（停牌、数据缺失）
2. dropna 后该日期被完全移除
3. factor_df['date'].min()/max()/nunique() 计算的是过滤后的范围
4. 与语义定义冲突："原始缓存覆盖范围" ≠ "过滤后的数据范围"

正确做法：
- 在 dropna 之前，先计算 raw_period_start, raw_period_end, raw_total_days
- 返回过滤后的数据 + raw_metadata
- calculate_daily_ic_series 使用 raw_metadata 计算 period/total_days
```

**日期转换异常处理规范（遵循 PROJECT.md）：**

| 异常格式 | `pd.to_datetime` 默认行为 | `errors='coerce'` 行为 |
|---------|--------------------------|----------------------|
| `"N/A"` | 抛出 `ParserError` | 转为 NaT |
| 空字符串 `""` | 抛出 `ParserError` | 转为 NaT |
| `"Invalid"` | 抛出 `ParserError` | 转为 NaT |
| `"2024-13-01"` | 抛出 `ParserError` | 转为 NaT |

**为何必须检查 NaT：**

1. `errors='coerce'` 将无效日期转为 NaT，不抛异常
2. `NaT.strftime('%Y-%m-%d')` 产生字符串 `"NaT"`（不是 None）
3. `"NaT"` 字符串会污染后续计算（isin、日期排序等）
4. 必须在转换后立即检查 NaT 数量，发现脏数据时及时报错

**输出示例**：

```
factor_df:
| date       | asset   | rsi_6 |
|------------|---------|-------|
| 2026-05-01 | 000001  | 25.5  |
| 2026-05-01 | 000002  | 80.2  |
| ...        | ...     | ...   |

return_df:
| date       | asset   | forward_return |
|------------|---------|----------------|
| 2026-05-01 | 000001  | 0.05           |
| 2026-05-01 | 000002  | -0.02          |
| ...        | ...     | ...            |
```

---

### Step 4: IC 计算（核心 - 方向验证流程）

这是 `calculate_ic_with_direction_verification()` 模块的核心逻辑：

**遵循 PROJECT.md 规范：因子方向必须根据实际 IC 测试结果确定，不可预设。**

```
calculate_ic_with_direction_verification(factor_df, return_df)
    │
    ├── [验证] 检查必需列是否存在
    │
    ├── [合并] 按键合并
    │   │
    │   └── merged = pd.merge(factor_df, return_df, on=[date, asset])
    │
    ├── [遍历] 按日期分组，逐日计算正向 IC
    │   │
    │   └─────────────────────────────────────────────┐
    │   │                                             │
    │   │  for each date:                              │
    │   │      │                                       │
    │   │      ├── 股票数 < 10? → 跳过该日              │
    │   │      │                                       │
    │   │      ├── 因子值全部相同? → IC = 0             │
    │   │      │                                       │
    │   │      ├── 收益值全部相同? → IC = 0             │
    │   │      │                                       │
    │   │      └── 计算该日正向 IC:                     │
    │   │          │                                   │
    │   │          └── IC = corr(rsi_6, forward_return, method='spearman')
    │   │              # 使用原始 RSI 值，不反转        │
    │   │                                              │
    │   └─────────────────────────────────────────────┘
    │
    ├── [统计量] Newey-West 调整的 t 统计量和 p 值
    │   │
    │   ├── ic_mean = ic_series.mean()
    │   ├── ic_std = ic_series.std()
    │   ├── icir = |ic_mean| / ic_std  # 使用绝对值（PROJECT.md 规范）
    │   ├── t_stat, p_value, nw_lag = newey_west_t_stat(ic_series)  # 自动选择lag
    │   └── positive_ratio = IC > 0 的天数占比
    │
    ├── [五维度判断] 独立输出，不合并
    │   │
    │   ┌─────────────────────────────────────────────────────────────┐
    │   │ 五维度判断（PROJECT.md 规范 - 独立输出）:                      │
    │   │                                                           │
    │   │ 维度1: 统计显著性                                          │
    │   │   p_value < 0.05 → is_significant: true                  │
    │   │   （详见 PROJECT.md "统计显著性判断简化"章节）              │
    │   │   输出: nw_lag（实际使用的滞后阶数）                         │
    │   │                                                           │
    │   │ 维度2: 因子方向（仅符号判断，不含阈值）                       │
    │   │   ic_mean < -1e-6 → negative（反向因子）                   │
    │   │   ic_mean > 1e-6  → positive（正向因子）                   │
    │   │   ic_mean ≈ 0     → zero（方向不明）                        │
    │   │   注意: 方向判断仅描述符号，不代表有效性                     │
    │   │                                                           │
    │   │ 维度3: 经济显著性                                          │
    │   │   |ic_mean| >= 0.05 → strong                              │
    │   │   |ic_mean| >= 0.03 → weak                                │
    │   │   |ic_mean| < 0.03  → none                                │
    │   │                                                           │
    │   │ 维度4: ICIR稳定性                                          │
    │   │   ICIR >= 2.0  → excellent                                │
    │   │   ICIR >= 1.0  → good                                     │
    │   │   ICIR >= 0.5  → usable                                   │
    │   │   ICIR < 0.5   → none                                     │
    │   │                                                           │
    │   │ 维度5: IC分布一致性                                        │
    │   │   positive_ratio 与 ic_mean_sign 匹配判断                 │
    │   │                                                           │
    │   │   ⚠️ 核心原则：规则按序执行（if-elif链），匹配后直接返回      │
    │   │                                                           │
    │   │   判断规则（含优先级标注）：                                  │
    │   │   优先级1（最高）: ic_mean_sign = 'zero' → balanced        │
    │   │   优先级2: 正向因子 positive_ratio >= 50% → consistent    │
    │   │   优先级2: 反向因子 positive_ratio <= 50% → consistent    │
    │   │   优先级3: positive_ratio ∈ [49%, 51%] → balanced         │
    │   │            （闭区间，代码用<=0.011应对浮点精度）         │
    │   │   优先级4: 其他情况 → contradictory                        │
    │   │                                                           │
    │   │   边界示例（边界对称设计）：                                │
    │   │   正向因子 49% → balanced（优先级3）                       │
    │   │   正向因子 50% → consistent（优先级2）                     │
    │   │   反向因子 50% → consistent（优先级2）                     │
    │   │   反向因子 51% → balanced（优先级3）                       │
    │   │   （详见 PROJECT.md "IC分布一致性判断边界规范"）            │
    │   │                                                           │
    │   │   输出: is_consistent, consistency_type                   │
    │   │                                                           │
    │   │ ⚠️ 五个维度独立输出，不合并为 valid/invalid                 │
    │   └─────────────────────────────────────────────────────────────┘
    │
    └── 返回结果字典
```

---

### Step 4.1: NaN 处理规范（v1.29 新增）

**遵循 PROJECT.md NaN 处理规范：NaN → None 转换应在数据生成阶段完成。**

```
calculate_daily_ic_series(factor_df, return_df, raw_metadata)
    │
    ├── [计算 IC] 调用 calculate_ic_with_direction_verification
    │
    ├── [转换日期和 IC 值]
    │   │
    │   ├── dates = [str(d) for d in ic_series.index]
    │   ├── ic_values = [round(v, 6) for v in ic_series.values]
    │
    ├── [计算 rolling_ic_mean]
    │   │
    │   ├── rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    │   │   - 前 9 天不满 min_periods=10 → 返回 NaN
    │   │
    │   ├── [NaN 处理]（遵循 PROJECT.md NaN 处理规范）
    │   │   │
    │   │   ├── 使用 pd.isna(v) 检查 NaN
    │   │   ├── NaN → None（语义转换："无有效数据"）
    │   │   │
    │   │   └── rolling_ic_mean = [
    │   │           round(v, 6) if not pd.isna(v) else None
    │   │           for v in rolling_mean.values
    │   │       ]
    │   │
    │   └── 为何必须在数据生成阶段处理：
    │       1. 语义一致性：None 表示"无有效数据"，nan 是浮点数运算结果
    │       2. 增量路径用 None 填充无效日期，全量路径用 NaN 填充不满 min_periods 的日期
    │       3. 若延迟到 convert_to_native_types 处理，语义不一致
    │       4. JSON 序列化时 None → null，标准 JSON 不支持 nan
    │
    └── [防御性校验] 确保 dates 升序排列 + 长度一致
```

---

### Step 4.2: 日期排序规范（v1.30 新增）

**遵循 PROJECT.md ic_series 排序规范：ic_series.index 必须按日期升序排列。**

```
calculate_ic_with_direction_verification(factor_df, return_df)
    │
    ├── [按日期计算 IC]
    │   │
    │   ├── for date, daily_data in merged.groupby(date_col):
    │   │       ic_list.append({'date': date, 'ic': ic_value})
    │   │
    │   ├── ic_df = pd.DataFrame(ic_list)
    │   ├── ic_series = ic_df.set_index('date')['ic']
    │   │
    │   ├── [显式排序]（遵循 PROJECT.md ic_series 排序规范）
    │   │   │
    │   │   └── ic_series = ic_series.sort_index()
    │   │
    │   └── 为何必须显式排序：
    │       1. rolling 计算按位置顺序，而非 index 值顺序
    │       2. 若 ic_series.index 乱序 → dates 与 rolling_ic_mean 对应错误
    │       3. pandas groupby 默认 sort=True，但不应依赖隐式行为
    │       4. 版本升级风险：pandas 可能改变默认行为
    │       5. 增量路径合并后可能乱序
    │
    └── [返回 ic_series]
```

**防御性校验：**

```
calculate_daily_ic_series(factor_df, return_df, raw_metadata)
    │
    ├── [长度校验]
    │   ├── len(dates) == len(ic_values)
    │   └── len(dates) == len(rolling_ic_mean)
    │
    ├── [日期顺序校验]（遵循 PROJECT.md ic_series 排序规范）
    │   │
    │   └── if dates != sorted(dates):
    │           raise RuntimeError("dates 未按升序排列")
    │
    └── 为何必须校验日期顺序：
        1. 长度一致不代表语义对应正确
        2. 若 dates 乱序，dates[i] 与 rolling_ic_mean[i] 对应错误
        3. rolling_ic_mean[i] 是位置 i 的滚动均值，应对应 dates[i]
        4. 若 dates[0]='2026-05-02', dates[1]='2026-05-01'
           → rolling_ic_mean[0] 对应 '2026-05-02'（语义错误）
```

**ic_series 排序规范要点：**

| 规范项 | 位置 | 说明 |
|-------|------|------|
| 显式排序 | ic_calculator.py | `ic_series = ic_series.sort_index()` |
| 防御性校验 | ic_rsi_1d.py | `if dates != sorted(dates): raise RuntimeError` |

---

### Step 4.3: 函数返回值契约校验（v1.31 新增）

**遵循 PROJECT.md 函数返回值契约规范：调用方必须校验返回值字段存在性。**

```
calculate_daily_ic_series(factor_df, return_df, raw_metadata)
    │
    ├── [调用函数]
    │   │
    │   └── result = calculate_ic_with_direction_verification(...)
    │
    ├── [契约校验]（遵循 PROJECT.md 函数返回值契约规范）
    │   │
    │   ├── 定义必需字段列表：
    │   │   required_fields = [
    │   │       'ic_series', 'ic_mean', 'ic_std', 'icir',
    │   │       'statistical_significance', 'factor_direction',
    │   │       'economic_significance', 'icir_stability',
    │   │       'ic_distribution_consistency', 'positive_ratio', 'summary'
    │   │   ]
    │   │
    │   ├── 检查缺失字段：
    │   │   missing_fields = [f for f in required_fields if f not in result]
    │   │
    │   └── 若缺失字段 → 抛出 RuntimeError：
    │       │
    │       └── raise RuntimeError(
    │               f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
    │               f"缺失字段: {missing_fields}\n"
    │               f"问题定位: factor_ic/common/ic_calculator.py\n"
    │               f"期望字段: {required_fields}"
    │           )
    │
    └── [安全访问]
        │
        └── ic_series = result['ic_series']  # 校验通过后安全访问
```

**为何必须校验返回值字段：**

```
1. 直接下标访问 result['field'] 会抛出 KeyError
2. KeyError 错误信息：KeyError: 'ic_mean' ← 无法判断问题模块
3. 函数返回值结构变更时，调用方静默失败
4. 校验后的 RuntimeError 包含：
   - 缺失字段列表（missing_fields）
   - 问题定位（模块路径）
   - 期望字段列表（required_fields）
```

**错误信息对比：**

| 场景 | 未校验（KeyError） | 已校验（RuntimeError） |
|-----|-------------------|----------------------|
| 错误信息 | `KeyError: 'ic_mean'` | `calculate_ic_with_direction_verification 返回值缺少必需字段\n缺失字段: ['ic_mean']\n问题定位: factor_ic/common/ic_calculator.py\n期望字段: [...]` |
| 问题定位 | 无法判断 | 明确模块路径 |
| 排查效率 | 低（需逐行检查） | 高（直接定位） |

---

### Step 4.4: 增量计算 None 处理规范（v1.32 新增）

**遵循 PROJECT.md 增量计算 None 处理规范：增量计算中 None（股票数不足）的处理必须与全量计算保持一致。**

```
_incremental_update(missing_dates, output_file)
    │
    ├── [读取现有缓存]
    │   │
    │   ├── existing_dates = existing_data.get('dates', [])
    │   ├── existing_ic_values = existing_data.get('ic_values', [])
    │   │
    │   └── 注意：来自全量计算，只有有效 IC 日期（不含 None）
    │
    ├── [计算新日期 IC]
    │   │
    │   ├── new_dates = sorted(factor_df_new['date'].unique())
    │   ├── new_ic_values = []
    │   │
    │   ├── for date in new_dates:
    │   │       ic_value = calculate_single_day_ic(...)
    │.      │       new_ic_values.append(ic_value if ic_value is not None else None)
    │   │
    │   └── 注意：new_ic_values 可能含 None（股票数不足）
    │
    ├── [合并数据]
    │   │
    │   ├── [None 过滤]（遵循 PROJECT.md 增量计算 None 处理规范）
    │   │   │
    │   │   ├── date_ic_map = {}
    │   │   ├── for date, ic in zip(existing_dates, existing_ic_values):
    │   │   │       date_ic_map[date] = ic  # 只有有效 IC 值
    │   │   │
    │   │   └── for date, ic in zip(new_dates, new_ic_values):
    │   │           if ic is not None:  # 只写入有效 IC 值（过滤股票数不足的 None）
    │   │               date_ic_map[date] = ic
    │   │
    │   └── 为何必须过滤 None：
    │       1. 全量计算：dates = ic_series.index（只有有效 IC 日期）
    │       2. 增量计算：若写入 None → date_ic_map[date] = None
    │       3. 合并后：existing_dates 不含 None，new_dates 可能含 None → 语义混乱
    │       4. 统一语义：ic_values 不存储"股票数不足"的 None
    │
    └── [解构合并数据]
        │
        ├── all_dates = sorted(date_ic_map.keys())
        └── all_ic_values = [date_ic_map[d] for d in all_dates]  # 不含 None
```

**None 语义定义：**

| None 来源 | 语义 | 是否存储 |
|----------|------|---------|
| `calculate_single_day_ic` 返回 None | 股票数 < min_stocks | **不存储**（过滤） |
| 全量计算中 ic_series.index | 只有有效 IC 日期 | 不含 None |
| 增量计算中 new_ic_values | 可能含 None | **过滤后存储** |

**为何必须统一语义：**

```
问题：date_ic_map 混合"有效 IC 值"和"股票数不足的 None"
1. existing_dates 不含 None（全量过滤）
2. new_dates 可能含 None（股票数不足）
3. 若不过滤 → date_ic_map[date] = None
4. all_dates 中某些日期 ic_values = None，但语义不明确
5. total_days - valid_days = 股票数不足跳过的日期数

修复：增量计算合并时过滤 None（只写入有效 IC 值）
结果：ic_values 不存储"股票数不足"的 None（与全量语义一致）
```

---

### Step 4.5: 全量/增量 IC 计算等价性规范（v1.33 新增）

**遵循 PROJECT.md 全量/增量 IC 计算等价性规范：全量计算与增量计算必须使用同一核心函数（calculate_single_day_ic）。**

```
全量/增量 IC 计算等价性验证
    │
    ├── [核心函数一致性]
    │   │
    │   ├── 全量计算路径
    │   │   │
    │   │   ├── calculate_ic_with_direction_verification()
    │   │   │       │
    │   │   │       ├── 内部调用 calculate_single_day_ic（第157-159行）
    │   │   │       │   for date in dates:
    │   │   │       │       ic = calculate_single_day_ic(...)
    │   │   │       │       ic_series[date] = ic
    │   │   │       │
    │   │   │       └── docstring 必须说明：
    │   │   │           "本函数内部调用 calculate_single_day_ic 计算每日 IC"
    │   │   │
    │   │   └── 增量计算路径
    │   │       │
    │   │       ├── _incremental_update()
    │   │       │       │
    │   │       │       ├── 直接调用 calculate_single_day_ic（第364-366行）
    │   │       │       │   for date in missing_dates:
    │   │       │       │       ic = calculate_single_day_ic(...)
    │   │       │       │       if ic is not None:
    │   │       │       │           date_ic_map[date] = ic
    │   │       │       │
    │   │       │       └── 注释必须说明：
    │   │       │           "使用核心函数，确保与全量计算算法一致"
    │   │       │
    │   │       └── 等价性：两者使用同一 calculate_single_day_ic
    │   │
    │   └── [边界处理一致性]
    │       │
    │       ├── 股票数 < min_stocks → calculate_single_day_ic 返回 None
    │       │   ├── 全量：跳过该日（dates 不含该日）
    │       │   └── 增量：过滤 None（date_ic_map 不含该日）
    │       │   └── 结果一致 ✓
    │       │
    │       ├── 因子值全相同 → calculate_single_day_ic 返回 0.0
    │       │   ├── 全量：ic_series[date] = 0.0
    │       │   └── 增量：date_ic_map[date] = 0.0
    │       │   └── 结果一致 ✓
    │       │
    │       └── 收益值全相同 → calculate_single_day_ic 返回 0.0
    │       │   ├── 全量：ic_series[date] = 0.0
    │       │   └── 增量：date_ic_map[date] = 0.0
    │       │   └── 结果一致 ✓
    │
    ├── [单元测试验证]
    │   │
    │   ├── test_full_incremental_same_core_function()
    │   │   │
    │   │   ├── 构造测试数据（单日，20只股票）
    │   │   ├── 全量：calculate_ic_with_direction_verification()
    │   │   ├── 增量：calculate_single_day_ic()
    │   │   ├── 验证：abs(full_ic - incremental_ic) < 1e-6 ✓
    │   │   │
    │   │   └── 结论：两者产生相同 IC 值
    │   │
    │   ├── test_boundary_handling_equivalence_insufficient_stocks()
    │   │   │
    │   │   ├── 构造测试数据（5只股票 < min_stocks=10）
    │   │   ├── 全量：calculate_ic_with_direction_verification()
    │   │   ├── 增量：calculate_single_day_ic()
    │   │   ├── 验证：incremental_ic is None ✓
    │   │   │
    │   │   └── 结论：股票数不足时两者都返回 None
    │   │
    │   └── test_boundary_handling_equivalence_constant_factor()
    │   │   │
    │   │   ├── 构造测试数据（因子值全相同）
    │   │   ├── 全量：calculate_ic_with_direction_verification()
    │   │   ├── 增量：calculate_single_day_ic()
    │   │   ├── 验证：两者都返回 0.0 ✓
    │   │   │
    │   │   └── 结论：因子值全相同时两者都返回 0.0
    │
    └── [修改代码时必须同步更新]
        │
        ├── 修改 calculate_single_day_ic 边界处理
        │   ├── 更新 calculate_ic_with_direction_verification docstring
        │   ├── 更新单元测试验证等价性
        │   └── 原因：确保等价性定义一致
        │
        ├── 修改 calculate_ic_with_direction_verification 内部逻辑
        │   ├── 更新单元测试验证
        │   ├── 原因：确保仍调用 calculate_single_day_ic
        │   │
        └── 修改增量计算路径调用方式
            ├── 更新单元测试验证
            ├── 原因：确保仍使用 calculate_single_day_ic
```

**为何必须等价：**

```
问题：全量与增量使用不同算法
1. 全量计算使用 calculate_single_day_ic（有边界处理）
2. 增量计算直接调用 scipy.stats.spearmanr（无边界处理）
3. 边界情况结果不一致：
   - 股票数不足：全量返回 None，增量可能返回 NaN
   - 因子全相同：全量返回 0.0，增量可能返回 NaN
4. 合并后数据语义混乱（同一日期全量/增量结果不一致）

修复：
1. 增量计算改用 calculate_single_day_ic（遵循 PROJECT.md 规范）
2. 添加单元测试验证等价性
3. 修改代码时同步更新 docstring 和单元测试

结果：
1. 全量/增量使用同一核心函数 ✓
2. 边界处理一致 ✓
3. 单元测试验证等价性 ✓
```

**禁止行为：**

```python
# ❌ 禁止：增量计算不使用 calculate_single_day_ic
# 增量计算路径
for date in missing_dates:
    daily_data = merged[merged['date'] == date]
    factor_values = daily_data['rsi_6'].values
    return_values = daily_data['forward_return'].values
    ic_value = scipy.stats.spearmanr(factor_values, return_values)[0]  # ❌
    # 问题：
    #   1. 全量使用 calculate_single_day_ic（有边界处理）
    #   2. 增量直接调用 spearmanr（无边界处理）
    #   3. 边界情况结果不一致

# ✓ 正确：增量计算使用 calculate_single_day_ic
for date in missing_dates:
    daily_data = merged[merged['date'] == date]
    ic_value = calculate_single_day_ic(
        daily_data,
        factor_col='rsi_6',
        return_col='forward_return',
        min_stocks=10
    )
    if ic_value is not None:
        date_ic_map[date] = ic_value
```

**注意事项：**

```
1. calculate_ic_with_direction_verification docstring 必须明确说明内部调用 calculate_single_day_ic
2. ic_rsi_1d.py 增量计算注释必须说明"使用核心函数，确保算法一致性"
3. 单元测试必须验证全量/增量对同一日期产生相同 IC 值
4. 修改核心函数时，必须检查等价性是否被破坏
```

**强制保障机制（v1.47 新增）：**

```
等价性验证三重保障机制
    │
    ├── [第一层：代码架构保障]
    │   │
    │   ├── 设计原则：全量/增量调用同一函数
    │   │   ├── 全量路径：calculate_ic_with_direction_verification 内部调用 calculate_single_day_ic
    │   │   └── 增量路径：直接调用 calculate_single_day_ic
    │   │   └── 强制保障：两者无法独立演化，修改一处必影响另一处
    │   │
    │   ├── 方向处理保障：
    │   │   ├── calculate_single_day_ic：计算原始 IC（不反转）
    │   │   ├── _assess_factor_direction：只判断方向（不修改 IC 值）
    │   │   ├── 返回的 ic_series：原始 IC 值（无负号）
    │   │   └── 结论：不存在"方向相差负号"风险
    │   │
    │   └── 代码位置验证：
    │       ├── ic_calculator.py:163-165（全量调用 calculate_single_day_ic）
    │       ├── ic_rsi_1d.py:406-408（增量调用 calculate_single_day_ic）
    │       └── 两者参数完全一致
    │
    ├── [第二层：单元测试保障]
    │   │
    │   ├── TestAlgorithmEquivalence 类（ic_rsi_1d_test_cases.py:472）
    │   │
    │   ├── test_full_incremental_same_core_function
    │   │   ├── 验证：单日期场景，两者产生相同 IC 值
    │   │   └── 断言：abs(incremental_ic - full_ic) < 1e-6
    │   │
    │   ├── test_boundary_handling_equivalence_insufficient_stocks
    │   │   ├── 验证：股票数不足边界，两者行为一致
    │   │   └── 断言：增量返回 None，全量抛出 ValueError
    │   │
    │   ├── test_boundary_handling_equivalence_constant_factor
    │   │   ├── 验证：因子值全相同边界，两者返回 0.0
    │   │   └── 断言：incremental_ic == 0.0, full_ic == 0.0
    │   │
    │   ├── test_full_incremental_equivalence_multi_day（v1.47 新增）
    │   │   ├── 验证：多日期场景，逐日 IC 值一致性
    │   │   ├── 验证：ic_mean 一致性
    │   │   ├── 验证：方向一致性（factor_direction 与 incremental_ic_mean 符号匹配）
    │   │   └── 断言：abs(full_ic - incremental_ic) < 1e-6（每个日期）
    │   │
    │   └── 运行命令：
    │       pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestAlgorithmEquivalence -v
    │
    └── [第三层：文档规范保障]
        │
        ├── Step 4.5 规范：全量/增量必须使用同一核心函数
        ├── PROJECT.md 规范：修改核心函数时必须检查等价性
        ├── docstring 要求：calculate_ic_with_direction_verification 必须说明内部调用关系
        └── 注释要求：ic_rsi_1d.py 增量计算必须说明"使用核心函数"
```

**验证等价性的方法：**

```bash
# 运行等价性单元测试
pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestAlgorithmEquivalence -v

# 预期结果：4 passed（含 test_full_incremental_equivalence_multi_day）

# 若测试失败，说明：
#   1. 全量/增量使用了不同的 IC 计算逻辑
#   2. 边界处理不一致
#   3. 方向处理存在反转逻辑
# 需立即检查 ic_calculator.py 和 ic_rsi_1d.py 的调用路径
```

---

### Step 4.6: 旧缓存兼容性处理规范（v1.34 新增）

**遵循 PROJECT.md 旧缓存兼容性处理规范：增量计算读取现有缓存时，必须兼容旧版本缓存数据。**

```
旧缓存兼容性处理流程
    │
    ├── [问题背景]
    │   │
    │   ├── v1.32 之前版本：ic_values 可能包含 None（未过滤股票数不足）
    │   ├── 增量更新读取现有缓存 → existing_ic_values 可能包含 None
    │   ├── 合并逻辑语义不一致风险：
    │   │   ├── existing 直接写入 → 旧 None 被保留
    │   │   └── new 过滤 None → 新 None 被过滤
    │   │   └── date_ic_map 混合"旧版本遗留 None"和"有效 IC 值"
    │   │
    │   └── 语义混乱：同一日期在不同版本缓存中语义不同
    │
    ├── [兼容性处理实现]
    │   │
    │   ├── _incremental_update() 第391-396行
    │   │   │
    │   │   ├── date_ic_map = {}
    │   │   │
    │   │   ├── for date, ic in zip(existing_dates, existing_ic_values):
    │   │   │       if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
    │   │   │           date_ic_map[date] = ic  # 只有有效 IC 值
    │   │   │
    │   │   ├── for date, ic in zip(new_dates, new_ic_values):
    │   │   │       if ic is not None:  # 只写入有效 IC 值
    │   │   │           date_ic_map[date] = ic
    │   │   │
    │   │   └── 结果：existing 和 new 都过滤 None（语义一致）
    │   │
    │   └── 自动清理旧版本遗留 None
    │       │
    │       ├── 旧缓存 ic_values = [0.1, None, 0.3, None, 0.5]
    │       ├── 合并时过滤 None → date_ic_map = [0.1, 0.3, 0.5]
    │       ├── 新计算值写入 → 合并后不含 None
    │       ├── 输出缓存 → ic_values = [0.1, 0.3, 0.5, ...]
    │       │
    │       └── 旧版本遗留 None 被自动清理，无需手动干预
    │
    ├── [版本兼容性说明]
    │   │
    │   ├── v1.32 之前：ic_values 可能含 None → 直接写入 date_ic_map
    │   ├── v1.32 及之后：ic_values 只含有效值 → 过滤 None 后写入
    │   ├── v1.34 及之后（当前）：existing 和 new 都过滤 None
    │   │
    │   └── 升级路径：
    │       1. v1.32 → v1.34：旧缓存自动清理
    │       2. 无需手动干预，增量更新时自动处理
    │
    └── [防御性验证]
        │
        ├── 第420-433行：验证 rolling_ic_mean_raw 与 valid_ic 长度一致
        │   │
        │   ├── if len(rolling_ic_mean_raw) != len(valid_ic):
        │   │       raise RuntimeError(...)
        │   │
        │   ├── 错误信息包含旧缓存兼容性诊断提示：
        │   │   1. calculate_ic_statistics 内部过滤（不应发生）
        │   │   2. ic_series 输入包含 NaN（调用方应过滤）
        │   │   3. 旧缓存兼容性问题（v1.32 之前 ic_values 可能含 None）
        │   │
        │   └── 诊断建议：检查 ic_series 是否含 NaN
        │
        └── 注意：calculate_ic_statistics 不会过滤 ic_series
            - 输入长度 = 输出长度（docstring 第746行明确声明）
            - 若触发异常 → 说明有其他问题（非 calculate_ic_statistics 内部过滤）
```

**为何需要兼容性处理：**

```
问题：合并逻辑语义不一致（旧版本遗留问题）
1. v1.32 规范：ic_values 不存储 None
2. 但 v1.32 之前版本可能写入 None
3. 增量更新读取旧缓存 → existing_ic_values 可能含 None
4. 若不处理：
   - 旧 None 被保留 → date_ic_map[date] = None
   - 新 None 被过滤 → 语义不一致
   - 同一日期在不同版本缓存中语义不同

修复：
1. existing 和 new 都过滤 None
2. 旧版本遗留 None 被自动清理
3. 合并后 date_ic_map 只含有效 IC 值

结果：
1. 兼容旧版本缓存 ✓
2. 自动清理遗留 None ✓
3. 语义一致性 ✓
```

**注意事项：**

```
1. 增量合并时，existing 和 new 都必须过滤 None（语义一致）
2. 旧版本遗留 None 会被自动清理（无需手动干预）
3. 防御性验证错误信息必须包含旧缓存兼容性诊断提示
4. calculate_ic_statistics 不会过滤 ic_series（输入长度 = 输出长度）
```

---

### Step 4.7: 增量模式 period 语义规范（v1.35 新增）

**遵循 PROJECT.md 增量模式 period 语义规范：增量模式下 period 和 total_days 必须覆盖合并后的 all_dates 范围。**

```
增量模式 period 语义处理流程
    │
    ├── [问题背景]
    │   │
    │   ├── 现有缓存：existing_dates 可能比当前因子缓存更早（历史数据）
    │   ├── raw_metadata['period_start'] = 当前因子缓存最小日期
    │   ├── 若只使用 raw_metadata：
    │   │   ├── period.start = 当前因子缓存最小日期
    │   │   ├── all_dates[0] = 历史缓存最小日期（可能更早）
    │   │   └── period.start > all_dates[0] → 语义矛盾
    │   │
    │   └── 注释语义："period 表示原始数据覆盖范围"与实际值矛盾
    │
    ├── [正确实现]
    │   │
    │   ├── _incremental_update() 第451-462行
    │   │   │
    │   │   ├── all_dates = sorted(date_ic_map.keys())
    │   │   │
    │   │   ├── 'period': {
    │   │   │       'start': min(all_dates[0], raw_metadata['period_start']),
    │   │   │       'end': max(all_dates[-1], raw_metadata['period_end'])
    │   │   │   }
    │   │   │
    │   │   ├── 'sample_stats': {
    │   │   │       'total_days': len(all_dates),
    │   │   │       'valid_days': len(valid_ic)
    │   │   │   }
    │   │   │
    │   │   └── 结果：period 覆盖合并后数据范围
    │   │
    │   └── 全量 vs 增量语义对比
    │       │
    │       ├── 全量：
    │       │   - period.start = raw_metadata['period_start']
    │       │   - period.end = raw_metadata['period_end']
    │       │   - total_days = raw_metadata['total_days']
    │       │   - period 覆盖当前因子缓存范围
    │       │
    │       └── 增量：
    │       │   - period.start = min(all_dates[0], raw_metadata['period_start'])
    │       │   - period.end = max(all_dates[-1], raw_metadata['period_end'])
    │       │   - total_days = len(all_dates)
    │       │   - period 覆盖合并后数据范围（包含历史缓存）
    │
    ├── [增量模式示例]
    │   │
    │   ├── 场景：
    │   │   - existing_dates = [2025-01-01, ..., 2025-05-31]（历史数据）
    │   │   - raw_metadata['period_start'] = 2025-06-01
    │   │   - all_dates = [2025-01-01, ..., 2025-06-30]
    │   │
    │   ├── 修复前（语义矛盾）：
    │   │   - period.start = 2025-06-01（当前因子缓存）
    │   │   - all_dates[0] = 2025-01-01（历史缓存）
    │   │   - period.start > all_dates[0] → 错误
    │   │
    │   └── 修复后（语义一致）：
    │       - period.start = min(2025-01-01, 2025-06-01) = 2025-01-01
    │       - period.end = max(2025-06-30, 2025-06-30) = 2025-06-30
    │       - total_days = len(all_dates) = 180天
    │       - period 覆盖合并后数据范围 ✓
    │
    └── [为何必须覆盖合并范围]
        │
        ├── period 应表示"最终输出数据的覆盖范围"
        │   - 非仅"当前因子缓存范围"
        │   - 增量合并后，输出数据包含历史缓存
        │   - period 必须覆盖完整输出范围
        │
        ├── total_days 应表示"最终输出数据的日期数"
        │   - 非仅"当前因子缓存日期数"
        │   - 必须与 len(all_dates) 一致
        │   - 与 period 覆盖范围对应
        │
        └── 语义一致性：
            - period.start ≤ all_dates[0]
            - period.end ≥ all_dates[-1]
            - total_days = len(all_dates)
```

**为何必须覆盖合并范围：**

```
问题：增量模式 period 语义矛盾（v1.34 之前版本）
1. 现有缓存可能比当前因子缓存更早
2. 若只使用 raw_metadata：
   - period.start = 当前因子缓存最小日期
   - all_dates[0] = 历史缓存最小日期（可能更早）
3. period.start > all_dates[0] → 语义矛盾
4. 注释说"period 表示原始数据覆盖范围"，但实际不覆盖历史数据

修复：
1. period.start = min(all_dates[0], raw_metadata['period_start'])
2. period.end = max(all_dates[-1], raw_metadata['period_end'])
3. total_days = len(all_dates)

结果：
1. period 覆盖合并后数据范围 ✓
2. total_days = len(all_dates) ✓
3. 语义一致性 ✓
```

**注意事项：**

```
1. 增量模式：period 覆盖合并后 all_dates 范围（包含历史缓存）
2. 全量模式：period 覆盖当前因子缓存范围
3. total_days 全量：raw_metadata['total_days']
4. total_days 增量：len(all_dates)
5. period 与 total_days 必须语义对应
```

---

### Step 5: 五维度判断结果

**实测结果（2026-05-12 18:30:00 北京时间）:**

```
RSI(6) IC 分析结果:
┌────────────────────────────────────────────────────────────┐
│  IC 均值: -0.0372                                          │
│  ICIR: 0.25                                                │
│  p 值: < 1e-06                                             │
│  t 统计量: -6.02                                            │
│  总天数: 515                                               │
│                                                            │
│  [五维度判断（独立输出）]                                    │
│  1. 统计显著性: p<1e-06 → 统计显著                          │
│  2. 方向判断: ic_mean=-0.0372 → 方向为负                    │
│  3. 经济显著性: |ic_mean|=0.0372≥0.03 → 经济显著弱          │
│  4. ICIR稳定性: ICIR=0.25<0.5 → 稳定性不足                  │
│  5. IC分布一致性: 正比例=38.1%与负方向一致 → IC分布正常      │
│                                                            │
│  五个维度独立输出，不合并为单一结论                           │
└────────────────────────────────────────────────────────────┘
```

**五维度判断说明（PROJECT.md 规范）:**

| 维度 | 判断标准 | 本次结果 |
|-----|---------|---------|
| 统计显著性 | p_value < 0.05 | p<1e-06 → 统计显著 |
| 方向判断 | ic_mean 的符号 | negative（反向因子） |
| 经济显著性 | |ic_mean| ≥ 0.03（弱）或 ≥ 0.05（强） | weak（0.0372≥0.03） |
| ICIR稳定性 | ICIR ≥ 0.5（可用）或 ≥ 1.0（较好） | none（0.25<0.5） |
| IC分布一致性 | positive_ratio 与 ic_mean_sign 匹配 | consistent（38.1%<50%对应负方向） |

**注意**: 五个维度独立输出，不合并为 factor_direction: valid/invalid

---

### Step 6: 输出结果

输出结果符合 PROJECT.md 规范的数据结构（五维度判断）：

**实测数据（2026-05-12 20:55 北京时间）:**

```json
{
    "factor_name": "rsi_1d",
    "calculation_date": "2026-05-12",
    "period": {
        "start": "2024-03-21",
        "end": "2026-05-11"
    },
    "ic_metrics": {
        "ic_mean": -0.037205,
        "ic_std": 0.149815,
        "icir": 0.2483
    },
    "sample_stats": {
        "total_days": 515,
        "valid_days": 514,
        "avg_stocks_per_day": 2719
    },
    
    "statistical_significance": {
        "p_value": 1.78e-09,
        "p_value_display": "< 1e-06",
        "t_stat": -6.0168,
        "nw_lag": 5,
        "nw_lag_method": "Newey-West (1994): lag = int(4*(T/100)^(2/9))",
        "is_significant": true,
        "conclusion": "统计显著（p=< 1e-06<0.05）"
    },
    "factor_direction": {
        "ic_mean": -0.037205,
        "ic_mean_sign": "negative",
        "direction_usage": "反向因子：分层回测时做多低值组、做空高值组",
        "conclusion": "因子方向为反向（ic_mean=-0.0372<0），分层回测做多低值组"
    },
    "economic_significance": {
        "abs_ic_mean": 0.037205,
        "threshold_used": {"weak": 0.03, "strong": 0.05},
        "level": "weak",
        "is_economically_significant": true,
        "conclusion": "经济显著弱（|ic_mean|=0.0372>=0.03）"
    },
    "icir_stability": {
        "icir": 0.2483,
        "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0},
        "level": "none",
        "is_stable": false,
        "conclusion": "IC稳定性不足（ICIR=0.25<0.5)"
    },
    "ic_distribution_consistency": {
        "positive_ratio": 0.3813,
        "ic_mean_sign": "negative",
        "is_consistent": true,
        "consistency_type": "consistent",
        "distribution_hint": "IC分布偏向负值（61.9%天数IC<0）",
        "conclusion": "一致：正比例<50%对应负方向，IC分布正常"
    },
    
    "dates": ["2024-03-21", "2024-03-22", ...],
    "ic_values": [-0.052, -0.023, -0.041, ...],
    "rolling_ic_mean": [null, null, null, null, null, null, null, null, null, -0.042, -0.041, ...],
    "positive_ratio": 0.3813,
    "n_assets": 2997,
    "summary": "IC均值=-0.0372, ICIR=0.25, p值=< 1e-06, 方向=negative, 统计显著=True, 经济显著=weak, ICIR稳定=none, 正比例=38.1%（IC>0天数占比）"
}
```

**规范字段说明**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `factor_name` | string | 因子标识，格式 `<因子名>_<周期>` |
| `calculation_date` | string | 计算日期 (YYYY-MM-DD) |
| `period.start` | string | 数据覆盖起始日期（因子缓存最小日期，可能 ≠ dates[0]） |
| `period.end` | string | 数据覆盖结束日期（因子缓存最大日期，可能 ≠ dates[-1]） |
| `ic_metrics.ic_mean` | float | IC均值 |
| `ic_metrics.ic_std` | float | IC标准差 |
| `ic_metrics.icir` | float | ICIR = |IC均值|/IC标准差（绝对值） |
| `sample_stats.total_days` | int | 因子缓存覆盖的日期数 |
| `sample_stats.valid_days` | int | 有效 IC 天数 |
| `sample_stats.avg_stocks_per_day` | int | 日均股票数 |
| `statistical_significance` | dict | 统计显著性判断（独立输出） |
| `factor_direction` | dict | 方向判断（独立输出，ic_mean符号） |
| `economic_significance` | dict | 经济显著性判断（独立输出） |
| `icir_stability` | dict | ICIR稳定性判断（独立输出） |
| `ic_distribution_consistency` | dict | IC分布一致性判断（独立输出） |

**period 与 dates 的边界说明（重要）**：

```
period 表示数据覆盖范围，dates 表示有效 IC 日期列表：
- period.start ≠ dates[0] → 首日因子数据无有效 IC（股票数不足等）
- period.end ≠ dates[-1] → 末日因子数据无有效 IC（股票数不足等）
- period 与 sample_stats.total_days 对应，dates 与 sample_stats.valid_days 对应
```

**额外字段**（保留原有功能）：

| 字段 | 类型 | 含义 |
|------|------|------|
| `dates` | array | 计算日期列表 |
| `ic_values` | array | 每日 IC 值 |
| `rolling_ic_mean` | array | 20日滚动 IC 均值（window=20, min_periods=10，前9个为null）详见 PROJECT.md |
| `positive_ratio` | float | IC > 0 的天数比例 |

---

## 📊 关键指标含义

| 指标 | 含义 | 判断标准 |
|------|------|----------|
| **IC均值** | 因子预测能力 | 正向因子：> 0.05 有效；反向因子：< -0.05 有效 |
| **ICIR** | IC稳定性（|ic_mean|/ic_std） | > 0.5 = 可用；> 1.0 = 较好；> 2.0 = 很好（绝对值，无需区分方向） |
| **正比例** | IC分布特征 | 正向因子：> 50% 分布正常；反向因子：< 50% 分布正常 |
| **t统计量** | IC是否显著不为零（用于输出，不用于判断） | |t| > 1.96 = 95%显著（与 p < 0.05 等价） |

---

## 🔧 数据依赖

```
cache/factor_data/
    ├── factor_data.json.gz    ← RSI(6) 等因子值（预先计算）
    └── return_data.json.gz    ← forward_return_1d 未来收益（预先计算）

这些缓存由上游预计算脚本生成，IC 计算器只读取，不生产。
```

---

## 📁 文件位置

| 文件 | 路径 | 说明 |
|------|------|------|
| IC计算脚本 | `factor_ic/ic_rsi_1d.py` | 主脚本 |
| 公共模块 | `factor_ic/common/ic_calculator.py` | 通用 IC 计算（方向验证）|
| 公共模块 | `factor_ic/common/data_completeness.py` | 数据完整性检查 |
| 公共模块 | `factor_ic/common/convert_types.py` | numpy 类型转换为原生 Python 类型 |
| 输出结果 | `factor_ic/result/ic_rsi_1d_analysis_result.json` | IC计算结果（规范命名） |
| 流程文档 | `factor_ic/docs/ic_rsi_1d_flow.md` | 本文档（规范命名） |
| 测试用例 | `factor_ic/test_cases/ic_rsi_1d_test_cases.py` | pytest测试文件 |

---

## 🔄 与其他因子的对比

| 因子 | IC计算方式 | 方向验证结果 | 说明 |
|------|------------|-------------|------|
| RSI | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
| KDJ_J | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
| Volume_Ratio | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |
| Turnover_Surge | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |
| Bollinger_PB | ic_calculator | negative | 方向由实测IC确定（ic_mean<0） |
| Main_Inflow_Ratio | ic_calculator | positive | 方向由实测IC确定（ic_mean>0） |

**注意**: 所有因子均需通过方向验证流程确认方向，不可预设。

---

## 📝 错误信息格式规范（v1.44 新增）

**遵循 PROJECT.md 错误信息格式规范：枚举类错误必须包含合法值列表，帮助用户理解正确用法。**

### 规范要点

| 规范项 | 要求 | 说明 |
|-------|------|------|
| 枚举类错误 | 必须包含合法值列表 | 如 `mode` 取值错误，错误信息必须列出 `['skip', 'incremental', 'full']` |
| 参数缺失错误 | 必须包含可用选项列表 | 如 `factor_col` 不存在，错误信息必须列出 `可用列: [...]` |
| 错误信息格式 | 多行结构，每行一个信息点 | 便于用户快速定位问题 |

### 正确示例

```python
# KeyError：因子列不存在（ic_rsi_1d.py 第120-125行）
if factor_col not in factor_df.columns:
    available_cols = sorted(factor_df.columns.tolist())
    raise KeyError(
        f"因子列 '{factor_col}' 不存在于缓存数据中\n"
        f"可用列: {available_cols}"
    )

# RuntimeError：未知计算模式（ic_rsi_1d.py 第728-734行）
else:
    raise RuntimeError(
        f"未知的计算模式: {mode}\n"
        f"合法值: ['skip', 'incremental', 'full']\n"
        f"请检查 check_data_completeness() 返回值是否正确"
    )
```

### 错误示例（不推荐）

```python
# 错误信息不包含合法值列表
raise RuntimeError(f"未知的计算模式: {mode}")
# 用户看到这个错误不知道合法值是什么，需要查阅源码或文档

# 错误信息不包含可用选项
raise KeyError(f"因子列 '{factor_col}' 不存在")
# 用户不知道有哪些可用列，需要手动检查 DataFrame.columns
```

### 规范来源

此规范源于代码中的正确实践（KeyError 处理），但之前未形成明确条文，导致部分代码（如未知模式处理）遗漏了这一最佳实践。v1.44 将其正式写入流程文档，确保所有错误处理遵循统一格式。

---

## 🔬 convert_to_native_types 行为验证规范（v1.45 新增）

**遵循 PROJECT.md NaN 处理规范：convert_to_native_types 是兜底保障，必须有单元测试验证其行为。**

### 规范要点

| 规范项 | 要求 | 说明 |
|-------|------|------|
| NaN → None | 必须验证 numpy.float64(NaN) → None | 数据生成阶段的兜底保障 |
| None → null | 必须验证 JSON 序列化 None → null | 标准 JSON 不支持 NaN，必须转为 null |
| 行为一致性 | 必须有单元测试 | 确保 numpy NaN 和 Python float NaN 行为一致 |

### 转换行为验证

```
convert_to_native_types 转换路径：
    │
    ├── numpy.float64(NaN) → None
    │       └── json.dumps(None) → "null"
    │       └── JSON 标准：null 是合法值
    │
    ├── Python float(NaN) → None
    │       └── json.dumps(None) → "null"
    │       └── 与 numpy NaN 行为一致
    │
    └── numpy.int64 → int
    └── numpy.float64 → float
    └── numpy.ndarray → list
    └── pandas.Series → list
    └── pandas.Timestamp → str
```

### 单元测试文件

**位置**: `factor_ic/test_cases/test_convert_types.py`

**测试覆盖**:

| 测试类别 | 测试项 | 验证内容 |
|---------|--------|---------|
| 基本类型转换 | numpy int/float/array | 转换为 Python 原生类型 |
| NaN 处理 | numpy NaN / Python NaN | 转换为 None |
| JSON 序列化 | 含 None 的数据 | None → null，JSON 输出不含 NaN |
| 嵌套结构 | dict/list 中的 NaN | 递归转换，确保 JSON 格式一致 |
| 边界情况 | None/空字典/空列表 | 正确处理 |

### 测试执行

```bash
cd /home/admin/projects/factor_ic_analyzer
python -m pytest factor_ic/test_cases/test_convert_types.py -v
```

**期望结果**: 24 passed

### 为何必须验证（设计动机）

```
问题背景：
1. json.dump(convert_to_native_types(ic_data), f) 是全量和增量的共同出口
2. 若 convert_to_native_types 将 NaN 转为 "NaN" 字符串而非 null
   → 下游读取 JSON 时解析失败（JSON 标准：null 是合法值，NaN 不是）
3. 若 convert_to_native_types 报错而非静默转换
   → IC 计算在保存阶段崩溃，用户数据丢失
4. 代码中未验证其行为，用户无法确认输出 JSON 格式是否一致

解决方案：
1. 必须有单元测试验证 convert_to_native_types 对 NaN 的处理行为
2. 测试覆盖 numpy NaN 和 Python float NaN（确保行为一致）
3. 测试验证 JSON 序列化结果（None → null，而非 NaN 或报错）
4. CI/CD 中运行测试，确保行为始终一致

设计原则（遵循 PROJECT.md 规范）：
- NaN → None 转换应在数据生成阶段完成（主动处理）
- convert_to_native_types 作为兜底保障（防御性措施）
- 但必须验证兜底保障的行为，否则无法保证输出一致性
```

### PROJECT.md 规范引用

```
# PROJECT.md 第 1087-1090 行
convert_to_native_types 仍然会处理 NaN（防御性措施），但：
- 数据生成阶段应主动处理 NaN（语义明确）
- convert_to_native_types 仅作为兜底保障（防止遗漏）
- 必须有单元测试验证其行为（确保兜底有效）
```

---

## 📋 函数签名变更同步规范（v1.46 新增）

**遵循 PROJECT.md 函数签名变更规范：返回值变更时必须同步更新类型注解和 docstring。**

### 规范要点

| 规范项 | 要求 | 说明 |
|-------|------|------|
| 类型注解 | 返回值变更时必须同步更新 | 如 `Tuple[...]` 返回值从 2 个变成 3 个，类型注解必须同步 |
| docstring | 返回值描述必须同步更新 | docstring 的 Returns 部分必须与实际返回值一致 |
| 调用方检查 | 必须确认所有调用方已同步修改 | 避免调用方接收参数数量不匹配导致运行时错误 |

### 正确示例

```python
# 函数定义：返回值从 2 个变成 3 个
def load_data_from_cache(
    factor_col: str = 'rsi_6',
    return_col: str = 'forward_return_1d'
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:  # 类型注解同步更新
    """
    从缓存加载因子数据和收益数据
    
    返回:
        (factor_df, return_df, raw_metadata)  # docstring 同步更新
        - factor_df: 过滤后的因子数据 DataFrame
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典  # 新增返回值描述
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    """
    ...
    return factor_df, return_df, raw_metadata  # 实际返回 3 个值

# 调用方：同步接收 3 个返回值
factor_df, return_df, raw_metadata = load_data_from_cache()
```

### 错误示例（不推荐）

```python
# 类型注解未同步更新（错误）
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame]:  # 只有 2 个
    """返回: (factor_df, return_df)"""  # docstring 只有 2 个
    ...
    return factor_df, return_df, raw_metadata  # 实际返回 3 个

# 调用方：类型注解误导，可能只接收 2 个
factor_df, return_df = load_data_from_cache()  # 运行时 ValueError: too many values to unpack
```

### 变更检查清单

当函数返回值变更时，必须检查以下内容：

| 检查项 | 检查方法 | 说明 |
|-------|---------|------|
| 类型注解 | 读取函数定义签名 | `-> Tuple[...]` 是否与实际返回值数量一致 |
| docstring | 读取函数 docstring | Returns 部分是否与实际返回值数量一致 |
| 调用方 | grep 搜索调用位置 | 所有调用方是否已同步接收新的返回值数量 |
| 流程文档 | 更新相关流程文档 | 返回值变更说明必须写入更新日志 |

### 为何必须同步（设计动机）

```
问题背景：
1. 函数返回值从 2 个变成 3 个（如 v1.28 新增 raw_metadata）
2. 类型注解未同步更新，仍标注为 Tuple[..., ...]（只有 2 个）
3. docstring 未同步更新，返回值描述只有 2 个
4. 调用方可能只接收 2 个值，导致运行时错误：
   ValueError: too many values to unpack (expected 2)
5. IDE 和静态类型检查器无法发现此问题（类型注解错误）

解决方案：
1. 返回值变更时必须同步更新类型注解
2. 返回值变更时必须同步更新 docstring
3. 必须检查所有调用方是否已同步修改
4. 必须在流程文档中记录变更说明
```

### 相关案例

**案例**: `load_data_from_cache` 返回值变更（v1.28）

- **变更**: 返回值从 `(factor_df, return_df)` 变为 `(factor_df, return_df, raw_metadata)`
- **原因**: 新增 raw_metadata 用于记录原始数据范围（dropna 前）
- **修复**: v1.46 同步更新类型注解和 docstring

---

*最后更新: 2026-05-20 00:15 (北京时间)*