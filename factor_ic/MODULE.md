# factor_ic 模块规范

> 版本: v3.8（精简版）
> 创建时间: 2026-05-19
> 重构时间: 2026-05-22
> 最后更新: 2026-05-23 (新增主函数数据加载异常处理规范、修复步骤编号错误)

## 快速参考

### 必须遵守的约束（15条）

| # | 约束 | 说明 |
|---|------|------|
| 1 | 因子方向不可预判 | 根据 IC 结果确定，不能假设 |
| 2 | 统计显著性只用 p<0.05 | 与 |t|>1.96 等价 |
| 3 | ICIR 用 abs(ic_mean) | 无论正向反向因子 |
| 4 | 输出结构必须统一 | 所有因子脚本输出相同结构 |
| 5 | 字段值不可为 None | 输出前诊断原因 |
| 6 | 日期格式 YYYY-MM-DD | 强制格式 |
| 7 | DataFrame 参数先 copy() | 函数入口处 |
| 8 | 禁止分层回测逻辑 | IC 脚本职责仅限于 IC 计算 |
| 9 | 增量模式复用 calculate_single_day_ic | 确保算法一致性 |
| 10 | 异常链保留 from e | ValueError 不包装 |
| 11 | Newey-West 样本量 T=valid_days | 不是 total_days |
| 12 | rolling_ic_mean 前 9 个为 None | min_periods=10 |
| 13 | sample_stats.avg_stocks_period 含口径说明 | 语义完整 |
| 14 | 修改公共模块同步更新 MODULE.md | 字段定义一致性 |
| 15 | 字段不重复输出 | 同一字段只在一处 |

### 关键函数签名

| 函数 | 文件 | 用途 |
|------|------|------|
| `load_factor_return_data(factor_cols)` | data_loader.py | 加载因子+收益数据 |
| `calculate_ic_with_direction_verification(factor_df, return_df, factor_col)` | ic_calculator.py | IC计算+五维度判断 |
| `build_ic_result(ic_result, raw_metadata, factor_name)` | ic_result_builder.py | 构建输出结构 |
| `incremental_update_ic(output_path, factor_df_full, ...)` | incremental_engine.py | 增量更新 |
| `run_simple_factor_ic(factor_name, factor_col)` | factor_ic_runner.py | 简单因子主入口 |
| `run_complex_factor_ic(..., custom_factor_calculation)` | factor_ic_runner.py | 复杂因子主入口 |

### 输出结构模板

```json
{
  "factor_name": "<str>",
  "calculation_date": "<ISO时间>",
  "period": {"start": "<str>", "end": "<str>", "description": "<str>"},
  "ic_metrics": {"ic_mean": <float>, "ic_std": <float>, "icir": <float>, "p_value": <float>, "p_value_display": "<str>"},
  "sample_stats": {"total_days": <int>, "valid_days": <int>, "avg_stocks_per_day": <float>, "avg_stocks_period": {"start": "<str>", "end": "<str>", "description": "<str>"}},
  "statistical_significance": {"t_stat": <float>, "p_value": <float>, "p_value_display": "<str>", "nw_lag": <int>, "nw_lag_method": "<str>", "is_significant": <bool>, "conclusion": "<str>"},
  "factor_direction": {"ic_mean": <float>, "ic_mean_sign": "<str>", "direction_usage": "<str>", "conclusion": "<str>"},
  "economic_significance": {"abs_ic_mean": <float>, "threshold_used": {"weak": 0.03, "strong": 0.05}, "level": "<str>", "is_economically_significant": <bool>, "conclusion": "<str>"},
  "icir_stability": {"icir": <float>, "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0}, "level": "<str>", "is_stable": <bool>, "conclusion": "<str>"},
  "ic_distribution_consistency": {"positive_ratio": <float>, "ic_mean_sign": "<str>", "consistency_type": "<str>", "distribution_hint": "<str>", "is_consistent": <bool>, "conclusion": "<str>"},
  "dates": ["<日期列表>"],
  "ic_values": [<IC值列表>],
  "rolling_ic_mean": [<滚动均值列表>],
  "positive_ratio": <float>,
  "n_assets": <int>,
  "summary": {"ic_performance": "<str>", "statistical_significance": "<str>", "factor_direction": "<str>", "economic_significance": "<str>", "recommendation": "<str>"},
  "factor_stats": {"factor_name": "<str>", "return_period": "<str>", "data_source": "<str>", "total_days": <int>, "valid_days": <int>},
  "factor_col": "<str>",
  "update_mode": "<str>"
}
```

**字段说明（五维度判断）**：

| 字段 | 判断依据 | 子字段 |
|------|---------|--------|
| statistical_significance | Newey-West t检验，p<0.05 | t_stat, p_value, p_value_display, nw_lag, nw_lag_method, is_significant, conclusion |
| factor_direction | ic_mean 符号判断 | ic_mean, ic_mean_sign, direction_usage, conclusion |
| economic_significance | |ic_mean| >= 0.03/0.05 | abs_ic_mean, threshold_used, level, is_economically_significant, conclusion |
| icir_stability | |ICIR| >= 0.5/1.0/2.0 | icir, threshold_used, level, is_stable, conclusion |
| ic_distribution_consistency | 正比例与方向一致/矛盾 | positive_ratio, ic_mean_sign, consistency_type, distribution_hint, is_consistent, conclusion |

**辅助字段说明**：

| 字段 | 含义 | 来源 |
|------|------|------|
| n_assets | 平均股票数 | raw_metadata.avg_stocks_per_day |
| factor_stats | 因子元信息 | build_ic_result 构建（含 data_source, return_period） |
| factor_col | 因子列名 | 用于追踪（如 rsi_6, kdj_j） |

---

## 更新记录

1. v1.0 首次创建模块规范
2. v1.1 删除重复的流程文档规范（已迁移至 PROJECT.md）
3. v1.2（2026-05-21）：
   - 统一 statistical_significance 字段定义（三处统一为7字段）
   - 补充公共模块同步规范
4. v1.3（2026-05-21）：精简重复章节标题
5. v1.4（2026-05-22）：合并重复章节，行数4761→3892
6. v2.0（2026-05-22）：按主题归类为6大章节，压缩格式，保留所有内容
7. v2.1（2026-05-22 08:35）：
   - 新增"公共模块架构"章节（data_loader.py 规范）
   - 新增因子脚本抽象设计目标（从~700-1100行降至~50-200行）
   - 添加 data_loader.py 使用示例和规范要点
8. v2.2（2026-05-22 08:45）：
   - 新增 ic_result_builder.py 规范（构建完整输出结构）
   - 添加 build_ic_result() 使用示例和辅助函数说明
9. v2.3（2026-05-22 09:00）：
   - 新增 incremental_engine.py 规范（增量更新引擎）
   - 新增 factor_ic_runner.py 规范（主入口模板）
   - 添加新增因子开发流程说明（总代码量~50-200行）
   - 添加 CLI 支持说明
10. v2.4（2026-05-22 10:30）：
    - 公共模块验证完成（test_public_modules.py 所有字段符合规范）
    - ic_rsi_1d.py 重构完成（774行→206行，减少73%）
    - 修复验证脚本字段检查列表（statistical_significance 字段名统一）
    - 新增重构脚本使用说明（保留原版为 ic_rsi_1d_legacy.py）
11. v2.5（2026-05-22 11:15）：
    - 5个因子脚本全部重构完成，平均减少72%代码量
    - ic_volume_ratio_1d.py（686行→193行，减少72%）
    - ic_kdj_j_1d.py（882行→310行，减少65%，保留KDJ计算）
    - ic_bollinger_pb_1d.py（1129行→240行，减少79%，保留布林带计算）
    - ic_turnover_surge_1d.py（798行→261行，减少67%，保留换手率筛选）
    - 重构汇总：原版保存为 *_legacy.py，新增因子仅需~200-300行
12. v2.6（2026-05-22 14:30）：
    - 新增"职责边界规范"章节：IC脚本只做IC计算，禁止分层回测
    - ic_volume_ratio_1d.py 删除分层回测逻辑（193行→145行）
    - 明确 factor_ic/ 与 backtest/ 模块职责边界
13. v3.0（2026-05-22）：
    - 大规模精简，从3558行精简至2652行，减少26%
    - 按主题归类为6大章节
    - 补充多个技术陷阱规范
14. v3.1-v3.2（2026-05-22）：持续精简优化
15. v3.3（2026-05-22 22:30）：
    - 新增"EWM 初始值处理规范"章节
    - 修复 ic_kdj_j_1d.py `_calculate_k_with_initial` 和 `_calculate_d_with_initial` 逻辑错误
    - 核心原则：EWM 初始值是前一期(t-1)的虚拟值，不是当前期(t)的输入覆盖值
    - 错误：覆盖第一个有效 RSV/K 值；正确：在第一个有效值前插入虚拟初始值
16. v3.4（2026-05-22 23:00）：
    - 新增"中间变量避免污染输出 DataFrame 规范"章节
    - 新增"CLI 入口异常处理堆栈保留规范"章节
    - 修复 ic_kdj_j_1d.py `calculate_kdj_j` 中间变量污染问题（rsv/k/d 改为局部变量）
    - 修复 `__main__` 异常处理堆栈丢失问题（logger.error → logger.exception）
17. v3.5（2026-05-22 17:15）：
    - 补充输出结构模板缺失字段（五维度判断完整定义）
    - 添加 economic_significance、icir_stability、ic_distribution_consistency 字段定义
    - 更新 ic_metrics（添加 p_value_display）、sample_stats（添加 avg_stocks_period）
    - 更新 statistical_significance（7字段）、factor_direction（4字段）、summary（5子字段）
    - 添加五维度判断字段说明表
18. v3.6（2026-05-22 17:30）：
    - 合并输出结构模板（行41-80）和统一输出结构定义（原行242-310）
    - 补充辅助字段：n_assets、factor_stats、factor_col
    - 删除重复定义，精简76行
    - 保留统一性要求和字段值完整性检查规范
19. v3.7（2026-05-23）：
    - 新增"SKIP 模式缓存对象处理规范"章节
    - 修复 ic_rsi_1d.py SKIP 模式修改缓存对象未持久化问题
    - 修复 ic_rsi_1d.py 全量/增量模式日志取值路径不一致问题
    - 核心原则：SKIP 模式不修改缓存对象，避免内存与文件不一致
20. v3.8（2026-05-23）：
    - 新增"主函数数据加载异常处理规范"章节
    - 修复 ic_rsi_1d.py 步骤编号错误（[N/3] → [N/4]）
    - 修复 ic_rsi_1d.py 异常处理粒度过粗问题
    - 核心原则：按异常类型分开处理，保留原始异常类型信息
21. v3.9（2026-05-23）：
    - 补充"新增因子开发"章节：数据加载流程说明
    - 明确 `factor_cols` 与 `additional_factor_files` 数据合并机制
    - 核心原则：自定义计算函数可访问所有合并列
22. v3.10（2026-05-23）：
    - 修订"pandas 缺失值标记规范"：浮点 Series 统一使用 np.nan
    - 修复 ic_turnover_surge_1d.py：pd.NA → np.nan（第107/127行）
    - 修复 ic_bollinger_pb_1d.py：pd.NA → np.nan（第107/112行）
    - 核心原则：构造时 pd.NA 会导致 dtype 变为 object，引发类型问题
23. v3.11（2026-05-23）：
    - 新增"股价类数据异常检测规范"章节
    - 修复 ic_turnover_surge_1d.py：prev_close 除零防护逻辑错误
    - 核心原则：异常检测优于静默修正，prev_close=0 计算出天文数字
24. v3.12（2026-05-23）：
    - 新增"rolling 窗口语义规范"章节
    - 修复 ic_turnover_surge_1d.py：surge_window rolling 包含当日语义错误
    - 核心原则："过去几日"不含当日，使用 shift(1).rolling(N)
    - 问题：包含当日导致因子值稀释，无法正确反映"突增"

# 一、概述与基础

## 概述

factor_ic 模块负责计算各类因子的 IC（Information Coefficient）值，用于评估因子对未来收益的预测能力。

**模块定位：**
- 输入：来自 data_fetchers 的缓存数据（cache/factor_data/）
- 输出：IC 分析结果（factor_ic/result/）
- 依赖：不自行拉取数据，只处理已缓存数据

### 职责边界规范

**核心原则：IC脚本只做IC计算，禁止分层回测。**

| 模块 | 职责 | 禁止 |
|------|------|------|
| `factor_ic/` | IC计算、方向判断 | 分层回测、回测引擎导入 |
| `backtest/` | 分层回测、净值曲线 | - |

### 公共模块同步规范

**修改公共模块必须同步更新 MODULE.md。**

同步检查：修改ic_calculator.py输出结构→检查字段定义位置→批量更新→提交。

## 公共模块架构

**目录规范：factor_ic下IC计算脚本的共用模块放在 `factor_ic/common/` 目录。**

禁止在IC脚本中重复实现已有公共功能，应复用common模块。

详细规范见 `factor_ic/common/README.md`。

| 模块 | 功能 | 核心函数 |
|------|------|----------|
| `data_loader.py` | 数据加载 | `load_factor_return_data()` |
| `ic_result_builder.py` | IC结果构建 | `build_ic_result()` |
| `incremental_engine.py` | 增量更新 | `incremental_update_ic()` |
| `factor_ic_runner.py` | 主入口 | `run_simple_factor_ic()`, `run_complex_factor_ic()` |

**新增因子开发：**
- 简单因子：`run_simple_factor_ic('rsi', 'rsi_6')`
- 复杂因子：`run_complex_factor_ic(factor_name, factor_col, factor_cols, custom_factor_calculation, additional_factor_files)`
- 数据加载流程（2026-05-23 补充）：
  1. `factor_cols` 指定从主缓存加载的列
  2. `additional_factor_files` 指定额外缓存文件，列会合并到 `factor_df`
  3. 合并后的 `factor_df` 传递给 `custom_factor_calculation`
  4. 自定义计算函数可访问所有合并列（`factor_cols` + `additional_factor_files`）

### factor_ic目录规范

**脚本命名：** `ic_<因子名>_<收益周期>.py`（如 `ic_rsi_1d.py`）

**数据来源：** 必须来自 `data_fetchers/` 缓存，禁止在脚本中拉取数据。

**输出路径：** `factor_ic/result/ic_<因子名>_<周期>_analysis_result.json`

# 二、IC计算核心

## IC 计算规范

### IC统计指标

| 字段 | 含义 | 计算方式 |
|------|------|---------|
| ic_mean | IC均值 | 有效日期IC算术平均 |
| ic_std | IC标准差 | 有效日期IC标准差 |
| ICIR | 信息比率 | abs(ic_mean)/ic_std |
| t_stat | t统计量 | ic_mean*sqrt(valid_days)/ic_std |
| p_value | 显著性p值 | 双尾t检验p值 |

**注意：** ICIR用abs(ic_mean)；p<0.05表示统计显著

### 因子方向判断

| IC特征 | 方向 | 说明 |
|--------|------|------|
| ic_mean>0.03 且 p<0.05 | 正向 | 高因子→高收益 |
| ic_mean<-0.03 且 p<0.05 | 反向 | 高因子→低收益 |
| p>0.05 | 无效 | 无预测能力 |

**禁止：** 根据因子类型假设方向；**正确：** 根据IC结果确定

### 反向因子IC计算

**业界标准：** 使用原始因子值计算Spearman IC，不做反转。

ic_mean<0 表示反向因子有效（高因子→低收益）。

分层回测时通过 `factor_direction='negative'` 参数控制方向。

### 输出结构统一性规范

#### 统一性要求
- 相同的顶层字段结构
- 相同的嵌套字段结构
- 相同的字段类型
- 相同的字段顺序

**输出结构定义见上方"输出结构模板"章节（行41-80），此处不再重复。**

### 字段值完整性检查规范

**核心原则：输出 JSON 前，检查每个字段是否有值。字段值为 None/null 代表数据有问题。**

| 字段类型 | 检查内容 | None/null 含义 |
|---------|---------|---------------|
| 数值字段（ic_mean, ic_std, icir, t_stat, p_value） | 必须有有效数值 | 计算失败 |
| 整数字段（total_days, valid_days, n_assets） | 必须 ≥ 0 | 数据源为空 |
| 字符串字段（factor_name, period.start/end） | 必须非空 | 数据缺失 |
| 数组字段（dates, ic_values） | 必须非空 | IC 计算失败 |

**诊断清单：**
- ic_mean=None → valid_days=0
- dates=[] → 所有日期跳过
- icir 无法计算 → ic_std=0

## 增量更新规范

### 增量模式定义

**增量模式 = 追加新日期IC值，保留历史IC值，重算统计指标**

触发条件：缓存存在→尝试增量；缓存不存在→全量计算；`--force-full`→强制全量

### 增量判断流程

```
缓存不存在 → full
缓存存在 → 读取existing_dates
比较existing_dates vs new_dates:
  new_dates ⊆ existing → skip（返回缓存）
  new_dates有缺失 → incremental（计算缺失日期IC，合并后重算统计）
```

### 因子脚本三模式处理规范（强制）

**所有因子脚本主函数必须处理 skip/incremental/full 三种模式。**

使用 `UpdateMode` 枚举判断：

```python
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental

mode = should_use_incremental(output_file, factor_df, force_full)

if mode == UpdateMode.SKIP:
    # 返回缓存数据，设置 update_mode='skip'
    ...
elif mode == UpdateMode.INCREMENTAL:
    # 调用 incremental_update_ic，设置 update_mode='incremental'
    ...
else:  # UpdateMode.FULL
    # 全量计算，设置 update_mode='full'
    ...
```

**禁止：**
- ❌ 只处理 skip 模式，缺失 incremental 分支（ic_bollinger_pb_1d.py 2026-05-22 诊断）
- ❌ 使用旧版 `should_use_incremental` 返回 bool（已改为返回 `UpdateMode` 枚举）

### SKIP 模式缓存对象处理规范（2026-05-23新增）

**核心原则：SKIP 模式不修改缓存对象，直接返回原数据，避免内存与文件不一致。**

**错误示例（修改缓存对象）**：
```python
# ❌ 错误：修改 cached_data['update_mode']，但未持久化
if mode == UpdateMode.SKIP:
    with open(output_file, 'r', encoding='utf-8') as f:
        cached_data = json.load(f)
        cached_data['update_mode'] = 'skip'  # 内存修改
        return cached_data
    # 问题：
    # - 调用方拿到的 cached_data['update_mode'] = 'skip'
    # - 但文件中 cached_data['update_mode'] 可能是旧值
    # - 内存数据与文件不一致，下次读取行为不可预测
```

**正确示例（不修改缓存对象）**：
```python
# ✓ 正确：直接返回缓存，不修改
if mode == UpdateMode.SKIP:
    logger.info("[模式] 缓存已最新，跳过更新")
    with open(output_file, 'r', encoding='utf-8') as f:
        cached_data = json.load(f)
        # 不修改 cached_data，直接返回
        return cached_data
```

**为何必须不修改缓存对象**：

| 原因 | 说明 |
|------|------|
| 内存文件一致性 | 修改后不持久化，调用方数据与文件不同步 |
| 行为可预测 | 下次读取时缓存内容不变，行为一致 |
| 遵循最小修改原则 | SKIP 模式语义是"跳过"，不应有任何修改 |

**适用场景**：
- SKIP 模式返回缓存数据
- 任何"只读返回"场景

**参考**：ic_rsi_1d.py 第152-165行（2026-05-23 修复）

### 因子计算异常处理顺序规范（2026-05-22新增）

**核心原则：按优先级顺序处理异常，先低后高，高优先级覆盖低优先级。**

**错误示例（逻辑隐晦，意图不清晰）：**

```python
# ❌ 错误：高优先级先处理，低优先级需额外条件排除
bollinger_pb = bollinger_pb.where(~abnormal_mask, None)  # 异常负值 → NaN（步骤1）
bollinger_pb = bollinger_pb.where(~narrow_band_mask | abnormal_mask, 0.5)  # 过窄 → 0.5（步骤2）
# 问题：
# - 步骤2的 `| abnormal_mask` 意图不明确（排除异常负值？）
# - 逻辑依赖 .where(True, value) 保留原值的隐晦行为
# - 注释与代码逻辑不符，极易引入维护bug
```

**正确示例（按优先级顺序，意图清晰）：**

```python
# ✅ 正确：按优先级顺序处理，先低后高，高优先级覆盖低优先级
# 优先级1（低）：band_width < EPSILON（过窄带宽）→ 0.5（中性值）
# 优先级2（高）：band_width < 0（异常负值）→ NaN（覆盖上一步）
bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)  # 过窄 → 0.5
bollinger_pb = bollinger_pb.where(~abnormal_mask, pd.NA)   # 异常负值 → pd.NA（覆盖）
```

**为何必须按优先级顺序：**

| 原因 | 说明 |
|------|------|
| 意图清晰 | 低优先级先处理，高优先级后处理并覆盖，逻辑一目了然 |
| 无隐晦条件 | 不需要 `| abnormal_mask` 这种"排除"逻辑 |
| 易于维护 | 新增异常类型只需追加一行 `.where()`，无需修改现有逻辑 |
| 符合直觉 | 高优先级"覆盖"低优先级，符合人类思维习惯 |

**适用场景：**
- 多种异常类型需不同处理（如：过窄 → 0.5，异常负值 → NaN）
- 异常类型有优先级关系（高优先级覆盖低优先级）
- 使用 `.where()` 或类似条件替换操作

**参考：** ic_bollinger_pb_1d.py 第99-103行（2026-05-22 修复）

### 因子计算异常集合关系规范（2026-05-22新增）

**核心原则：异常类型集合关系必须明确分离，避免模糊的包含关系。**

**错误示例（集合关系模糊）：**

```python
# ❌ 错误：narrow_band_mask 包含 abnormal_mask，集合关系不清晰
abnormal_mask = band_width < 0
narrow_band_mask = band_width < EPSILON  # 包含 band_width < 0！
# 问题：
# - narrow_band_mask ⊇ abnormal_mask（负值 < EPSILON）
# - 异常负值会被 narrow_band_mask 处理设为 0.5，再被 abnormal_mask 覆盖为 NaN
# - 冗余计算，逻辑意图不清晰
```

**正确示例（集合关系明确分离）：**

```python
# ✅ 正确：明确分离异常类型，集合关系清晰
abnormal_mask = band_width < 0
narrow_band_mask = (band_width >= 0) & (band_width < EPSILON)  # 排除异常负值
# 集合关系：abnormal_mask ∩ narrow_band_mask = ∅（互斥）
# 异常负值只被 abnormal_mask 处理，不参与 narrow_band_mask 处理
```

**为何必须明确分离：**

| 原因 | 说明 |
|------|------|
| 避免冗余处理 | 异常负值不会被 narrow_band_mask 处理再覆盖 |
| 逻辑意图清晰 | 每种异常类型只被处理一次 |
| 易于维护 | 新增异常类型时集合关系清晰，无需推断包含关系 |
| 便于调试 | 异常统计日志数量准确，不重复计数 |

**参考：** ic_bollinger_pb_1d.py 第93-95行（2026-05-22 修复）

### 因子计算异常排除时机规范（2026-05-22新增）

**核心原则：先排除异常再计算，避免冗余计算和掩盖意图。**

**错误示例（先计算后覆盖）：**

```python
# ❌ 错误：先 clip 异常数据，计算无意义值，再覆盖为 NaN
safe_band_width = band_width.clip(lower=EPSILON)  # 负值被 clip 为 EPSILON
bollinger_pb = (close - lower) / safe_band_width  # 异常数据计算出无意义值
bollinger_pb = bollinger_pb.where(~abnormal_mask, None)  # 再覆盖为 NaN
# 问题：
# - 冗余计算：异常数据先计算出无意义值，再被覆盖
# - 掩盖意图：clip 将负值提升为 EPSILON，看似"修正"实则后续覆盖
# - 效率损失：异常数据参与除法运算，浪费计算资源
```

**正确示例（先排除异常再计算）：**

```python
# ✅ 正确：先排除异常（mask 将异常设为 NaN），再 clip
safe_band_width = band_width.mask(abnormal_mask).clip(lower=EPSILON)
bollinger_pb = (close - lower) / safe_band_width
# 异常数据已为 NaN，NaN / 任何值 = NaN，无需后续覆盖
# 逻辑清晰：异常数据不参与 clip 和除法运算
```

**为何必须先排除异常：**

| 原因 | 说明 |
|------|------|
| 避免冗余计算 | 异常数据不参与除法运算，节省计算资源 |
| 意图清晰 | 异常数据从一开始就被排除，逻辑一目了然 |
| 无隐晦覆盖 | 不依赖后续 `.where()` 覆盖无意义值 |
| 符合直觉 | 异常数据不参与正常数据处理流程 |

**适用场景：**
- 异常数据需要排除而非静默修正
- 异常数据会导致计算结果无意义
- 使用 `.clip()` 或类似修正操作前需排除异常

**参考：** ic_bollinger_pb_1d.py 第97-99行（2026-05-22 修复）

### 股价类数据异常检测规范（2026-05-23新增）

**核心原则：股价类数据不应为零或负值，异常检测优于静默修正。**

**错误示例（静默修正掩盖异常）：**

```python
# ❌ 错误：使用 clip 静默修正 prev_close=0
prev_close = factor_df.groupby('asset')['close'].transform(lambda x: x.shift(1))
daily_return = (factor_df['close'] - prev_close) / prev_close.clip(lower=EPSILON)
# 问题：
# - prev_close=0 时：daily_return = (close - 0) / EPSILON = 天文数字（完全错误）
# - 静默修正掩盖了"股价为零"的数据异常
# - 无法区分 NaN（正常缺失）和 0（数据异常）
```

**正确示例（异常检测 + 排除）：**

```python
# ✅ 正确：检测异常并排除，而非静默修正
prev_close = factor_df.groupby('asset')['close'].transform(lambda x: x.shift(1))

# 异常检测：prev_close <= EPSILON（股价不应为零或负值）
abnormal_mask = (prev_close.notna()) & (prev_close <= EPSILON)
abnormal_count = abnormal_mask.sum()
if abnormal_count > 0:
    logger.warning(f"检测到 {abnormal_count} 个异常前收盘价（≤ {EPSILON}），已标记为 np.nan")

# 使用 mask 排除异常，而非 clip 静默修正
safe_prev_close = prev_close.mask(prev_close.isna() | (prev_close <= EPSILON))
daily_return = (factor_df['close'] - prev_close) / safe_prev_close
# 结果：NaN/异常位置自然为 NaN，无需后续覆盖
```

**为何必须异常检测而非静默修正：**

|| 原因 | 说明 |
|------|------|
|| 业务语义 | 股价不应为零，prev_close=0 是数据异常，应检测 |
|| 结果正确 | prev_close=0 静默修正后计算出天文数字，完全错误 |
|| 区分场景 | NaN（正常缺失）vs 0（数据异常），语义不同 |
|| 可追溯 | 异常日志记录，便于后续排查数据源问题 |

**适用场景：**
- 股价类数据计算（prev_close, close, high, low）
- 除零防护前需排除数据异常
- 区分"正常缺失"与"数据异常"

**参考：** ic_turnover_surge_1d.py 第115-129行（2026-05-23 修复）

### rolling 窗口语义规范（2026-05-23新增）

**核心原则："过去几日"不含当日，使用 shift(1).rolling(N) 而非 rolling(N)。**

**错误示例（包含当日）：**

```python
# ❌ 错误：rolling 包含当日，当日值同时出现在分子和分母
avg_turnover = turnover_rate.rolling(surge_window, min_periods=surge_window).mean()
turnover_surge = turnover_rate / avg_turnover
# 问题：
# - 当日换手率同时出现在分子（turnover_rate）和分母（avg_turnover）
# - 因子值被稀释，无法正确反映"突增"
# - 极端情况：当日换手率极高，因子值永远无法超过 1
# - 示例：turnover_rate = [1, 2, 3, 10, 5]
#   - 第4日 avg = (3+10)/2 = 5，surge = 10/5 = 2.0（稀释）
#   - 正确应为 avg = (1+2+3)/3 = 2，surge = 10/2 = 5.0（突增明显）
```

**正确示例（不含当日）：**

```python
# ✅ 正确：shift(1) 排除当日，rolling 只计算"过去几日"
avg_turnover = turnover_rate.shift(1).rolling(surge_window, min_periods=surge_window).mean()
turnover_surge = turnover_rate / avg_turnover
# 结果：
# - 分子：当日换手率
# - 分母：过去几日换手率均值（不含当日）
# - 因子值正确反映"突增"语义
# - 示例：turnover_rate = [1, 2, 3, 10, 5]
#   - 第4日 avg = (1+2+3)/3 = 2，surge = 10/2 = 5.0（突增明显）
```

**为何必须不含当日：**

|| 原因 | 说明 |
|------|------|
|| 因子语义 | "过去几日"不含当日，是业界标准定义 |
|| 避免稀释 | 当日值同时出现在分子分母，因子值被稀释 |
|| 正确反映突增 | 不含当日才能正确反映"突增"程度 |
|| 避免极端偏差 | 包含当日时，极高值因子永远无法超过 1 |

**适用场景：**
- 换手率突增因子（turnover_surge）
- 均值比较因子（当日值 vs 过去均值）
- 任何"当日 vs 历史"对比场景

**参考：** ic_turnover_surge_1d.py 第90-94行（2026-05-23 修复）

### pandas 缺失值标记规范（2026-05-22新增，2026-05-23修订）

**核心原则：浮点 Series 统一使用 np.nan 或 float('nan')，而非 pd.NA。**

**错误示例（使用 pd.NA）：**

```python
# ❌ 错误1：构造时使用 pd.NA（dtype 变为 object）
s = pd.Series([pd.NA, 1.0, 2.0])  # dtype: object，而非 float64
# 问题：
# - dtype 变为 object，无法使用矢量化数值运算
# - 内存效率低，类型不一致（NAType vs float）
# - 后续运算可能引发类型错误

# ❌ 错误2：.where() 使用 pd.NA（风格不一致）
s = pd.Series([1.0, 2.0, 3.0])
s = s.where(s > 1.5, pd.NA)  # 虽然 dtype 保持 float64，但风格不一致
# 问题：
# - pd.NA 会被转换为 np.nan，但意图不明确
# - 与构造场景使用 np.nan 的风格不一致
```

**正确示例（使用 np.nan 或 float('nan'))：**

```python
# ✅ 正确1：构造时使用 np.nan（dtype 保持 float64）
s = pd.Series([np.nan, 1.0, 2.0])  # dtype: float64

# ✅ 正确2：.where() 使用 np.nan 或 float('nan')
s = pd.Series([1.0, 2.0, 3.0])
s = s.where(s > 1.5, np.nan)  # dtype: float64，风格一致
s = s.where(s > 1.5, float('nan'))  # dtype: float64，风格一致
```

**为何浮点 Series 必须使用 np.nan：**

|| 原因 | 说明 |
|------|------|
|| dtype 一致 | 构造和 `.where()` 都保持 float64 |
|| 矢量化运算 | float64 支持矢量化数值运算，object 不支持 |
|| 内存效率 | float64 内存效率高于 object |
|| 类型一致 | 元素类型统一为 numpy.float64 |
|| 风格统一 | 与 ic_kdj_j_1d.py 使用 float('nan') 保持一致 |

**pd.NA 适用场景：**
- nullable Int64/String/boolean Series（非浮点）
- 显式缺失值标记（文档说明）

**np.nan 适用场景：**
- float64 Series（因子计算主要场景）
- 数值运算 Series

**参考：** ic_kdj_j_1d.py 第102/150行（使用 float('nan'))

### 模块级常量规范（2026-05-22新增）

**核心原则：避免除零阈值、精度参数等常量应提升为模块级常量。**

**错误示例（函数内定义）：**

```python
# ❌ 错误：EPSILON 定义在函数内部
def calculate_bollinger_pb(factor_df):
    EPSILON = 1e-10  # 函数内定义
    ...
```

**正确示例（模块级定义）：**

```python
# ✅ 正确：EPSILON 定义为模块级常量
EPSILON = 1e-10  # 模块级常量

def calculate_bollinger_pb(factor_df):
    # 使用模块级常量
    safe_band_width = band_width.clip(lower=EPSILON)
    ...
```

**为何必须使用模块级常量：**

| 原因 | 说明 |
|------|------|
| 易于复用 | 同一模块内其他函数可复用常量 |
| 易于维护 | 修改常量只需一处，无需逐函数修改 |
| 语义明确 | 模块级常量命名更规范（如 EPSILON 而非 epsilon） |
| 便于测试 | 常量可独立测试和验证 |

**适用场景：**
- 避免除零阈值（EPSILON）
- 数值精度参数（PRECISION）
- 默认窗口参数（DEFAULT_WINDOW）
- 任何模块内多处使用的固定值

**参考：** ic_bollinger_pb_1d.py 第49行（2026-05-22 修复）

### 缺失日期诊断

区分"数据源无数据"和"缓存缺失"：

| 场景 | 诊断 | 行动 |
|------|------|------|
| 缺失日期不在缓存范围 | 警告：N个日期不在缓存范围 | 检查数据源或全量重算 |
| 缺失日期在缓存但无有效数据 | 缺失日期筛选后无数据 | 检查股票过滤条件 |

# 三、数据处理

## 参数传递规范

**默认参数常量：** `DEFAULT_MIN_STOCKS=10`, `DEFAULT_IC_THRESHOLD=0.03`, `DEFAULT_P_THRESHOLD=0.05`

参数通过函数签名传递，禁止使用全局变量。

**禁止：**
- ❌ 在函数内部硬编码参数值（如 `min_stocks = 10`）
- ❌ 使用全局变量传递参数

### DataFrame参数副本规范

**函数入口必须先 `.copy()`，避免修改原始数据。**

```python
def calculate_factor(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()  # 第一步：创建副本
    factor_df['new_col'] = ...    # 安全修改
    return factor_df
```

**错误：** 列赋值后再 `.copy()`，副作用已产生。
```python
def calculate_factor(factor_df: pd.DataFrame):
    factor_df['factor_col'] = ...  # ❌ 先修改原数据
    factor_df = factor_df.copy()   # 副本已包含副作用
    
    return factor_df
```

不需要 `.copy()`：只读、返回全新DataFrame、内部已用 `.copy()`。

### 中间变量避免污染输出规范（2026-05-22新增）

**核心原则：使用局部变量存储中间结果，只写入最终因子列到输出 DataFrame。**

**错误示例（中间列污染输出）：**
```python
# ❌ 错误：rsv, k, d 中间列污染输出 DataFrame
def calculate_kdj_j(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()
    
    factor_df['rsv'] = ...  # 中间列
    factor_df['k'] = ...    # 中间列
    factor_df['d'] = ...    # 中间列
    factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
    
    return factor_df  # 返回包含 rsv, k, d, kdj_j 四列

# 问题：
# - 调用方拿到包含中间列的 DataFrame，增加内存占用
# - 中间列可能干扰下游逻辑（如 IC 计算期望只有因子列）
# - 输出结构不清晰，意图不明确
```

**正确示例（局部变量存储中间结果）：**
```python
# ✅ 正确：使用局部变量，只写入最终因子列
def calculate_kdj_j(factor_df: pd.DataFrame):
    factor_df = factor_df.copy()
    
    # 使用局部变量存储中间结果
    rsv = ...  # 局部变量（不写入 factor_df）
    k = rsv.groupby(factor_df['asset']).transform(...)
    d = k.groupby(factor_df['asset']).transform(...)
    
    # 只写入最终因子列
    factor_df['kdj_j'] = 3 * k - 2 * d
    
    return factor_df  # 只包含原始列 + kdj_j

# 优点：
# - 输出结构清晰，只有最终因子列
# - 减少内存占用，中间变量不保留
# - 不干扰下游逻辑
```

**为何必须避免中间列污染：**

| 原因 | 说明 |
|------|------|
| 减少内存占用 | 中间列不保留，减少 DataFrame 大小 |
| 输出结构清晰 | 调用方只拿到最终因子列，意图明确 |
| 不干扰下游逻辑 | IC 计算、回测等下游模块期望只有因子列 |
| 易于维护 | 新增因子开发时遵循统一规范 |

**适用场景：**
- 多步骤计算的因子（如 KDJ 的 rsv → k → d → j）
- 中间结果不需要保留的场景
- 因子计算函数返回 DataFrame

**参考：** ic_kdj_j_1d.py `calculate_kdj_j`（2026-05-22 修复）

### CLI 入口异常处理堆栈保留规范（2026-05-22新增）

**核心原则：使用 `logger.exception()` 保留完整堆栈信息，便于调试定位问题。**

**错误示例（堆栈信息丢失）：**
```python
# ❌ 错误：logger.error() 只记录异常消息，不记录堆栈
if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.error(f"未预期的错误: {e}")  # 只记录消息
        sys.exit(1)

# 问题：
# - 堆栈信息丢失，无法定位异常发生位置
# - 调试困难，需要重新运行才能看到完整堆栈
# - 日志信息不完整，不利于问题追溯
```

**正确示例（保留完整堆栈）：**
```python
# ✅ 正确：logger.exception() 自动记录异常消息 + 堆栈
if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        logger.exception(f"计算失败")  # 自动附加堆栈
        sys.exit(1)
    except Exception as e:
        logger.exception(f"未预期的错误")  # 自动附加堆栈
        sys.exit(1)

# 优点：
# - 堆栈信息完整，便于定位异常位置
# - 日志信息完整，利于问题追溯
# - 符合 Python 异常处理最佳实践
```

**为何必须保留堆栈：**

| 原因 | 说明 |
|------|------|
| 定位异常位置 | 堆栈显示异常发生的文件、行号、调用链 |
| 问题追溯 | 日志文件包含完整信息，便于事后分析 |
| 符合最佳实践 | Python 标准 logging 模块推荐做法 |

**适用场景：**
- CLI 入口（`if __name__ == '__main__'`）
- 顶层异常处理（捕获后退出程序）
- 需要记录完整异常信息的场景

**参考：** ic_kdj_j_1d.py `__main__` 部分（2026-05-22 修复）

### numpy 与 pandas 混用规范

**避免 `np.where` 与 pandas Series 混用，保持 pandas 语义。**

`np.where` 返回 numpy ndarray，丢失 Series 的 index 和 metadata。

**正确：** 使用 `Series.clip()` + `Series.where()` 保持 pandas 语义。
```python
# 避免除零
safe_denom = denom.clip(lower=EPSILON)
result = (factor_df['close'] - lower) / safe_denom

# 条件替换
narrow_mask = denom.abs() < EPSILON
result = result.where(~narrow_mask, 0.5)  # 保持 Series 类型
```

**禁止：**
```python
# ❌ np.where 返回 ndarray，丢失 Series index
result = np.where(
    np.abs(denom) < EPSILON,
    0.5,
    (factor_df['close'] - lower) / denom
)
factor_df['result'] = result  # ndarray 赋值给 DataFrame 列
```

适用场景：边界处理、条件替换、除零防护。

### EWM 初始值处理规范（2026-05-22新增）

**核心原则：EWM 递推的初始值是前一期（t-1）的虚拟值，不是当前期（t）的输入覆盖值。**

**技术陷阱：pandas ewm 不支持直接设置初始条件，常见错误是覆盖第一个有效输入值。**

**错误示例（覆盖第一个有效值）：**
```python
# ❌ 错误：将第一个有效 RSV 值覆盖为 initial_k
rsv_copy[first_valid_idx] = initial_k
k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False, ignore_na=False).mean()
# 问题：
# - 第一期的 RSV 真实值被丢弃
# - K[0] = initial_k（覆盖值），而非 alpha * RSV[0] + (1-alpha) * initial_k
# - K 值递推起点错误，后续所有 K 值都受影响
```

**正确示例（在第一个有效值前插入虚拟初始值）：**
```python
# ✅ 正确：在第一个有效 RSV **前**插入虚拟 initial_k
# EWM 递推公式：K[t] = alpha * RSV[t] + (1-alpha) * K[t-1]
# 初始条件：K[t-1] = initial_k（第一期之前的虚拟值）
rsv_with_initial = pd.concat([
    pd.Series([initial_k], index=[-1]),  # 虚拟初始值
    rsv_series
], ignore_index=True)

# 计算 ewm（使用 ignore_na=True，让初始值正确传播）
k_with_initial = rsv_with_initial.ewm(alpha=alpha_k, adjust=False, ignore_na=True).mean()

# 移除虚拟初始值，恢复原始索引
k_series = k_with_initial.iloc[1:]
k_series.index = rsv_series.index

# 恢复原始 NaN 位置（ewm 会填充 NaN 位置为初始值）
k_series = k_series.where(rsv_series.notna(), float('nan'))

# 结果：
# - K[0] = alpha * RSV[0] + (1-alpha) * initial_k（正确应用初始条件）
# - RSV 前缀 NaN 位置的 K 也为 NaN
# - 保留真实 RSV 值，不覆盖
```

**为何必须正确处理初始值：**

| 原因 | 说明 |
|------|------|
| 保留真实数据 | 第一期的输入值不应被覆盖 |
| 正确递推起点 | K[t-1]=50 是初始条件，K[0] = alpha * RSV[0] + (1-alpha) * 50 |
| 符合 KDJ 标准 | KDJ 标准公式中 K/D 的初始值都是 50（作为 t-1 的虚拟值） |
| pandas ewm 限制 | ewm 不支持直接设置 y[t-1] 初始条件，需手动插入虚拟值 |

**适用场景：**
- KDJ 的 K 值计算（initial_k=50）
- KDJ 的 D 值计算（initial_d=50）
- 任何需要 EWM 从特定初始值开始递推的场景

**参考：** ic_kdj_j_1d.py `_calculate_k_with_initial` 和 `_calculate_d_with_initial`（2026-05-22 修复）

# 四、异常处理

## 异常处理规范

**核心原则：区分严重错误（文件损坏、权限）和可恢复错误（文件不存在）；使用 `raise ... from e` 保留异常链；异常消息只包装一次。**

### SKIP 模式缓存读取异常处理

| 异常类型 | 处理方式 |
|---------|---------|
| ValueError | 直接 raise |
| FileNotFoundError | 降级全量计算 |
| JSONDecodeError/PermissionError | 不静默降级，抛出 RuntimeError |

**正确：**
```python
except FileNotFoundError:
    return _full_recalculate(...)
except json.JSONDecodeError as e:
    raise RuntimeError(f"缓存文件损坏: {output_file}") from e
```

**禁止：** 静默吞掉所有异常；ValueError包装为RuntimeError；异常消息多层叠加。

### 主函数数据加载异常处理规范（2026-05-23新增）

**核心原则：按异常类型分开处理，保留原始异常类型信息，便于调用方差异化处理。**

**异常分类与处理方式：**

| 异常类型 | 语义 | 处理方式 | 调用方应对 |
|---------|------|---------|-----------|
| FileNotFoundError | 缓存文件不存在（数据源缺失） | RuntimeError（提示运行数据采集） | 先运行数据采集 |
| JSONDecodeError | 缓存文件损坏 | RuntimeError（提示检查数据源） | 检查/重建缓存文件 |
| PermissionError | 权限错误 | RuntimeError | 检查文件权限 |
| KeyError | 数据结构错误（缺失必需字段） | ValueError（保留原始类型） | 检查数据采集脚本 |
| ValueError | 参数/数据验证失败 | 直接 raise（不包装） | 检查输入参数 |
| Exception | 其他未预期异常 | RuntimeError（含原始类型名） | 诊断堆栈信息 |

**正确示例（按类型分开处理）**：
```python
# ✓ 正确：按异常类型分开处理，保留原始异常信息
try:
    factor_df, return_df, raw_metadata = load_factor_return_data(...)
    
except FileNotFoundError as e:
    # 缓存文件不存在：严重错误，不降级（数据源缺失）
    raise RuntimeError(f"缓存文件不存在，请先运行数据采集: {e}") from e
except json.JSONDecodeError as e:
    # 缓存文件损坏：严重错误，不降级
    raise RuntimeError(f"缓存文件损坏，请检查数据源: {e}") from e
except PermissionError as e:
    # 权限错误：严重错误，不降级
    raise RuntimeError(f"缓存文件权限错误: {e}") from e
except KeyError as e:
    # 数据结构错误：严重错误，不降级（缺失必需字段）
    raise ValueError(f"缓存数据结构错误，缺少必需字段: {e}") from e
except Exception as e:
    # 其他未预期异常：保留完整堆栈信息，便于诊断
    raise RuntimeError(f"数据加载失败（未预期错误）: {type(e).__name__}: {e}") from e
```

**错误示例（粒度过粗）**：
```python
# ❌ 错误：所有异常统一包装为 RuntimeError，丢失原始异常类型
try:
    factor_df, return_df, raw_metadata = load_factor_return_data(...)
except FileNotFoundError as e:
    raise RuntimeError(f"缓存文件不存在: {e}") from e  # 丢失 FileNotFoundError 类型
except Exception as e:
    raise RuntimeError(f"数据加载失败: {e}") from e  # 粒度过粗，无法区分错误类型
```

**为何必须按类型分开处理：**

| 原因 | 说明 |
|------|------|
| 保留原始类型 | 调用方可通过异常类型判断错误类型，差异化处理 |
| 便于诊断 | 不同错误类型有不同的应对方案（数据采集、权限修复、重建缓存） |
| 符合规范 | MODULE.md 第815-819行已定义异常分类，代码应遵守 |
| 避免信息丢失 | `except Exception` 统一处理会丢失具体异常类型信息 |

**异常消息最佳实践：**

| 要素 | 示例 |
|------|------|
| 错误类型 | `缓存文件不存在` |
| 应对建议 | `请先运行数据采集` |
| 原始异常 | `: {e}` |

**适用场景：**
- 主函数数据加载（所有模式共享的前置步骤）
- 需要区分错误类型的场景

**参考：** ic_rsi_1d.py 第90-117行（2026-05-23 修复）
```

## 字段去重化规范

**原则：同一字段只在一个位置输出。**

| 字段 | 输出位置 |
|------|----------|
| ic_mean, ic_std, icir | `ic_metrics` |
| p_value, t_stat, is_significant | `statistical_significance` |

`p_value_display` 由上游 `_format_p_value()` 生成，回退值用 `round(x, 4)`。

## 日期类型一致性规范

**强制格式：** 所有日期字符串必须为 `YYYY-MM-DD` 格式。

```python
DATE_FORMAT_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
def validate_date_format(date_str: str) -> None:
    if not DATE_FORMAT_PATTERN.match(date_str):
        raise ValueError(f"日期格式错误: '{date_str}'，期望 YYYY-MM-DD")
```

应用场景：读取缓存/IC结果、生成period.start/end前验证。

**禁止：** 不验证格式就使用 min/max 比较日期。

## 输入验证规范

### 列存在检查

```python
REQUIRED_COLUMNS = ['date', 'symbol', 'factor_value', 'future_return']
def validate_columns(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"数据缺少必需列: {missing}")
```

## 公共函数复用规范

| 函数 | 文件 | 用途 |
|------|------|------|
| calculate_rank_ic | reverse_rank_ic.py | Spearman秩IC |
| validate_date_format | - | 日期格式验证 |

禁止在脚本中重新实现公共函数。

### calculate_ic_with_direction_verification

**函数接收未合并的 factor_df 和 return_df，内部负责合并。**

禁止调用前合并数据（死代码）。

## 增量更新返回数据规范

### _incremental_update返回数据结构

**必须与 `_full_recalculate` 返回值结构一致，包含 `rolling_ic_mean` 字段。**

前端依赖该字段绘制滚动IC均值趋势图，缺失会导致功能异常。

### incremental_update_ic 返回结构统一规范

**`incremental_update_ic` 返回结构必须与 `build_ic_result` 一致，包含 `ic_metrics`、`statistical_significance` 等五维度判断字段。**

调用方（因子脚本）使用统一字段路径访问：
```python
# ✓ 正确：使用 ic_metrics 结构
logger.info(f"IC 均值: {result.get('ic_metrics', {}).get('ic_mean', 0):.4f}")
logger.info(f"ICIR: {result.get('ic_metrics', {}).get('icir', 0):.2f}")

# ❌ 错误：直接访问顶层字段（增量返回结构不一致）
logger.info(f"IC 均值: {result.get('ic_mean', 0):.4f}")  # 增量模式可能 KeyError
```

**规范原因：**
1. 全量模式返回 `ic_metrics['ic_mean']`，增量模式返回顶层 `ic_mean` → 字段路径不一致
2. 调用方需要 `.get()` 防御，说明接口未统一
3. 增量模式缺少 `statistical_significance` 等五维度判断字段

### 步骤编号统一规范

**增量模式与全量模式步骤编号必须一致，统一为 `[N/4]` 格式。**

| 步骤 | 全量模式 | 增量模式 |
|------|----------|----------|
| 1 | 数据加载（前置） | 数据加载（前置） |
| 2 | `[2/4]` 计算因子 | `[2/4]` 计算因子 |
| 3 | `[3/4]` 计算 IC | `[3/4]` 执行增量 IC 计算 |
| 4 | `[4/4]` 构建输出并保存 | 增量结果已保存（内部完成） |

**禁止：** 增量模式使用 `[2/3]`、`[3/3]`，全量模式使用 `[2/4]`、`[3/4]`、`[4/4]`。

### fallback 使用内部函数重构规范

**SKIP fallback 应使用内部函数 `do_full_calculation()`，而非 mode 重置依赖 elif 链。**

```python
# ✓ 正确：使用内部函数，逻辑清晰
def do_full_calculation() -> dict:
    """执行全量计算（用于正常 FULL 模式和 SKIP fallback）"""
    # ... 全量计算逻辑
    return result

# SKIP 模式
if mode == UpdateMode.SKIP:
    try:
        cached_data = json.load(f)
        return cached_data
    except FileNotFoundError:
        logger.warning("[诊断] 缓存文件不存在，执行全量计算")
        return do_full_calculation()  # 直接调用，逻辑清晰

# FULL 模式
elif mode == UpdateMode.FULL:
    return do_full_calculation()  # 复用同一函数
```

**禁止：mode 重置依赖 elif 链**
```python
# ❌ 错误：mode 重置后依赖 elif 链（逻辑冗余且脆弱）
if mode == UpdateMode.SKIP:
    try:
        cached_data = json.load(f)
        return cached_data
    except FileNotFoundError:
        mode = UpdateMode.FULL  # 重置模式
        # 依赖后续 elif 链进入 FULL 分支

# 后续代码
elif mode == UpdateMode.INCREMENTAL:
    ...
elif mode == UpdateMode.FULL:
    # fallback 会进入这里，但读者需追踪 elif 链才能理解
```

**规范原因：**
1. 内部函数语义清晰，fallback 直接调用而非依赖控制流
2. FULL 模式和 SKIP fallback 复用同一函数，避免代码重复
3. 维护时不会引入 bug（显式调用而非隐式跳转）

### __main__ 防御性访问规范

**`__main__` 中访问嵌套字段必须使用 `.get()` 防御，兼容 SKIP 模式旧格式缓存。**

SKIP 模式返回的 `cached_data` 结构取决于缓存文件内容，旧格式可能无 `ic_metrics` 层。

```python
# ✓ 正确：使用 .get() 防御性访问
if __name__ == '__main__':
    result = generate_bollinger_pb_ic_data(...)
    
    ic_metrics = result.get('ic_metrics', {})  # 兼容旧格式
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")

# ❌ 错误：直接访问嵌套字段（SKIP 模式可能 KeyError）
if __name__ == '__main__':
    result = generate_bollinger_pb_ic_data(...)
    
    logger.info(f"因子名称: {result['factor_name']}")  # 可能 KeyError
    logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")  # 旧格式无 ic_metrics
```

**适用场景：**
- `__main__` 中访问 `result['ic_metrics']['ic_mean']`
- SKIP 模式返回旧格式缓存（顶层 `ic_mean` 而非 `ic_metrics['ic_mean']`)
- 增量模式已统一使用 `ic_metrics`，但全量和 SKIP 模式可能不一致

## NaN处理规范

**NaN → None 转换应在数据生成阶段完成。**

ic_series不含NaN的原因：ic_calculator.py 只添加 `ic_value is not None` 的日期，不满足min_stocks的日期不会被添加。

**ic_values不需要 pd.isna(v) 检查（隐式行为已注释）。**
# ic_series.values 不含 NaN 的原因：
rolling_ic_mean = [round(v, 6) if not pd.isna(v) else None for v in rolling_mean.values]
```

**rolling_ic_mean需要 pd.isna(v) 检查：** rolling参数前 min_periods-1 个时间点返回NaN。

**必须在数据生成阶段处理：** None表示"无有效数据"，JSON不支持nan。

全量路径和增量路径必须一致处理。

## 滚动窗口参数规范

**参数语义：**
| 参数 | 语义 |
|------|------|
| `window=N` | 使用过去N个时间点 |
| `min_periods=M` | 至少M个有效值才能计算 |

前 `min_periods-1` 个时间点返回NaN。

业务决策必须在注释中说明影响（如新上市股票历史数据不足）。

**min_periods选择原则：**
| min_periods值 | 适用场景 |
|---------------|----------|
| `min_periods=window` | 高质量要求，拒绝不完整数据 |
| `min_periods=window//2` | 平衡质量和覆盖度 |

禁止 `min_periods=1`（早期数据质量极差）。

### filter_stats统计口径

**区分三种数据丢失原因：**

| 字段 | 统计口径 |
|------|----------|
| `total_records` | 过滤前总数 |
| `rolling_nan_count` | rolling NaN数 |
| `condition_filtered_count` | 条件过滤数 |
| `valid_count` | 最终有效数 |

禁止模糊命名（如 `filtered_count` 易误解）。

## 变量命名语义清晰原则规范

**变量名必须包含数据源前缀（price, turnover, volume），避免模糊命名。**

| 场景 | 模糊命名（禁止） | 正确命名 |
|------|-----------------|----------|
| 收盘价涨跌幅 | `pct_change` | `price_pct_change` |
| 换手率变化率 | `pct_change` | `turnover_pct_change` |
| 均值 | `ma` | `turnover_ma_5` |

## 数据对齐验证规范

**合并数据后验证日期对齐，避免静默丢失数据。**

```python
factor_dates = set(factor_df['date'].unique())
return_dates = set(return_df['date'].unique())
missing_in_return = factor_dates - return_dates
if missing_in_return:
    raise ValueError(f"因子数据有 {len(missing_in_return)} 个日期在收益数据中不存在")
```

验证场景：load_data_from_cache、calculate_ic前、merge后、增量更新时。

## 极端值裁剪规范

**裁剪范围必须与筛选条件一致。裁剪下界≥筛选条件下界。**

| 场景 | 裁剪下界规则 |
|------|-------------|
| 筛选条件 `factor > X` | 裁剪下界 ≥ X |

**正确：** 筛选条件 `turnover_surge > 1`，裁剪 `clip(1.0, 10)`。
| 筛选条件 `factor < Y` | 裁剪上界 ≤ Y |
| 无筛选条件 | 根据业务逻辑设定 |

验证：裁剪下界 ≥ 筛选下界（如有）；裁剪上界 ≤ 筛选上界（如有）。

## 异常检测而非静默修正规范

**核心原则：检测异常并标记为 NaN，而非静默修正数值。**

静默修正会导致：
1. 计算结果符号和数值错误
2. 异常被掩盖，无法追溯数据质量问题
3. 比除零更难察觉的错误

**正确做法：**
```python
# ✓ 检测异常 → 标记为 NaN → 后续过滤处理
abnormal_mask = band_width < 0  # 布林带宽度理论上恒 >= 0，负值异常
normal_band_width = band_width.clip(lower=EPSILON)  # 正常带宽除零防护
bollinger_pb = (close - lower) / normal_band_width

# 异常标记为 NaN（不静默修正）
bollinger_pb = bollinger_pb.where(~abnormal_mask, None)

# 异常统计日志
if abnormal_mask.sum() > 0:
    logger.warning(f"检测到 {abnormal_mask.sum()} 个异常数据，已标记为 NaN")
```

**禁止：静默修正异常数值**
```python
# ❌ 使用 .abs() 静默修正负值
safe_band_width = band_width.abs().clip(lower=EPSILON)  # 分母变正，但 numerator 未变
bollinger_pb = (close - lower) / safe_band_width  # 符号和数值均错误

# 问题：
# 1. band_width < 0 说明 std 计算异常（数据质量问题）
# 2. .abs() 将分母变正，但 lower 仍是原始值（可能错误）
# 3. (close - lower) / |band_width| 符号和数值均错误
# 4. 难以察觉（没有报错，但结果语义错误）
```

**适用场景：**
- 布林带宽度 `band_width < 0`（理论上恒 >= 0）
- 换手率 `turnover < 0`（理论上恒 >= 0）
- 量比 `volume_ratio < 0`（理论上恒 >= 0）

**处理原则：**
| 异常类型 | 处理方式 |
|----------|----------|
| 数值超出理论范围 | 检测 → 标记 NaN → 日志警告 |
| 除零边界 | `clip(lower=EPSILON)` 防护 |
| 过窄带宽（接近零） | 设为中性值（如 0.5）|

## 主入口错误处理规范

**if __name__ == '__main__' 必须有错误处理，提供友好提示。**

| 异常类型 | 用户提示 |
|----------|----------|
| FileNotFoundError | "缓存文件不存在，先运行数据缓存脚本" |
| ValueError | "数据验证失败，检查数据质量" |
| RuntimeError | "计算过程异常，查看日志" |

退出码：0=成功，1=通用错误。

| 错误代码 | 问题 | 修复 |
|----------|------|------|
| `if __name__ == '__main__': func()` | 无错误处理，异常直接暴露 | 添加 try-except 块 |
| `except Exception: pass` | 隐藏异常，用户无法感知错误 | 打印友好提示 + sys.exit(1) |
| `print(e)` 只打印异常对象 | 用户无法理解错误含义 | 打印友好提示 + 详情 + 解决方法 |
| 无 sys.exit() | 异常后继续执行，可能产生更严重错误 | 错误处理后立即 sys.exit(1) |

## ic_series排序规范

**核心原则：** ic_series.index 必须按日期升序排列。

**显式排序：**
```python
ic_series = ic_series.sort_index()
```

**防御性校验：**
```python
if dates != sorted(dates):
    raise RuntimeError("dates 未按升序排列")
```

**为何必须显式排序:**
1. rolling 计算按位置顺序，而非 index 值顺序
2. 若 ic_series.index 乱序 → dates 与 rolling_ic_mean 对应错误
3. pandas groupby 默认 sort=True，但不应依赖隐式行为
4. 版本升级风险: pandas 可能改变默认行为
5. 增量路径合并后可能乱序

6. **两条路径一致性:**
   - 全量路径: `load_data_from_cache` 第124行显式转换为字符串
   - 增量路径: JSON 缓存存储字符串，读取后直接使用
   - 当前一致，但依赖隐式实现，缺乏规范保障

## ic_series.index类型规范

### ic_series.index类型规范核心原则
**ic_series.index 必须是字符串类型（格式为 "YYYY-MM-DD"），禁止使用 datetime 对象。**

### 类型约束
```python
# ✓ 正确: index 为字符串 "YYYY-MM-DD"
ic_series.index  # 类型: pandas.Index with dtype='object' (字符串)
# 示例: Index(['2024-01-01', '2024-01-02', ...], dtype='object')

```

**禁止行为:**
```python
# ❌ 禁止: index 为 datetime 对象
ic_series.index  # 类型: pandas.DatetimeIndex
# 问题:
# 1. rolling 计算无法处理 datetime index（可能报错）
# 2. JSON 序列化失败（datetime 无法直接序列化）
# 3. 日期比较逻辑不一致（datetime vs 字符串）
```

### 全量路径实现
**`load_data_from_cache` 负责显式转换:**
```python
# 第124行: 显式转换为字符串格式
factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
```

**`calculate_daily_ic_series` 返回时:**
```python
# 第376行: 转换为 JSON 友好格式
dates = [str(d) for d in ic_series.index]
```

### 增量路径实现
**`_incremental_update` 直接使用字符串 index:**
```python
# 第660行: 直接使用 valid_dates (字符串)
ic_series = pd.Series(valid_ic, index=valid_dates)
```

### 一致性验证
**两条路径确保 index 类型一致（字符串 "YYYY-MM-DD"）：**

| 路径 | index 来源 | 类型 | 保障机制 |
|------|------------|------|----------|
| 全量 | `load_data_from_cache` 第124行转换 | 字符串 | 显式转换规范 |
| 增量 | `existing_dates` (JSON 缓存) + `new_dates` (strftime) | 字符串 | JSON 缓存格式规范 |

# 五、代码设计

## 函数参数设计规范

### 函数参数设计规范核心原则
**函数签名不应有冗余参数，每个参数必须有实际用途。**

### 冗余参数判定规则
```python
# ❌ 参数永远不被传入，永远使用默认值
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10,
    period_start=None,  # 永远不传入
    period_end=None     # 永远不传入
):
    if period_start is None:  # 永远为 True
        period_start = str(factor_df['date'].min())

# ✓ 删除冗余参数，直接使用已有数据
def calculate_daily_ic_series(
    factor_df,
    return_df,
    raw_metadata,
    min_stocks=10
):
    period_start = raw_metadata['period_start']  # 直接使用
```

### 设计原则
1. **参数必要性：** 每个参数必须被实际传入或有明确的默认值语义
2. **数据源优先：** 如果已有数据结构包含所需信息，应直接使用，不应添加额外参数
3. **语义一致性：** 参数语义应与数据源语义一致，不应混用不同来源数据
4. **接口简洁：** 函数签名应尽可能简洁，避免不必要的复杂度

## period.start/end语义规范

### period.start/end语义规范核心原则
**period.start/end 表示原始缓存范围（dropna 前），而非过滤后范围。**

### 语义定义

| 字段 | 来源 | 语义 | 示例 |
|------|------|------|------|
| `raw_metadata['period_start']` | 原始缓存dropna前 | 原始最小日期 | 2024-01-01 |
| `raw_metadata['period_end']` | 原始缓存dropna前 | 原始最大日期 | 2026-05-15 |
| `factor_df['date'].min()` | 过滤后数据 | 过滤后最小日期 | 2024-01-20 |
| `factor_df['date'].max()` | 过滤后数据 | 过滤后最大日期 | 2026-05-15 |

### 差异原因
```
原始缓存范围：2024-01-01 ~ 2026-05-15
dropna 后范围：2024-01-20 ~ 2026-05-15

差异：前19天布林带 NaN 被过滤
```

### 正确使用
```python
# ✓ 使用 raw_metadata 表示原始缓存范围
period_start = raw_metadata['period_start']  # 2024-01-01
period_end = raw_metadata['period_end']      # 2026-05-15

# ❌ 使用 factor_df 表示原始缓存范围（语义错误）
period_start = str(factor_df['date'].min())  # 2024-01-20（错误！）
```

### 输出规范
**IC 计算结果的 period 字段应表示原始缓存范围：**
```json
{
  "period": {
    "start": "2024-01-01",  // 原始缓存最小日期
    "end": "2026-05-15"     // 原始缓存最大日期
  }
}
```

### total_days 使用规范
**核心原则：** total_days 直接使用 raw_metadata，不与过滤后数据做比较。

**禁止：**
```python
# ❌ 冗余的 max 比较
'total_days': max(raw_metadata.get('total_days', 0), factor_df_full['date'].nunique())

# 理由：
# 1. raw_metadata['total_days'] 表示原始缓存天数（dropna 前）
# 2. factor_df_full['date'].nunique() 表示过滤后天数（dropna 后）
# 3. 过滤后天数 ≤ 原始天数，max 永远返回原始天数
# 4. 冗余操作，增加代码复杂度
```

**正确：**
```python
# ✓ 直接使用 raw_metadata
'total_days': raw_metadata.get('total_days', 0)  # 原始缓存天数
```

## 字典结构缩进规范

### 字典结构缩进规范核心原则
**JSON 字典结构必须保持一致的缩进层级，缩进不一致会导致 IndentationError。**

### 缩进层级定义
```python
# ✓ 多层级字典缩进
merged_data = {
    'factor_name': 'bollinger_pb_1d',      # 第1层：8空格
    'ic_metrics': {                        # 第1层：8空格
        'ic_mean': 0.05,                   # 第2层：12空格
        'ic_std': 0.15                     # 第2层：12空格
    },                                     # 第1层闭合：8空格
    'sample_stats': {                      # 第1层：8空格
        'total_days': 545                  # 第2层：12空格
    }                                      # 第1层闭合：8空格
}

# ❌ 缩进不一致（IndentationError）
merged_data = {
    'factor_name': 'bollinger_pb_1d',
    'ic_metrics': {
        'ic_mean': 0.05,
        'ic_std': 0.15
    },
'sample_stats': {  # ❌ 缺少缩进
    'total_days': 545
}
```

### 缩进规则
1. **第1层字段：** 8空格缩进（函数体内字典）
2. **第2层字段：** 12空格缩进（嵌套字典内）
3. **第3层字段：** 16空格缩进（三层嵌套）
4. **闭合括号：** 与同级字段对齐（同级缩进）

### 常见错误
```python
# ❌ 错误：字典字段缩进缺失
'sample_stats': {  # 应有8空格缩进

# ❌ 错误：嵌套字段缩进不一致
'icir': round(result['icir'], 4)  # 应有12空格缩进

# ✓ 所有字段缩进一致
        'icir': round(result['icir'], 4)  # 12空格缩进
```

## 函数返回值契约规范（合并）

### 核心原则

**`required_fields` 校验列表必须包含所有后续直接访问的字段，禁止遗漏。**

### 正确实现

```python
# ✓ 校验列表包含所有直接访问的字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'p_value', 'p_value_display',  # ✓ 必须包含！
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(
        f"返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py"
    )

# 校验后可以安全访问
'p_value': round(result['p_value'], 6)  # ✓ 已校验，不会 KeyError
```

### 禁止行为

```python
# ❌ 校验列表缺少 p_value
required_fields = ['ic_series', 'ic_mean', 'ic_std', 'icir']

# 后续直接访问 p_value
'p_value': round(result['p_value'], 6)  # ✗ 未校验，可能 KeyError！
```

### 检查清单

```
□ 校验列表包含所有直接访问的字段
□ 校验后抛出 RuntimeError（包含缺失字段列表、问题定位）
□ 后续代码可安全访问已校验字段
```

## 输出字段规范（合并）

### 核心原则

**所有字段结构在两条路径（全量/增量）中必须完全一致。**

### 字段映射表（原始→输出）

| 字段组 | 原始字段名 | 输出字段名 | 类型 | 说明 |
|-------|----------|----------|------|------|
| **ic_metrics** | `ic_mean` | `ic_mean` | float | IC 均值 |
| | `ic_std` | `ic_std` | float | IC 标准差 |
| | `icir` | `icir` | float | ICIR |
| | `p_value` | `p_value` | float | p 值 |
| | `p_value_display` | `p_value_display` | str | p 值显示格式 |
| **factor_direction** | `ic_mean_sign` | `direction` | str | 因子方向（'positive'/'negative'/'zero') |
| | `ic_mean` | `ic_mean` | float | IC 均值 |
| | `conclusion` | `conclusion` | str | 方向判断结论 |
| **economic_significance** | `level` | `ic_strength` | str | IC 强度（'strong'/'weak'/'none') |
| | `abs_ic_mean` | `ic_mean_abs` | float | IC 均值绝对值 |
| | `conclusion` | `conclusion` | str | 经济显著性结论 |
| **statistical_significance** | 直接透传 | — | — | 字段名一致，无需重映射 |

### statistical_significance 必需字段（7个）

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `t_stat` | float | t 统计量（Newey-West调整） |
| `p_value` | float | p 值 |
| `p_value_display` | str | p 值显示格式 |
| `nw_lag` | int | Newey-West滞后阶数 |
| `nw_lag_method` | str | NW滞后选择方法 |
| `is_significant` | bool | 统计显著性标志 |
| `conclusion` | str | 统计显著性结论 |

### 正确实现

```python
# ✓ ic_metrics：全量/增量路径结构一致
'ic_metrics': {
    'ic_mean': round(result['ic_mean'], 6),
    'ic_std': round(result['ic_std'], 6),
    'icir': round(result['icir'], 4),
    'p_value': round(result['p_value'], 6),
    'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
}

# ✓ factor_direction：重映射字段名
'factor_direction': {
    'direction': result['factor_direction']['ic_mean_sign'],
    'ic_mean': result['factor_direction']['ic_mean'],
    'conclusion': result['factor_direction']['conclusion']
}

# ✓ economic_significance：重映射字段名
'economic_significance': {
    'ic_strength': result['economic_significance']['level'],
    'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
    'conclusion': result['economic_significance']['conclusion']
}

# ✓ statistical_significance：直接透传
'statistical_significance': result['statistical_significance']
```

### 禁止行为

```python
# ❌ 增量路径缺少字段
'ic_metrics': {'ic_mean': ..., 'ic_std': ..., 'icir': ...}  # 缺少 p_value

# ❌ 直接透传原始字段名（factor_direction/economic_significance）
'factor_direction': result['factor_direction']  # 字段名是 ic_mean_sign，不是 direction

# ❌ 分散赋值（字典构建）
result = {}
result['ic_mean'] = ic_mean
result['ic_std'] = ic_std  # 分散定义，容易遗漏
```

**校验示例:**
# 定义必需字段列表
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir',
    'statistical_significance', 'factor_direction',
    'economic_significance', 'icir_stability',
    'ic_distribution_consistency', 'positive_ratio', 'summary'
]

# 检查缺失字段
missing_fields = [f for f in required_fields if f not in result]

# 若缺失字段 → 抛出 RuntimeError
if missing_fields:
    raise RuntimeError(
        f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
        f"缺失字段: {missing_fields}\n"
        f"问题定位: factor_ic/common/ic_calculator.py\n"
        f"期望字段: {required_fields}"
    )
```

**为何必须校验返回值字段：**
1. 直接下标访问 result['field'] 会抛出 KeyError
2. KeyError 错误信息无法判断问题模块
3. 函数返回值结构变更时，调用方静默失败
4. 校验后的 RuntimeError 包含：缺失字段列表、问题定位、期望字段列表

## 增量计算None处理规范

**核心原则：** 增量计算中 None（股票数不足）的处理必须与全量计算保持一致。

**None 语义定义：**

| None 来源 | 语义 | 是否存储 |
|----------|------|---------|
| `calculate_single_day_ic` 返回 None | 股票数 < min_stocks | **不存储**（过滤） |
| 全量计算中 ic_series.index | 只有有效 IC 日期 | 不含 None |
| 增量计算中 new_ic_values | 可能含 None | **过滤后存储** |

**正确：**
```python
# 合并数据时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic

for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # 只写入有效 IC 值
        date_ic_map[date] = ic
```

## 全量/增量IC等价性规范

**核心原则：** 全量计算与增量计算使用同一核心函数（calculate_single_day_ic）。

**等价性验证三重保障机制：**

| 保障层 | 机制 | 说明 |
|-------|------|------|
| 第一层：代码架构 | 设计原则 | 全量/增量调用同一函数，无法独立演化 |
| 第二层：单元测试 | TestAlgorithmEquivalence | 验证单日期、多日期、边界情况等价性 |
| 第三层：文档规范 | Step 4.5 规范 | 修改核心函数时检查等价性 |

**禁止：**
```python
# ❌ 增量计算不使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = scipy.stats.spearmanr(factor_values, return_values)[0]  # 错误！

# ✓ 增量计算使用 calculate_single_day_ic
for date in missing_dates:
    ic_value = calculate_single_day_ic(
        daily_data,
        factor_col='rsi_6',
        return_col='forward_return',
        min_stocks=10
    )
```

## 旧缓存兼容性处理规范

**核心原则：** 增量计算读取现有缓存时，必须兼容旧版本缓存数据。

**背景：**
- v1.32 之前版本：ic_values 可能包含 None（未过滤股票数不足）
- 增量更新读取现有缓存 → existing_ic_values 可能包含 None

**兼容性处理：**
```python
# 合并数据时，existing 和 new 都过滤 None（语义一致）
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # 兼容旧缓存：过滤可能存在的 None
        date_ic_map[date] = ic
```

## 返回值标记规范

**核心原则：** 三种模式返回值必须标记 update_mode 字段。

**返回值标记设计：**

| 场景 | update_mode | 附加字段 | 调用方判断逻辑 |
|------|------------|---------|---------------|
| 正常 skip | `'skip'` | 无 | `update_mode == 'skip'` → 从缓存读取 |
| skip-fallback | `'full'` | `fallback_event` | `update_mode == 'full' && 'fallback_event' in result` → 意外触发全量 |
| 正常 incremental | `'incremental'` | `incremental_events` | `update_mode == 'incremental'` → 增量更新 |
| 正常 full | `'full'` | 无 | `update_mode == 'full' && 'fallback_event' not in result` → 正常全量 |

**为何必须标记返回值：**
1. mode='skip' 时读取缓存失败会 fallback 到全量计算
2. fallback 后返回值与正常全量计算返回值结构相同
3. 调用方无法区分来源
4. 若全量计算耗时很长，调用方毫不知情

## 错误信息格式规范

**核心原则：** 枚举类错误必须包含合法值列表。

**正确示例：**
```python
raise RuntimeError(
    f"未知模式: {mode}\n"
    f"合法值: ['skip', 'incremental', 'full']"
)
```

**错误信息对比：**

| 场景 | 未校验（KeyError） | 已校验（RuntimeError） |
|-----|-------------------|----------------------|
| 错误信息 | `KeyError: 'ic_mean'` | `缺少必需字段: ['ic_mean']\n问题定位: factor_ic/common/ic_calculator.py` |
| 问题定位 | 无法判断 | 明确模块路径 |
| 排查效率 | 低 | 高 |

## 字典构建规范

**核心原则：** 字段应集中定义在构建阶段，避免分散赋值。

**禁止：**
```python
# ❌ 分散赋值
result = {}
result['ic_mean'] = ic_mean
result['ic_std'] = ic_std
# ... 后面又赋值
result['update_mode'] = 'full'  # 分散，容易重复
```

**正确做法：**
```python
# ✓ 集中定义
result = {
    'ic_mean': ic_mean,
    'ic_std': ic_std,
    'icir': icir,
    'update_mode': 'full',  # 集中定义
}
```

## 输出字段口径规范

**核心原则：** 统计字段必须明确口径范围。

**正确：**
```json
{
  "avg_stocks_per_day": 4235.2,
  "avg_stocks_period": {
    "start": "2024-01-01",
    "end": "2024-12-31",
    "description": "平均每日有效股票数统计范围"
  }
}
```

**为何必须明确口径：**
- avg_stocks_per_day 基于 dropna 后数据
- total_days 基于 dropna 前数据
- 口径不同导致数值差异，必须通过字段说明

## 代码维护同步检查规范

**核心原则：** 添加新代码后检查旧代码是否冗余。

**清单：**
```
□ 新增字段 → 检查是否有重复赋值
□ 新增函数 → 检查是否有类似功能函数可合并
□ 新增逻辑 → 检查是否有冗余分支
□ 新增参数 → 检查是否有硬编码值可替换
```

## 设计演进清理规范

**核心原则：** 新实现替代旧实现后，必须删除旧代码，禁止保留死代码。

## 技术指标参数规范

### 布林带 rolling 窗口参数

**核心原则：** min_periods 必须等于 window，遵循技术指标标准定义。

**布林带标准定义：**
```
布林带需要满 N 个周期数据才能计算：
- Middle Band = SMA(Close, N)，需要 N 个数据点
- Upper/Lower Band = Middle + K × StdDev，标准差也需要 N 个数据点
- 前 N-1 个周期布林带值应为 NaN（等待足够数据）
```

**正确：**
```python
# ✓ min_periods=n，遵循标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).mean()
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()
)
```

**禁止：**
```python
# ❌ min_periods=1，违反标准定义
factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).mean()  # 错误！
)
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=1).std()  # 错误！
)

# 问题：
# - 第1个数据点：std=NaN（单点无法计算样本标准差）
# - 第2-4个数据点：std有值（基于不足N个数据点）
# - 违反布林带"满N周期才计算"的标准定义
```

为何 min_periods=n 是标准：
1. 布林带业界定义：需要满 N 个周期才产生有效值
2. 技术分析软件（TradingView、MetaTrader）均采用此定义
3. min_periods=1 会在前 N-1 周期产生非标准值，误导分析
4. 前N-1周期的NaN表示"数据不足，暂不计算"，语义清晰

### KDJ ewm 参数陷阱

**核心陷阱：ewm alpha 参数计算错误是常见bug。**

| 参数 | 错误值 | 正确值 | 原因 |
|------|--------|--------|------|
| alpha | `(m-1)/m` | `1/m` | ewm公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1] |
| ignore_na | True | False | False使NaN传播，前N-1期K也为NaN |
| first_valid_index | 用iloc[0] | 用series[idx] | 返回索引值而非位置 |

**ewm公式与KDJ公式对照：**
```
ewm公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1]
KDJ公式：K[t] = (1/m) * RSV[t] + (m-1)/m * K[t-1]

要匹配：alpha = 1/m（不是(m-1)/m）
```

**正确实现（ic_kdj_j_1d.py 第93行）：**
```python
# ✓ alpha = 1/m，ignore_na=False
k_series = rsv_copy.ewm(alpha=1/m, adjust=False, ignore_na=False).mean()

# ❌ alpha = (m-1)/m，错误
k_series = rsv_copy.ewm(alpha=(m-1)/m, adjust=False).mean()  # 错误！
```

**first_valid_index陷阱：**
```python
first_valid_idx = rsv_series.first_valid_index()
# ✓ 返回的是索引值，用series[idx]访问
initial_rsv = rsv_series[first_valid_idx]

# ❌ 用iloc[0]访问，错误
initial_rsv = rsv_series.iloc[0]  # 可能不是第一个有效值的位置
```

### 布林带标准差 ddof 参数

**核心原则：** 布林带标准差使用总体标准差（ddof=0），而非样本标准差（ddof=1）。

**布林带标准定义：**
```
布林带是对固定窗口内所有价格数据的标准差计算：
- Upper Band = Middle + K × StdDev(Close, N)
- StdDev = Population Standard Deviation（总体标准差）
- 公式：σ = sqrt(Σ(xi - μ)^2 / N)
- 不是对未知总体的样本估计，而是对固定窗口数据的完整统计
```

**正确：**
```python
# ✓ ddof=0，使用总体标准差
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std(ddof=0)
)
```

**禁止：**
```python
# ❌ 默认 ddof=1（样本标准差），系统性高估布林带宽度
factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
    lambda x: x.rolling(window=n, min_periods=n).std()  # 默认 ddof=1，错误！
)

# 问题：
# - 样本标准差公式：σ_sample = sqrt(Σ(xi-μ)^2 / (N-1))
# - 总体标准差公式：σ_population = sqrt(Σ(xi-μ)^2 / N)
# - 偏差系数：σ_sample = σ_population × sqrt(N/(N-1))
# - 对于 N=20：偏差约 2.5%（sqrt(20/19) ≈ 1.025）
# - 结果：布林带宽度系统性高估，%B 值系统性偏小
```

**为何 ddof=0 是标准：**
1. 布林带定义：对固定窗口内所有价格数据的完整统计，非样本估计
2. TradingView、MetaTrader 等业界软件均使用总体标准差
3. Bollinger 本人定义：Population Standard Deviation
4. ddof=1 会系统性高估带宽，导致 %B 指标失真

## 浮点数等值比较规范

### 浮点数等值比较规范核心原则

**浮点数等值比较使用精度容差，禁止直接使用 == 比较。**

### 浮点数等值比较规范问题背景

```
浮点数运算精度问题：
- IEEE 754 浮点数无法精确表示某些数值
- 运算结果可能产生微小误差（如 1e-15）
- 直接 == 0 比较会漏判极小值
- 极小值作为除数会产生极端结果（如 1e15）
```

### 浮点数等值比较规范正确实现

```python
# ✓ 使用精度容差判断
import numpy as np

EPSILON = 1e-10  # 浮点数精度容差

# 除零判断
diff = upper_band - lower_band
result = np.where(
    np.abs(diff) < EPSILON,  # 精度容差判断
    0.5,  # 默认值
    (close - lower_band) / diff
)
```

### 浮点数等值比较规范禁止行为

```python
# ❌ 直接 == 0 比较（浮点精度问题）
diff = upper_band - lower_band
result = np.where(
    diff == 0,  # 可能漏判 1e-15 等极小值
    0.5,
    (close - lower_band) / diff  # 可能产生极端值
)

# 问题示例：
# diff = 1e-15（浮点误差）
# diff == 0 → False（漏判）
# %B = 1.0 / 1e-15 = 1e15（极端值）
```

### 精度容差选择原则

```
| 场景 | 推荐容差 | 说明 |
|------|---------|------|
| 价格数据除零判断 | 1e-10 | 价格精度通常到小数点后2-4位 |
| 数值计算通用 | 1e-9 | 适合大多数浮点运算场景 |
| 高精度计算 | 1e-12 | 需要更高精度的特殊场景 |
```

### 适用场景

1. **布林带 %B 计算**：`diff = upper_band - lower_band` 除零判断
2. **RSI 计算**：`diff = max_gain - max_loss` 除零判断
3. **任何浮点数除法**：除数为运算结果时需精度容差判断

### 为何使用精度容差

1. IEEE 754 标准无法精确表示所有数值
2. 浮点运算累积误差可能导致极小值
3. 直接 == 比较会漏判，产生极端结果
4. 精度容差是业界做法（numpy、scipy 均采用）

## 增量路径核心规范（合并）

### 核心原则

**增量路径必须与全量路径保持一致：**
1. `rolling_ic_mean` 基于 `all_dates` 计算（长度一致）
2. `period.start/end` 使用 `raw_metadata`（语义一致）
3. 返回结构包含所有字段（与全量路径一致）

### rolling_ic_mean 规范

```python
# ✓ rolling_ic_mean 基于 all_dates 计算
ic_series = pd.Series(all_ic_values, index=all_dates)
rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
rolling_ic_mean = [round(v, 6) if not pd.isna(v) else None for v in rolling_ic_mean_series.values]

# 输出：dates, ic_values, rolling_ic_mean 长度一致（N=N=N）
merged_data = {
    'dates': all_dates,           # len = N
    'ic_values': all_ic_values,   # len = N
    'rolling_ic_mean': rolling_ic_mean,  # len = N ✓
}

# ❌ 基于 valid_dates 子集计算（长度不一致）
valid_dates = [all_dates[i] for i in valid_indices]
ic_series = pd.Series(valid_ic, index=valid_dates)  # 基于 valid_dates → 长度错位
```

### period 字段规范

**period 表示原始缓存范围（dropna前），而非合并后有效IC日期范围。**

| 数据源 | 语义 | 示例 |
|--------|------|------|
| raw_metadata['period_start'] | 原始缓存最小日期 | 2024-01-01 |
| raw_metadata['period_end'] | 原始缓存最大日期 | 2026-05-15 |
| all_dates[0] | 合并后有效IC最小日期 | 2024-01-20 |

```python
# ✓ period 直接使用 raw_metadata
merged_data = {
    'period': {
        'start': raw_metadata['period_start'],  # 原始缓存范围
        'end': raw_metadata['period_end']
    }
}

# ❌ 使用 all_dates（语义不一致）
'period': {'start': all_dates[0], 'end': all_dates[-1]}  # 有效IC范围 ≠ 原始缓存范围
```

### 返回结构一致性规范

**增量路径返回结构必须包含所有字段（与全量路径一致）。**

| 必须字段 | 说明 |
|---------|------|
| factor_name, calculation_date, period | 基本信息 |
| ic_metrics, sample_stats, statistical_significance | 统计指标 |
| factor_direction, economic_significance | 显著性判断 |
| dates, ic_values, rolling_ic_mean | IC序列数据 |
| positive_ratio, n_assets, summary, factor_stats | 辅助信息 |
| update_mode, incremental_days | 增量标记 |

```python
# ✓ 增量路径包含所有字段
merged_data = {
    # ... 所有字段 ...
    'factor_stats': factor_stats,  # ✓ 必须包含
    'update_mode': 'incremental',
    'incremental_days': len(new_dates)
}

# ❌ 增量路径缺少字段
merged_data = {'summary': {...}, 'update_mode': 'incremental'}  # 缺少 factor_stats
```

### 检查清单

```
□ rolling_ic_mean 基于 all_dates 计算（长度一致）
□ period 使用 raw_metadata（语义一致）
□ 返回结构包含所有字段（与全量路径一致）
□ dates, ic_values, rolling_ic_mean 长度相等
□ 增量标记：update_mode='incremental', incremental_days
```

    'period': {
        'start': raw_metadata['period_start'],  # 原始缓存范围
        'end': raw_metadata['period_end']       # 原始缓存范围
    },
    'sample_stats': {
        'total_days': raw_metadata.get('total_days', 0),  # 原始缓存天数
        'valid_days': len(all_dates),  # 有效IC天数
    }
}
```

### 增量路径 period 字段规范禁止行为

```python
# ❌ 混合不同语义的范围
merged_data = {
    'period': {
        'start': min(all_dates[0], raw_metadata['period_start']),  # 混合语义
        'end': max(all_dates[-1], raw_metadata['period_end'])      # 混合语义
    }
}

# 问题：
# - all_dates[0] 和 raw_metadata['period_start'] 语义不同
# - min/max 混合两个不同范围，语义模糊
# - 无法解释 period 表示什么范围
# - 与全量路径不一致（全量路径直接使用 raw_metadata）
```

### 为何使用 raw_metadata

1. **语义一致性：** period 表示原始缓存范围，而非有效IC范围
2. **两条路径一致：** 全量路径使用 raw_metadata，增量路径必须一致
3. **数据源稳定性：** raw_metadata 表示数据源范围，不受计算过程影响
4. **下游依赖明确：** 前端显示 period 时期望原始数据范围，而非计算后范围

### 全量/增量路径一致性验证

| 路径 | period.start来源 | period.end来源 | 语义 |
|------|-----------------|----------------|------|
| 全量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |
| 增量 | raw_metadata['period_start'] | raw_metadata['period_end'] | 原始缓存范围 ✓ |

**关键：** 增量模式追加数据不改变原始缓存范围，`period` 应始终表示数据源范围。

## 增量路径因子值有效性检查规范

### 增量路径因子值有效性检查规范核心原则

**增量路径检查缺失日期因子值是否有效，避免静默产生大量 None IC值。**

### 增量路径因子值有效性检查规范问题背景

```
布林带预热期问题：

布林带计算需要前N-1日数据预热：
- N=20，需要前19日数据
- rolling(window=n, min_periods=n) 确保 前19天为 NaN
- 缺失日期如果是缓存范围的前19天
- bollinger_pb_1d 全为 NaN（即使 factor_df_new 不为空）

示例场景：
- 缓存范围：2024-01-01 ~ 2026-05-15
- 缺失日期：2024-01-02（缓存范围第2天）
- factor_df_new 有数据（日期、股票、close）
- 但 bollinger_pb_1d 全为 NaN（只有1天历史数据，无法计算20日布林带）
- calculate_single_day_ic 返回 None
- 用户看不到诊断信息，不知道为什么跳过

问题后果：
- 静默产生大量 None IC值
- 用户不知道跳过原因
- 无法区分"股票数不足"和"因子值NaN"
```

### 增量路径因子值有效性检查规范正确实现

```python
# ✓ 检查因子值有效性
# 篛选缺失日期数据
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]

# 检查因子值有效性
valid_factor_count = factor_df_new['bollinger_pb_1d'].notna().sum()
total_factor_count = len(factor_df_new)

if valid_factor_count == 0:
    # 缺失日期因子值全为 NaN（布林带预热期）
    print(f"  [诊断] 缺失日期因子值全为 NaN（可能因布林带预热期）")
    print(f"  [诊断] 缺失日期: {sorted(factor_df_new['date'].unique())[:5]}")
    print(f"  [建议] 这些日期需要更多历史数据才能计算布林带，跳过增量计算")
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行，其中 {valid_factor_count} 行有效因子值")
if total_factor_count - valid_factor_count > 0:
    print(f"  - {total_factor_count - valid_factor_count} 行因子值为 NaN（布林带预热期）")
```

### 增量路径因子值有效性检查规范禁止行为

```python
# ❌ 只检查 factor_df_new 是否为空，不检查因子值有效性
if factor_df_new.empty:
    return existing_data

print(f"  - 篛选后: {len(factor_df_new)} 行")  # ✗ 没有检查因子值是否有效！

# 问题：
# - factor_df_new 不为空，但 bollinger_pb_1d 可能全为 NaN
# - 后续 calculate_single_day_ic 返回 None
# - 用户看不到诊断信息，不知道跳过原因
```

### 为何检查因子值有效性

1. **布林带预热期：** 技术指标需要历史数据预热，前N-1天因子值为 NaN
2. **诊断信息清晰：** 告知用户跳过原因，而非静默产生 None
3. **区分跳过原因：** 区分"数据缺失"、"股票数不足"、"因子值NaN"
4. **提前返回：** 若全为 NaN，直接返回缓存，避免无效计算

### 适用场景

1. **布林带 %B**：N=20，前19天预热期
2. **RSI**：N=6/14，前N-1天预热期
3. **KDJ**：N=9，前N-1天预热期
4. **任何需要历史数据的技术指标**

### 增量路径因子值有效性检查规范检查清单

```
□ 检查 factor_df_new 是否为空（数据缺失）
□ 检查因子值是否有效（notna().sum() > 0）
□ 提供诊断信息（缺失日期示例）
□ 区分不同跳过原因（数据缺失/因子值NaN/股票数不足）
□ 提前返回缓存（避免无效计算）
```

## 增量路径 None 值保留规范

### 增量路径 None 值保留规范核心原则

**增量路径合并时保留所有日期（包括 None IC 值日期），不过滤 None，确保 total_days 与 valid_days 的差值语义正确。**

### 增量路径 None 值保留规范问题背景

```
逻辑矛盾问题：

旧代码（错误）：
```python
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic
for date, ic in zip(new_dates, new_ic_values):
    if ic is not None:  # ✗ 过滤了 None
        date_ic_map[date] = ic

all_dates = sorted(date_ic_map.keys())  # ✗ 只包含有效 IC 日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None
```

问题后果：
- 丢失了"股票数不足跳过"日期（IC=None）
- total_days = len(all_dates) 只计算有效 IC 日期数
- valid_days 也只计算有效 IC 日期数
- 两者相等，无法区分跳过日期
- 语义失真：用户不知道有多少天因股票数不足跳过

示例场景：
- 现有缓存：dates=['2024-01-01', '2024-01-02'], ic_values=[0.05, None]
- 增量计算：new_dates=['2024-01-03'], new_ic_values=[None]
- 合并后：all_dates=['2024-01-01'], all_ic_values=[0.05]
- ✗ 丢失了 2024-01-02, 2024-01-03（都因股票数不足跳过）
- total_days=1, valid_days=1，但实际应有 total_days=3, valid_days=1
```

### 增量路径 None 值保留规范正确实现

```python
# ✓ 保留所有日期，不过滤 None
# 使用字典去重，保留 None 值
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤
for date, ic in zip(new_dates, new_ic_values):
    date_ic_map[date] = ic  # 保留 None 值，不过滤

# 按日期排序（包含所有日期，包括 None IC 值日期）
all_dates = sorted(date_ic_map.keys())
all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None

# 统计有效 IC 数（用于诊断信息）
valid_ic_count = sum(1 for ic in all_ic_values if ic is not None)
none_ic_count = len(all_ic_values) - valid_ic_count

print(f"  - 合并后总计: {len(all_dates)} 天（去重后）")
if none_ic_count > 0:
    print(f"  - 其中 {valid_ic_count} 天有效 IC，{none_ic_count} 天因股票数不足跳过（IC=None）")

# 后续 calculate_ic_statistics 会自动过滤 None 计算 valid_days
# total_days = len(all_dates)，valid_days = valid_ic_count
```

### 增量路径 None 值保留规范禁止行为

```python
# ❌ 合并时过滤 None
date_ic_map = {}
for date, ic in zip(existing_dates, existing_ic_values):
    if ic is not None:  # ✗ 过滤了 None，丢失跳过日期
        date_ic_map[date] = ic

# ❌ 只统计有效 IC 日期
all_dates = sorted(date_ic_map.keys())  # ✗ 不包含 None IC 日期
all_ic_values = [date_ic_map[d] for d in all_dates]  # ✗ 不包含 None

# 问题：
# - total_days = len(all_dates) = valid_days
# - 无法区分"股票数不足跳过"日期
# - 语义失真
```

### 为何保留 None 值

1. **语义正确性：** total_days 应表示所有日期数，valid_days 应表示有效 IC 数
2. **诊断信息完整：** 用户需要知道有多少天因股票数不足跳过
3. **统计指标准确：** calculate_ic_statistics 自动过滤 None，不影响 IC/ICIR 计算
4. **与全量路径一致：** 全量路径也保留 None 值

### calculate_ic_statistics 处理逻辑

```python
# common/ic_calculator.py 中的 calculate_ic_statistics
# 自动过滤 None 值，只计算有效 IC 的统计指标
def calculate_ic_statistics(ic_series: pd.Series) -> dict:
    # 过滤 None 值（pd.Series 中的 NaN）
    valid_ic = ic_series.dropna()
    
    # 统计指标基于有效 IC 计算
    ic_mean = valid_ic.mean()
    ic_std = valid_ic.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0
    
    # 但 total_days = len(ic_series)，valid_days = len(valid_ic)
    return {
        'total_days': len(ic_series),  # 包含 None 日期数
        'valid_days': len(valid_ic),   # 有效 IC 日期数
        ...
    }
```

### 增量路径 None 值保留规范检查清单

```
□ 合并时不过滤 None（保留所有日期）
□ all_dates 包含所有日期（包括 None IC 日期）
□ all_ic_values 包含 None（不过滤）
□ 提供诊断信息（valid_ic_count vs none_ic_count）
□ total_days 与 valid_days 差值语义正确
```

## 布林带因子规范（合并）

### 核心原则

**布林带因子使用 close 价格，这是布林带的数学定义。必须：**
1. 强制加载和过滤 'close' 列
2. %B 计算显式处理 NaN（而非依赖隐式传播）
3. 不接受 factor_col 参数（布林带固定使用 close）

### 布林带公式定义

```
中轨 = SMA(close, N)
上轨 = 中轨 + K × Std(close, N)
下轨 = 中轨 - K × Std(close, N)
%B = (close - 下轨) / (上轨 - 下轨)
```

### 正确实现

```python
# ✓ 固定加载 close 列（布林带数学定义）
def load_data_from_cache(return_col: str = 'forward_return_1d'):
    """布林带因子使用 close 价格，固定加载和过滤 'close' 列"""
    factor_cols = ['date', 'asset', 'close']  # 固定列名，不接受参数
    factor_df = factor_df[factor_cols].copy()
    factor_df = factor_df.dropna(subset=['close']).reset_index(drop=True)
    return factor_df, return_df, raw_metadata

# ✓ %B 计算显式处理 NaN
diff = factor_df['upper_band'] - factor_df['lower_band']
factor_df['bollinger_pb_1d'] = np.where(
    pd.isna(diff),  # 显式检查 NaN（布林带预热期）
    np.nan,         # NaN → NaN（显式定义）
    np.where(
        np.abs(diff) < 1e-10,  # 布林带宽度为零
        0.5,  # %B 定义为 0.5（价格在中轨）
        (factor_df['close'] - factor_df['lower_band']) / diff
    )
)
```

### 禁止行为

```python
# ❌ 只加载 factor_col 列，不强制加载 'close'
factor_cols = ['date', 'asset', factor_col]  # ✗ 不包含 'close'

# ❌ 接受 factor_col 参数（误导用户）
def load_data_from_cache(factor_col: str = 'close'):  # ✗ 参数对布林带无意义

# ❌ %B 计算依赖 NaN 传播的隐式行为
factor_df['bollinger_pb_1d'] = np.where(
    np.abs(diff) < 1e-10,  # ✗ NaN < 1e-10 返回 False（隐式）
    0.5,
    (close - lower) / diff  # ✗ NaN/NaN = NaN（隐式传播）
)
```

### 适用范围

此规范适用于所有依赖 close 价格的技术指标：布林带 %B、RSI、KDJ。

### 检查清单

```
□ 固定加载 'close' 列（factor_cols = ['date', 'asset', 'close'])
□ 固定过滤 'close' 列的 NaN
□ 不接受 factor_col 参数（布林带固定使用 close）
□ %B 计算显式检查 pd.isna(diff)
□ 使用嵌套 np.where 处理三种情况（NaN、宽度为零、正常）
```

## 列表索引访问前检查长度规范

### 列表索引访问前检查长度规范核心原则

**访问列表元素（如 list[0], list[-1]）前检查列表长度，避免 IndexError。**

### 列表索引访问前检查长度规范问题背景

```
IndexError 问题：

旧代码（错误）：
```python
# 日期格式断言
dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
for d in dates_to_check:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

问题后果：
- 如果 all_dates 为空（极端情况）
- all_dates[0] → IndexError: list index out of range
- all_dates[-1] → IndexError: list index out of range

示例场景（增量路径）：
- 现有缓存为空：existing_dates = [], existing_ic_values = []
- 新日期无有效数据：
  - 因子值全为 NaN（布林带预热期）
  - 或全部因股票数不足跳过（IC=None）
- 合并后：all_dates = [], all_ic_values = []
- 访问 all_dates[0] → IndexError
```

### 列表索引访问前检查长度规范正确实现

```python
# ✓ 检查列表长度，避免 IndexError
if len(all_dates) == 0:
    print("  [警告] 合并后无有效日期，跳过日期格式检查")
    dates_to_check = [raw_metadata['period_start'], raw_metadata['period_end']]
else:
    dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]

for d in dates_to_check:
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
        raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

### 列表索引访问前检查长度规范禁止行为

```python
# ❌ 直接访问列表元素，不检查长度
dates_to_check = [all_dates[0], all_dates[-1], ...]  # ✗ IndexError if all_dates is empty

# ❌ 假设列表不为空
# 问题：
# - 空列表访问索引会抛出 IndexError
# - 增量路径可能合并后为空
# - 缺少防御性检查
```

### 为何检查列表长度

1. **防御性编程**：避免极端情况下的 IndexError
2. **增量路径空合并**：现有缓存为空 + 新日期无有效数据 → 空列表
3. **诊断信息清晰**：告知用户为何跳过检查
4. **稳定运行**：不应因边界情况崩溃

### 列表索引访问前检查长度规范适用范围

此规范适用于所有列表索引访问：
1. **dates[0], dates[-1]**：访问日期列表首尾
2. **ic_values[0]**：访问 IC 值列表
3. **任何 list[index]**：访问列表任意索引

### 列表索引访问前检查长度规范检查清单

```
□ 访问 list[0] 前检查 len(list) > 0
□ 访问 list[-1] 前检查 len(list) > 0
□ 访问 list[index] 前检查 len(list) > index
□ 提供诊断信息（为何跳过检查）
□ 避免 IndexError 崩溃
```

## 增量路径向量化计算 IC 规范

### 增量路径向量化计算 IC 规范核心原则

**增量路径计算 IC 使用向量化处理：先整体 merge，再按日期 groupby 计算。禁止逐行循环做 DataFrame 过滤和 merge，这会导致严重性能问题。**

### 增量路径向量化计算 IC 规范问题背景

```
逐行循环性能问题：

旧代码（低效）：
```python
for date in new_dates:
    day_factor = factor_df_new[factor_df_new['date'] == date]  # ✗ 每次循环做 DataFrame 过滤
    day_return = return_df_new[return_df_new['date'] == date]  # ✗ 每次循环做 DataFrame 过滤
    
    # 合并
    merged = day_factor.merge(day_return, on=['date', 'asset'], how='inner')  # ✗ 每次循环做 merge
    
    # 计算 IC
    ic_value = calculate_single_day_ic(merged, ...)
    new_ic_values.append(...)
```

性能分析：
- 当 missing_dates = 100 天时
- 循环 100 次，每次做：
  - 2次 DataFrame 过滤（扫描全表 O(n)）
  - 1次 merge（O(m)）
- 总性能：100 × (2n + m) = O(200n + 100m)
- DataFrame 过滤每次扫描全表，非常低效

示例场景：
- missing_dates = 100 天
- factor_df_new = 100,000 行（100天 × 1000股票）
- 每次 DataFrame 过滤：扫描 100,000 行 → 找到 1000 行
- 100 次循环 × 100,000 扫描 = 10,000,000 次操作
- 性能极差，耗时显著增加
```

### 增量路径向量化计算 IC 规范正确实现

```python
# ✓ 向量化处理，先整体 merge
# 计算新日期的每日 IC（遵循 MODULE.md 增量路径向量化计算 IC 规范）
new_dates = sorted(factor_df_new['date'].unique())

# 向量化处理：先整体 merge（一次操作）
merged_new = factor_df_new.merge(return_df_new, on=['date', 'asset'], how='inner')

# 检查 merge 后是否有数据
if merged_new.empty:
    print("  [警告] merge 后无数据，所有日期因股票数不足跳过")
    new_ic_values = [None] * len(new_dates)
else:
    # 按日期分组计算 IC（向量化）
    # 使用 groupby 避免逐行循环，提升性能约 N 倍
    ic_results = {}
    for date, group in merged_new.groupby('date'):
        ic_value = calculate_single_day_ic(
            group, factor_col='bollinger_pb_1d', return_col='forward_return', min_stocks=min_stocks
        )
        ic_results[date] = round(ic_value, 6) if ic_value is not None else None
    
    # 按日期顺序填充 IC 值（缺失日期填充 None）
    new_ic_values = [ic_results.get(date) for date in new_dates]
```

### 增量路径向量化计算 IC 规范禁止行为

```python
# ❌ 逐行循环做 DataFrame 过滤
for date in new_dates:
    day_factor = factor_df_new[factor_df_new['date'] == date]  # ✗ 每次循环扫描全表

# ❌ 逐行循环做 merge
for date in new_dates:
    merged = day_factor.merge(day_return, ...)  # ✗ 每次循环做 merge

# ❌ 逐行循环计算 IC
for date in new_dates:
    ic_value = calculate_single_day_ic(merged, ...)  # ✗ 逐行循环

# 问题：
# - DataFrame 过滤每次扫描全表 O(n)
# - 当 missing_dates 较多时（如100天），性能极差
# - 总性能：N × (2n + m)，其中 N 为 missing_dates 数
# - 向量化处理性能：O(n + g)，其中 g 为组数（g << n）
```

### 性能对比

| 方式 | 操作数 | 性能 |
|------|--------|------|
| 逐行循环（N=100） | 100 × (2n + m) | O(200n + 100m) |
| 向量化处理 | n + g | O(n + g) |
| **性能提升** | - | **约 100 倍** |

当 missing_dates = 100 时，向量化处理性能提升约 100 倍。

### 为何使用向量化处理

1. **性能显著提升**：避免逐行循环扫描全表，性能提升约 N 倍
2. **DataFrame 过滤低效**：每次过滤扫描全表，非常耗时
3. **merge 操作昂贵**：每次 merge 需要哈希匹配，逐行循环浪费资源
4. **pandas 最佳实践**：向量化处理是 pandas 最佳实践

### 增量路径向量化计算 IC 规范适用范围

此规范适用于所有按日期分组计算的场景：
1. **IC 计算**：按日期分组计算 Spearman IC
2. **因子统计**：按日期分组计算因子统计指标
3. **收益分析**：按日期分组计算收益指标
4. **任何需要按日期分组的批量计算**

### 增量路径向量化计算 IC 规范检查清单

```
□ 先整体 merge（一次操作）
□ 按 groupby 计算（避免逐行循环）
□ 检查 merge 后是否有数据（空数据处理）
□ 按日期顺序填充 IC 值（缺失日期填充 None）
□ 禁止逐行循环做 DataFrame 过滤
□ 禁止逐行循环做 merge
```

## 增量路径布林带历史数据必要性规范

### 增量路径布林带历史数据必要性规范核心原则

**增量路径必须加载全量数据计算布林带，再筛选缺失日期。布林带使用 rolling(window=N) 计算 SMA 和 Std，每个目标日期需要前面 N-1 天历史数据。这是必要的，不是浪费。**

### 增量路径布林带历史数据必要性规范问题背景

```
历史数据必要性：

用户疑问：
- 为什么加载全量数据，只用到缺失日期数据？
- 是否浪费计算资源？

技术解释：
- 布林带公式：中轨 = SMA(close, N)，上轨 = 中轨 + K × Std(close, N)
- pandas rolling(window=N, min_periods=N)：需要前 N-1 天历史数据
- 例如 N=20：计算 2024-01-20 布林带
  - 需要 2024-01-01 ~ 2024-01-19 的历史数据（19天）
  - rolling 窗口包含 2024-01-01 ~ 2024-01-20（20天）
  - 2024-01-20 是目标日期，前19天是历史数据

示例场景：
- 缓存范围：2024-01-01 ~ 2024-01-31
- 缺失日期：2024-01-20 ~ 2024-01-25（6天）
- 需要计算 2024-01-20 布林带：
  - 需要 2024-01-01 ~ 2024-01-19 的历史数据（19天）
  - 如果不加载全量数据，无法计算 2024-01-20 布林带
- 因此必须加载全量数据，再筛选缺失日期
```

### 增量路径布林带历史数据必要性规范正确实现

```python
# ✓ 加载全量数据计算布林带，再筛选缺失日期
# 布林带计算说明（遵循 MODULE.md 增量路径布林带历史数据必要性规范）：
# - 布林带使用 rolling(window=N) 计算 SMA 和 Std，每个目标日期需要前面 N-1 天历史数据
# - 例如 N=20：计算 2024-01-20 布林带，需要 2024-01-01 ~ 2024-01-19 的历史数据
# - 因此必须加载全量数据计算布林带，再筛选缺失日期
# - 这是必要的，不是浪费：缺失日期布林带依赖历史数据作为滚动窗口

factor_df_full, return_df_full, raw_metadata = load_data_from_cache()

# 计算布林带%B因子（全量数据，滚动窗口需要历史数据）
factor_df_full, factor_stats = calculate_bollinger_pb_1d_factor(factor_df_full, n=n, k=k)

# 筛选缺失日期数据
missing_set = set(missing_dates)
factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
```

### 增量路径布林带历史数据必要性规范禁止行为

```python
# ❌ 只加载缺失日期数据
# 问题：布林带需要历史数据，缺失日期前 N-1 天数据缺失
factor_df_new = load_data_for_dates(missing_dates)  # ✗ 缺少历史数据

# ❌ 不注释说明历史数据必要性
# 问题：用户会误解为"浪费计算资源"
factor_df_full = load_data_from_cache()  # ✗ 无注释说明
```

### 为何必须加载全量数据

1. **布林带滚动窗口**：每个目标日期需要前面 N-1 天历史数据
2. **技术指标预热期**：布林带、RSI、KDJ 都需要历史数据预热
3. **缺失日期不连续**：缺失日期可能分散，每个都需要历史数据
4. **历史数据不可缺失**：缺失日期前的历史数据必须存在

### 增量路径布林带历史数据必要性规范适用范围

此规范适用于所有依赖技术指标预热因子计算：
1. **布林带 %B**：N=20，需要前19天历史数据
2. **RSI**：N=6/14，需要前N-1天历史数据
3. **KDJ**：N=9，需要前N-1天历史数据
4. **任何需要滚动窗口的技术指标**

### 增量路径布林带历史数据必要性规范检查清单

```
□ 加载全量数据计算布林带
□ 注释说明历史数据必要性（遵循 MODULE.md 规范）
□ 明确说明：这是必要的，不是浪费
□ 篮选缺失日期数据
□ 不只加载缺失日期数据（缺少历史数据）
```

## 增量路径最小必需历史窗口边界检查规范

### 增量路径最小必需历史窗口边界检查规范核心原则

**增量路径检查缺失日期是否在最小必需历史窗口内（布林带预热期）。缺失日期如果靠近缓存起始点（前N-1天内），因子值可能全为 NaN，需要提前警告并提供诊断信息。**

### 增量路径最小必需历史窗口边界检查规范问题背景

```
预热期边界问题：

布林带预热期：
- N=20，需要前19天历史数据
- 缓存起始点：2024-01-01
- 预热期：2024-01-01 ~ 2024-01-19（前19天）
- 2024-01-01 ~ 2024-01-19 布林带因子值 = NaN（预热期不足）

缺失日期在预热期：
- 缺失日期：2024-01-05（缓存范围第5天）
- 2024-01-05 只有前4天数据（2024-01-01~2024-01-04），不够19天
- 2024-01-05 布林带因子值 = NaN（预热期不足）
- 无法计算有效 IC，浪费计算资源

边界检查必要性：
- 提前识别预热期内的缺失日期
- 提供诊断信息：告知用户为何因子值全为 NaN
- 避免无效计算：如果所有缺失日期都在预热期，提前返回缓存
```

### 增量路径最小必需历史窗口边界检查规范正确实现

```python
# ✓ 检查缺失日期是否在预热期内
# 边界检查：最小必需历史窗口（遵循 MODULE.md 增量路径最小必需历史窗口边界检查规范）
cache_start_date = raw_metadata['period_start']
cache_start_dt = pd.to_datetime(cache_start_date)

# 计算布林带预热期边界日期（缓存起始点后 N-1 天）
warmup_boundary_date = (cache_start_dt + pd.Timedelta(days=n-1)).strftime('%Y-%m-%d')
warmup_days_count = n - 1

# 检查缺失日期是否在预热期内
missing_dates_in_warmup = [d for d in missing_dates if d <= warmup_boundary_date]

if missing_dates_in_warmup:
    print(f"  [边界检查] 缓存起始: {cache_start_date}")
    print(f"  [边界检查] 布林带预热期: 前 {warmup_days_count} 天（{cache_start_date} ~ {warmup_boundary_date}）")
    print(f"  [边界检查] {len(missing_dates_in_warmup)} 个缺失日期在预热期内，因子值可能全为 NaN")
    examples = sorted(missing_dates_in_warmup)[:5]
    print(f"  [边界检查] 示例日期: {examples}")
    if len(missing_dates_in_warmup) == len(missing_dates):
        print("  [边界检查] 所有缺失日期都在预热期内，无法计算有效 IC")
        print("  [建议] 延长缓存历史范围，或跳过这些日期")
        # 不直接返回缓存，继续计算以验证（可能部分股票有更多历史数据）
```

### 增量路径最小必需历史窗口边界检查规范禁止行为

```python
# ❌ 不检查预热期边界
# 问题：缺失日期在预热期内，因子值全为 NaN，浪费计算资源
factor_df_full = load_data_from_cache()
factor_df_full = calculate_bollinger_pb_1d_factor(factor_df_full, n=n)  # ✗ 无边界检查

# ❌ 不提供诊断信息
# 问题：用户不知道为何因子值全为 NaN
if valid_factor_count == 0:
    return existing_data  # ✗ 无诊断信息
```

### 边界检查逻辑

| 检查项 | 逻辑 | 诊断信息 |
|--------|------|----------|
| 缓存起始日期 | `raw_metadata['period_start']` | 缓存起始: YYYY-MM-DD |
| 预热期边界 | `缓存起始 + N-1 天` | 预热期: 前 N-1 天 |
| 缺失日期在预热期 | `missing_dates <= warmup_boundary` | X 个缺失日期在预热期内 |
| 全部在预热期 | `len(missing_dates_in_warmup) == len(missing_dates)` | 无法计算有效 IC |

### 为何检查边界

1. **避免无效计算**：缺失日期在预热期内，因子值全为 NaN
2. **提供诊断信息**：告知用户为何因子值全为 NaN
3. **用户可操作**：提供建议（延长缓存历史范围）
4. **提前预警**：避免用户困惑为何 IC 计算失败

### 增量路径最小必需历史窗口边界检查规范适用范围

此规范适用于所有依赖技术指标预热因子计算：
1. **布林带 %B**：N=20，预热期前19天
2. **RSI**：N=6/14，预热期前N-1天
3. **KDJ**：N=9，预热期前N-1天
4. **任何需要滚动窗口的技术指标**

### 增量路径最小必需历史窗口边界检查规范检查清单

```
□ 计算预热期边界日期（缓存起始 + N-1 天）
□ 检查缺失日期是否在预热期内
□ 提供诊断信息（缓存起始、预热期范围、示例日期）
□ 如果全部在预热期，建议用户延长缓存历史范围
□ 不直接返回缓存，继续计算以验证（部分股票可能有更多历史数据）
```

## 注释缩进一致性规范

### 注释缩进一致性规范核心原则

**注释必须与代码保持一致的缩进级别。Python不强制注释缩进，但最佳实践是注释与代码保持一致的缩进，避免视觉歧义。**

### 注释缩进一致性规范问题背景

```
注释缩进不一致问题：

旧代码（错误）：
```python
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ic_value = calculate_single_day_ic(...)
    
# 合并数据  # ✗ 顶格注释，无缩进
    print("合并数据并重新计算统计指标...")  # ✓ 有缩进
    
    # 检查重叠
    existing_set = set(existing_dates)
```

问题后果：
- 注释顶格（无缩进），代码有缩进
- 视觉上造成歧义：注释看起来在函数外
- 实际上代码仍在函数内，但注释格式混乱
- 维护者可能误解代码结构
- 不符合 Python 最佳实践
```

### 注释缩进一致性规范正确实现

```python
# ✓ 注释与代码保持一致的缩进
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ic_value = calculate_single_day_ic(...)
    
    # 合并数据（遵循 MODULE.md 注释缩进一致性规范）
    print("合并数据并重新计算统计指标...")  # ✓ 4空格缩进
    
    # 检查重叠
    existing_set = set(existing_dates)
```

### 注释缩进一致性规范禁止行为

```python
# ❌ 注释顶格，代码有缩进
def _incremental_update(...):
    # 计算 IC
    for date in new_dates:
        ...
    
# 合并数据  # ✗ 顶格注释，视觉歧义
    print("合并数据...")  # ✓ 有缩进

# ❌ 注释缩进与代码不一致
# 问题：
# - Python 不强制注释缩进，但最佳实践是保持一致
# - 视觉歧义：注释看起来在函数外
# - 维护者可能误解代码结构
```

### 为何必须保持注释缩进一致

1. **视觉清晰**：注释与代码保持一致的缩进，视觉上清晰
2. **避免歧义**：避免维护者误解代码结构
3. **最佳实践**：Python 最佳实践是注释与代码保持一致的缩进
4. **代码可读性**：提高代码可读性，易于维护

### 注释缩进一致性规范适用范围

此规范适用于所有 Python 代码：
1. **函数内注释**：注释与函数体代码保持一致的缩进
2. **类内注释**：注释与类体代码保持一致的缩进
3. **循环/条件块内注释**：注释与循环/条件块代码保持一致的缩进
4. **任何 Python 代码**

### 注释缩进一致性规范检查清单

```
□ 注释与代码保持一致的缩进
□ 函数内注释：4空格缩进（与函数体代码一致）
□ 类内注释：4空格缩进（与类体代码一致）
□ 循环/条件块内注释：与块内代码一致缩进
□ 避免顶格注释（除非是文件级注释）
□ 遵循 Python 最佳实践
```

## PEP8 import规范

### PEP8 import规范核心原则

**所有 import 语句必须在文件顶部，禁止在函数内部 import。函数内部 import 会每次调用时重新导入（性能问题），且降低代码可读性。**

### PEP8 import规范问题背景

```
函数内部 import 问题：

旧代码（错误）：
```python
# 文件顶部
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic
)

def _incremental_update(...):
    # 函数内部 import（违反 PEP8）
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 在函数内
    result = calculate_ic_statistics(ic_series)
```

问题后果：
- 违反 PEP8 规范：所有 import 应在文件顶部
- 性能问题：每次调用函数时都会执行 import（虽然 Python 有缓存机制）
- 降低可读性：import 分散在不同位置，难以追踪依赖
- 代码风格不一致：同一模块的函数分散导入
```

### PEP8 import规范正确实现

```python
# ✓ 所有 import 在文件顶部
# 导入 IC 计算模块（支持方向验证 + 单日 IC 计算 + IC 统计指标计算）
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,  # 用于增量计算
    calculate_ic_statistics   # 用于增量路径重新计算统计指标
)

def _incremental_update(...):
    # calculate_ic_statistics 已在文件顶部导入（遵循 PEP8 import 规范）
    result = calculate_ic_statistics(ic_series)
```

### PEP8 import规范禁止行为

```python
# ❌ 函数内部 import
def _incremental_update(...):
    from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 在函数内
    result = calculate_ic_statistics(ic_series)

# ❌ 同一模块分散导入
# 文件顶部：
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification
# 函数内：
from factor_ic.common.ic_calculator import calculate_ic_statistics  # ✗ 分散导入

# 问题：
# - 违反 PEP8 规范
# - 降低可读性
# - 同一模块应统一导入
```

### 为何必须遵循 PEP8 import 规范

1. **PEP8 标准**：Python 官方代码风格指南要求所有 import 在文件顶部
2. **性能考虑**：虽然 Python 有 import 缓存机制，但函数内 import 每次调用都会执行查找
3. **可读性**：import 在顶部易于追踪模块依赖
4. **代码风格一致**：同一模块的函数应统一导入

### PEP8 import规范适用范围

此规范适用于所有 Python 代码：
1. **模块级 import**：所有 import 在文件顶部
2. **同一模块导入**：同一模块的多个函数应统一导入
3. **避免函数内 import**：除非有特殊原因（如避免循环导入）
4. **任何 Python 代码**

### PEP8 import规范检查清单

```
□ 所有 import 在文件顶部
□ 同一模块的函数统一导入
□ 避免函数内 import（除非有特殊原因）
□ 遵循 PEP8 规范
□ 提高代码可读性
```

### 未使用导入清理规范

**导入但从未使用的模块必须删除，避免死代码误导读者。**

```python
# ✓ 正确：只导入实际使用的模块
from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic,
    save_ic_result
)
from factor_ic.common.incremental_engine import UpdateMode, should_use_incremental
from factor_ic.common.data_completeness import get_ic_output_path

# ❌ 错误：导入但从未使用
from factor_ic.common.data_completeness import get_ic_output_path, check_data_completeness
# check_data_completeness 已被 should_use_incremental 替代，应删除
```

**典型场景：**

| 场景 | 旧导入 | 新导入 | 清理要求 |
|------|--------|--------|---------|
| 函数替代 | `check_data_completeness` | `should_use_incremental` | 删除旧导入 |
| 模块重构 | `from old_module import func` | `from new_module import func` | 删除旧模块导入 |
| 功能移除 | `from module import deprecated_func` | 无 | 删除整个导入 |

**为何必须清理未使用导入：**
1. 未使用导入误导读者：以为代码依赖该模块
2. 代码审计浪费时间：分析未使用导入的用途
3. 增加导入开销：Python 仍会加载未使用模块（虽有缓存机制）
4. 维护混乱：重构时误认为需要保留未使用模块

## 全量路径与增量路径防御对称规范

### 全量路径与增量路径防御对称规范核心原则

**全量路径与增量路径必须保持一致的防御机制。防御检查（如日期格式断言）不应只在某一条路径执行，两条路径都应有等效的防御。**

### 全量路径与增量路径防御对称规范问题背景

```
防御不对称问题：

旧代码（错误）：
```python
# 增量路径：有日期格式断言
def _incremental_update(...):
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范)
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")

# 全量路径：无日期格式断言
def calculate_daily_ic_series(...):
    dates = [str(d) for d in ic_series.index]  # ✗ 无格式检查
    period_start = raw_metadata['period_start']  # ✗ 无格式检查
```

问题后果：
- 增量路径检查日期格式，全量路径不检查
- 防御不对称：全量路径可能通过错误日期格式
- 如果日期格式错误（如 '2024/01/01' 或 '2024-1-1'）
- 增量路径会报错，全量路径不会报错
- 导致下游问题：JSON 序列化失败、日期比较错误
```

### 全量路径与增量路径防御对称规范正确实现

```python
# ✓ 两条路径都有日期格式断言
# 全量路径
def calculate_daily_ic_series(...):
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范）
    # 核心原则：全量路径与增量路径保持一致的防御机制
    dates_to_check = [dates[0] if len(dates) > 0 else None,
                      dates[-1] if len(dates) > 0 else None,
                      period_start, period_end]
    
    for d in dates_to_check:
        if d is not None and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")

# 增量路径
def _incremental_update(...):
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范)
    dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
    
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
```

### 全量路径与增量路径防御对称规范禁止行为

```python
# ❌ 只在一条路径有防御检查
# 增量路径：有检查
def _incremental_update(...):
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(...)

# 全量路径：无检查  # ✗ 防御不对称
def calculate_daily_ic_series(...):
    dates = [str(d) for d in ic_series.index]  # ✗ 直接使用，无检查

# ❌ 防御检查不一致
# 问题：
# - 某一条路径可能通过错误的格式
# - 增量路径报错，全量路径不报错
# - 导致下游问题
# - 维护者困惑：为什么只有一条路径报错？
```

### 为何必须保持防御对称

1. **一致性**：两条路径应有相同的防御机制
2. **可靠性**：避免某一条路径通过错误的格式
3. **可维护性**：维护者不会困惑为何只有一条路径报错
4. **避免下游问题**：错误日期格式会导致 JSON 序列化失败、日期比较错误

### 全量路径与增量路径防御对称规范适用范围

此规范适用于所有全量/增量路径：
1. **日期格式断言**：全量和增量路径都应检查
2. **数据类型校验**：全量和增量路径都应校验
3. **边界检查**：全量和增量路径都应检查
4. **任何防御性编程**

### 全量路径与增量路径防御对称规范检查清单

```
□ 全量路径和增量路径都有日期格式断言
□ 防御检查在两条路径保持一致
□ 避免只在一条路径有防御
□ 两条路径都应验证数据格式
□ 保持防御对称，避免下游问题
```

## 可选字段回退逻辑规范

### 可选字段回退逻辑规范核心原则

**可选字段的回退逻辑必须依赖必需字段（已校验）。禁止在 required_fields 中包含可选字段，这会导致回退逻辑永远不会触发（矛盾设计）。**

### 可选字段回退逻辑规范问题背景

```
回退逻辑矛盾问题：

旧代码（错误）：
```python
# required_fields 包含可选字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display',  # ✗ 矛盾
    ...
]

# 回退逻辑（永远不会触发）
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

问题后果：
- required_fields 包含 'p_value_display'
- 缺少 'p_value_display' 时校验抛出 RuntimeError
- 回退逻辑永远不会触发
- 矛盾设计：既然校验会报错，为何还有回退逻辑？

依赖问题：
- 回退逻辑使用 result['p_value'] 作为回退值
- 如果同时缺少 'p_value_display' 和 'p_value'，回退逻辑抛出 KeyError
- 虽然 required_fields 包含 'p_value'，但如果不包含 'p_value_display'...
- 回退逻辑会因缺少 'p_value' 而抛出 KeyError
```

### 可选字段回退逻辑规范正确实现

```python
# ✓ 区分必需字段和可选字段
# 核心原则：p_value 是必需字段（回退逻辑依赖），p_value_display 是可选字段（可从 p_value 计算）
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',  # p_value 必需
    'statistical_significance', 'factor_direction',
    'economic_significance', 'positive_ratio', 'summary'
]
# p_value_display 是可选字段，不校验（可从 p_value 计算回退值）

missing_fields = [f for f in required_fields if f not in result]
if missing_fields:
    raise RuntimeError(...)

# 回退逻辑（可靠依赖 p_value）
# p_value_display 回退逻辑说明（遵循 MODULE.md 可选字段回退逻辑规范）
# 核心原则：p_value_display 是可选字段，缺少时从 p_value 计算
# p_value 是必需字段（已校验），回退逻辑可靠
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
```

### 可选字段回退逻辑规范禁止行为

```python
# ❌ required_fields 包含可选字段
required_fields = [
    'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display',  # ✗ 矛盾
    ...
]

# ❌ 回退逻辑依赖未校验的字段
'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))  # ✗ p_value 未校验？

# ❌ 矛盾设计
# 问题：
# - 既然校验会报错，为何还有回退逻辑？
# - 回退逻辑永远不会触发
# - 代码维护者困惑：为何有两种处理方式？
```

### 为何必须区分必需字段和可选字段

1. **消除矛盾**：required_fields 包含可选字段是矛盾设计
2. **回退逻辑有效**：可选字段缺少时，回退逻辑才会触发
3. **依赖可靠**：回退逻辑依赖必需字段（已校验），不会抛出 KeyError
4. **代码清晰**：维护者不会困惑为何有两种处理方式

### 可选字段回退逻辑规范适用范围

此规范适用于所有有回退逻辑的可选字段：
1. **p_value_display**：可选字段，可从 p_value 计算
2. **任何有回退逻辑的字段**：必需区分必需字段和可选字段
3. **字段校验逻辑**：required_fields 只包含必需字段
4. **回退逻辑设计**：依赖必需字段（已校验）

### 可选字段回退逻辑规范检查清单

```
□ 区分必需字段和可选字段
□ required_fields 只包含必需字段
□ 可选字段不在 required_fields 中
□ 回退逻辑依赖必需字段（已校验）
□ 回退逻辑不会因缺少依赖字段而抛出 KeyError
□ 注释说明可选字段的回退逻辑
```

**典型场景：**

| 场景 | 旧实现 | 新实现 | 清理要求 |
|------|-------|-------|---------|
| 性能优化 | 循环处理单股票 | 向量化处理多股票 | 删除循环版本函数 |
| 算法重构 | 单数据点函数 | 向量化版本 | 删除单数据点函数 |
| 公共函数复用 | 本地实现 | common/ 公共函数 | 删除本地实现 |

**正确示例：**
```python
# ✓ 向量化版本替代循环版本后，删除旧函数

# 旧版本（删除）：
# def calculate_single_stock(stock_df): ...  # 已删除

# 新版本（保留）：
def calculate_all_stocks_vectorized(factor_df):
    return factor_df.groupby('asset').transform(...)
```

**禁止：**
```python
# ❌ 保留旧函数但从不调用（死代码）
def calculate_single_stock(stock_df):  # 死代码！
    """单股票版本，从未被调用"""
    return stock_df.rolling(20).mean()

def calculate_all_stocks_vectorized(factor_df):  # 实际使用
    """向量化版本"""
    return factor_df.groupby('asset').transform(...)

# calculate_single_stock 定义后从未被调用，是死代码
```

**为何必须清理死代码：**
1. 死代码误导读者：以为有两条实现路径可选
2. 死代码增加维护成本：修改逻辑时需同步多处
3. 死代码可能不一致：与新实现产生偏差
4. 代码审计浪费时间：分析死代码的用途

## 函数签名变更同步规范

**核心原则：** 返回值变更时必须同步更新类型注解和 docstring。

**正确示例：**
```python
def load_data_from_cache(...) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Returns:
        factor_df: 过滤后因子数据
        return_df: 过滤后收益数据
        raw_metadata: 原始数据范围信息（新增）
    """
```

**禁止：**
- ❌ 只改返回值不改类型注解
- ❌ 只改返回值不改 docstring

## 参数类型约定规范

**核心原则：** output_file 统一转为 Path 对象。

**正确：**
```python
def generate_rsi_ic_data(output_file=None):
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')  # 返回 Path
    else:
        output_file = Path(output_file)  # str → Path
```

**为何必须统一类型：**
- Path 对象可安全使用 .parent.mkdir()
- str 对象需要额外处理
- 统一类型避免后续代码类型判断

# 六、判断规范与引用

## 统计显著性判断规范

**五维度判断（独立输出，不合并）：**

| 维度 | 判断规则 | 输出字段 |
|------|---------|---------|
| 维度1: 统计显著性 | p < 0.05（与 |t| > 1.96 等价） | is_significant, nw_lag |
| 维度2: 因子方向 | ic_mean 符号判断 | factor_direction |
| 维度3: 经济显著性 | |ic_mean| >= 0.05 → strong; >= 0.03 → weak | economic_significance |
| 维度4: ICIR稳定性 | ICIR >= 2.0 → excellent; >= 1.0 → good | icir_stability |
| 维度5: IC分布一致性 | positive_ratio 与 ic_mean_sign 匹配 | is_consistent, consistency_type |

## IC分布一致性判断边界规范

**判断规则（含优先级）：**

| 优先级 | 条件 | 输出 |
|-------|------|------|
| 1（最高） | ic_mean_sign = 'zero' | balanced |
| 2 | 正向因子 positive_ratio >= 50% | consistent |
| 2 | 反向因子 positive_ratio <= 50% | consistent |
| 3 | positive_ratio ∈ [49%, 51%]（闭区间） | balanced |
| 4 | 其他情况 | contradictory |

**边界示例：**
- 正向因子 49% → balanced（优先级3）
- 正向因子 50% → consistent（优先级2）
- 反向因子 50% → consistent（优先级2）
- 反向因子 51% → balanced（优先级3）

## 增量模式period语义规范

**核心原则：** period.start/end 必须基于原始缓存数据（dropna 前）。

**正确：**
```python
# 在 dropna 之前，先计算原始数据范围
raw_period_start = factor_df['date'].min()
raw_period_end = factor_df['date'].max()
raw_total_days = factor_df['date'].nunique()

# 然后 dropna
factor_df = factor_df.dropna()

# 返回过滤后数据 + raw_metadata
return factor_df, return_df, {'period_start': raw_period_start, ...}
```

**为何使用原始数据：**
- dropna 可能过滤掉某些日期的全部股票
- factor_df['date'].min()/max() 计算的是过滤后的范围
- 与语义定义冲突："原始缓存范围" ≠ "过滤后数据范围"

## 引用说明

本文档定义 factor_ic/ 目录下所有 IC 计算脚本的开发规范。

**相关文档：**
- 项目级规范：PROJECT.md（目录结构、开发检查清单）
- 流程文档：factor_ic/docs/ic_<因子名>_<周期>_flow.md
- 公共函数：factor_ic/common/ 模块

*最后更新: 2026-05-19*