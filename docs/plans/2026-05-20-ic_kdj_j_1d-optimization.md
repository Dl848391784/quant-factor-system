# ic_kdj_j_1d.py 优化实现计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将 ic_kdj_j_1d.py 优化为符合 MODULE.md 规范的标准实现（参考 ic_rsi_1d.py）

**Architecture:** 采用分步执行策略（每次一个小 patch），修复 10 个规范问题，参考 factor-script-optimization-checklist.md

**Tech Stack:** Python 3.x, pandas, numpy, gzip, json

---

## 问题诊断汇总

| 序号 | 问题类型 | 问题描述 | 修复策略 |
|------|---------|---------|---------|
| 1 | 代码Bug | 异常处理类型错误（第467-468行） | 分层捕获，ValueError直接raise |
| 2 | 代码Bug | total_days计算错误（第396-397行） | 使用raw_metadata['total_days'] |
| 3 | 规范遗漏 | calculate_daily_ic_series函数签名不一致 | 添加raw_metadata和min_stocks参数 |
| 4 | 代码Bug | 打印信息字段访问错误（第484行） | 修正访问路径 |
| 5 | 规范遗漏 | DEFAULT_MIN_STOCKS常量缺失 | 添加常量定义 |
| 6 | 规范遗漏 | 日期类型转换缺失 | 添加pd.to_datetime转换 |
| 7 | 规范遗漏 | 输入验证缺失友好错误信息 | 添加可用列列表 |
| 8 | 规范遗漏 | rolling_ic_mean NaN未转为None | 添加NaN处理 |
| 9 | 规范遗漏 | 防御性校验缺失（required_fields、排序） | 添加校验逻辑 |
| 10 | 规范遗漏 | 流程文档缺失 | 创建ic_kdj_j_1d_flow.md |

---

## Task 1: 添加 DEFAULT_MIN_STOCKS 常量

**Objective:** 定义默认最小股票数常量，统一参数管理

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:37`（import区域后）

**Step 1: 在 import 后添加常量定义**

```python
# ============================================================================
# 参数统一管理（遵循 PROJECT.md 参数传递规范）
# ============================================================================
# 默认最小股票数：用于 IC 计算（单日股票数不足时返回 None）
# 注意：修改此值会影响所有 IC 计算逻辑，需同步更新相关注释
DEFAULT_MIN_STOCKS = 10
```

**Step 2: 修改 calculate_daily_ic_series 函数签名**

将第317-322行的函数签名改为：
```python
def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    raw_metadata: dict = None,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
```

**Step 3: 修改函数内部 min_stocks 传递**

将第343行的硬编码改为参数传递：
```python
result = calculate_ic_with_direction_verification(
    factor_df=factor_df,
    return_df=return_df,
    factor_col='kdj_j',
    return_col='forward_return',
    date_col='date',
    asset_col='asset',
    min_stocks=min_stocks  # 使用函数参数，遵循 PROJECT.md 参数传递规范
)
```

**Verification:**
- 检查常量定义位置正确
- 函数签名与 ic_rsi_1d.py 一致
- 无硬编码 min_stocks 值

---

## Task 2: 修复异常处理类型

**Objective:** 分层捕获异常，ValueError直接raise，不包装为RuntimeError

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:457-468`

**Step 1: 修改异常处理逻辑**

将第457-468行的异常处理改为：
```python
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache(n=n, m1=m1, m2=m2)
        
        # 检查数据量（遵循 PROJECT.md 数据验证规范）
        if factor_df['asset'].nunique() < DEFAULT_MIN_STOCKS:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\\n"
                f"当前: {factor_df['asset'].nunique()} < {DEFAULT_MIN_STOCKS}"
            )
        
    except FileNotFoundError as e:
        # 基础设施错误：可包装为 RuntimeError
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    except KeyError as e:
        # 数据验证错误：直接 raise，保留原始类型
        raise  # 不包装，遵循 PROJECT.md 异常处理类型保留规范
    except ValueError as e:
        # 数据验证错误：直接 raise，保留原始类型
        raise  # 不包装，遵循 PROJECT.md 异常处理类型保留规范
    except Exception as e:
        # 未预期异常：包装为 RuntimeError，保留异常链
        raise RuntimeError(
            f"数据加载失败（未预期异常）\\n"
            f"异常类型: {type(e).__name__}\\n"
            f"错误详情: {e}"
        ) from e
```

**Verification:**
- ValueError不再被包装为RuntimeError
- FileNotFoundError可包装
- 异常链保留（使用from e）

---

## Task 3: 添加日期类型转换

**Objective:** 统一日期格式为YYYY-MM-DD字符串，处理无效日期

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:264-286`（load_data_from_cache函数）

**Step 1: 在第264行后添加日期转换**

在 `factor_df = pd.DataFrame(factor_data['data'])` 后添加：
```python
    # 日期类型统一转换（遵循 PROJECT.md 日期类型一致性规范）
    # 从 JSON 加载后，日期可能是多种格式（字符串、datetime、timestamp）
    # 统一转换为字符串格式 "YYYY-MM-DD"，确保 isin 操作类型匹配
    # 使用 errors='coerce' 处理异常格式，转换后检查 NaT 数量
    
    if 'date' in factor_df.columns:
        date_series = pd.to_datetime(factor_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
            invalid_samples = factor_df['date'][date_series.isna()].head(5).tolist()
            raise ValueError(
                f"因子数据中存在 {nat_count} 个无效日期格式\\n"
                f"无效日期示例: {invalid_samples}\\n"
                f"请检查缓存数据源是否包含脏数据"
            )
        factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
    
    if 'date' in return_df.columns:
        date_series = pd.to_datetime(return_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
            invalid_samples = return_df['date'][date_series.isna()].head(5).tolist()
            raise ValueError(
                f"收益数据中存在 {nat_count} 个无效日期格式\\n"
                f"无效日期示例: {invalid_samples}\\n"
                f"请检查缓存数据源是否包含脏数据"
            )
        return_df['date'] = date_series.dt.strftime('%Y-%m-%d')
```

**Verification:**
- 日期统一为YYYY-MM-DD字符串格式
- 无效日期抛出ValueError（含样本示例）
- 与ic_rsi_1d.py实现一致

---

## Task 4: 修复 total_days 计算

**Objective:** 使用raw_metadata['total_days']，而非len(dates)

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:395-399`

**Step 1: 修改 calculate_daily_ic_series 函数内部逻辑**

在第317行函数内，修改第349-353行的日期范围获取：
```python
    # 获取日期范围（遵循 PROJECT.md period 数据源规范）
    # 使用 raw_metadata 中的原始数据范围，而非过滤后的 factor_df
    if raw_metadata is None:
        raw_metadata = {}
    period_start = raw_metadata.get('period_start', str(factor_df['date'].min()))
    period_end = raw_metadata.get('period_end', str(factor_df['date'].max()))
    total_days = raw_metadata.get('total_days', factor_df['date'].nunique())
```

**Step 2: 修改 sample_stats 结构**

将第395-399行的 sample_stats 改为：
```python
        'sample_stats': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - total_days: 原始因子缓存覆盖的日期数（dropna 前的数据范围）
            # - valid_days: 实际计算出 IC 的天数（每交易日股票数 >= min_stocks）
            # - 差值含义: total_days - valid_days = 因股票不足或数据缺失跳过的交易日数
            'total_days': total_days,  # 使用 raw_metadata
            'valid_days': len(dates),  # dates 来自 ic_series.index（有效IC日期）
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean())
        },
```

**Verification:**
- total_days使用raw_metadata而非len(dates)
- valid_days正确为len(dates)
- 语义注释清晰

---

## Task 5: 修复 rolling_ic_mean NaN处理

**Objective:** NaN值转为None，而非nan float

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:359-361`

**Step 1: 修改 rolling_ic_mean 计算**

将第359-361行改为：
```python
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    
    # 遵循 PROJECT.md NaN 处理规范：在数据生成阶段将 NaN 转为 None
    # 原因：rolling 前 9 天不满 min_periods=10，返回 NaN
    #       round(NaN, 6) 返回 Python float nan，而非 None
    rolling_ic_mean = [
        round(v, 6) if not pd.isna(v) else None
        for v in rolling_mean.values
    ]
```

**Verification:**
- NaN转为None而非nan float
- 注释说明原因
- 与ic_rsi_1d.py一致

---

## Task 6: 修复打印信息字段访问

**Objective:** 修正t_stat和significance的访问路径

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:484`

**Step 1: 修改第484行的字段访问**

将：
```python
print(f"  - t 统计量: {ic_data['t_stat']:.2f} {ic_data['significance']}")
```

改为：
```python
    t_stat = ic_data['statistical_significance']['t_stat']
    is_sig = ic_data['statistical_significance']['is_significant']
    sig_display = "显著" if is_sig else "不显著"
    print(f"  - t 统计量: {t_stat:.2f} ({sig_display})")
```

**Verification:**
- 字段访问路径正确（statistical_significance子对象）
- 无KeyError风险
- 显示格式清晰

---

## Task 7: 添加输入验证友好错误

**Objective:** 列不存在时显示可用列列表

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:278-296`

**Step 1: 在选择列前添加验证**

在第277-279行后添加：
```python
    # 输入验证（遵循 PROJECT.md 输入验证规范）
    # KDJ_J 必须有 close, high, low 列
    
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        available_cols = sorted(factor_df.columns.tolist())
        raise KeyError(
            f"因子数据缺少必需列: {missing_cols}\\n"
            f"可用列: {available_cols}"
        )
```

在第292-296行的收益列检查中添加可用列表：
```python
    # 验证收益列存在（遵循 PROJECT.md 输入验证规范）
    if 'forward_return_1d' not in return_df.columns:
        available_cols = sorted(return_df.columns.tolist())
        raise KeyError(
            f"收益列 'forward_return_1d' 不存在于缓存数据中\\n"
            f"可用列: {available_cols}"
        )
    
    return_df = return_df[['date', 'asset', 'forward_return_1d']].copy()
    return_df = return_df.rename(columns={'forward_return_1d': 'forward_return'})
```

**Verification:**
- 缺列时显示可用列列表
- KeyError而非简单print
- 与ic_rsi_1d.py一致

---

## Task 8: 添加防御性校验

**Objective:** 添加required_fields检查和dates排序校验

**Files:**
- Modify: `/home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py:336-362`

**Step 1: 在第346行后添加required_fields校验**

```python
    ic_series = result['ic_series']
    
    # 防御性校验：确保 result 包含必需字段
    # 遵循 PROJECT.md 函数返回值契约规范
    required_fields = [
        'ic_series', 'ic_mean', 'ic_std', 'icir',
        'statistical_significance', 'factor_direction',
        'economic_significance', 'icir_stability',
        'ic_distribution_consistency', 'positive_ratio', 'summary'
    ]
    missing_fields = [f for f in required_fields if f not in result]
    if missing_fields:
        raise RuntimeError(
            f"calculate_ic_with_direction_verification 返回值缺少必需字段\\n"
            f"缺失字段: {missing_fields}\\n"
            f"问题定位: factor_ic/common/ic_calculator.py\\n"
            f"期望字段: {required_fields}"
        )
```

**Step 2: 在第361行后添加dates排序校验**

```python
    # 防御性校验：确保 dates 按升序排列
    # 遵循 PROJECT.md 规范：ic_series.index 必须按日期排序
    # 原因：rolling 计算按位置顺序，若 dates 乱序会导致 dates[i] 与 rolling_ic_mean[i] 对应错误
    if dates != sorted(dates):
        raise RuntimeError(
            f"dates 未按升序排列，可能导致 dates 与 rolling_ic_mean 对应错误\\n"
            f"dates 前5个: {dates[:5]}\\n"
            f"sorted 前5个: {sorted(dates)[:5]}"
        )
```

**Verification:**
- required_fields检查完整
- dates排序校验存在
- RuntimeError含诊断信息

---

## Task 9: 运行脚本验证输出

**Objective:** 运行脚本检查实际输出，验证修复效果

**Files:**
- Run: `python /home/admin/projects/factor_ic_analyzer/factor_ic/ic_kdj_j_1d.py`

**Step 1: 运行脚本**
```bash
cd /home/admin/projects/factor_ic_analyzer
python factor_ic/ic_kdj_j_1d.py
```

**Step 2: 检查输出数据结构**

读取输出的JSON文件，验证：
```bash
cat factor_ic/result/ic_kdj_j_1d_analysis_result.json | head -50
```

**Expected output:**
- total_days != valid_days（有差距）
- rolling_ic_mean 前9个为null
- statistical_significance字段完整
- 无KeyError或RuntimeError

**Verification:**
- 脚本运行成功无异常
- 输出数据结构符合MODULE.md规范
- 字段值正确（total_days > valid_days）

---

## Task 10: 创建流程文档

**Objective:** 创建 ic_kdj_j_1d_flow.md 流程文档

**Files:**
- Create: `/home/admin/projects/factor_ic_analyzer/factor_ic/docs/ic_kdj_j_1d_flow.md`

**Step 1: 创建流程文档框架**

参考 ic_rsi_1d_flow.md 的结构，创建包含：
- 数据流向图
- 函数调用关系
- 输出字段说明
- 示例数据（使用实际运行结果）
- 时间标注

**Step 2: 同步时间标注**

文档头部包含：
```markdown
> 生成时间: 2026-05-20 XX:XX 北京时间
> 实测数据时间: 2026-05-20 XX:XX 北京时间
> 版本: v1.0
```

**Verification:**
- 流程文档存在
- 数据流向图清晰
- 输出字段与实际一致
- 时间标注完整

---

## Task 11: Git提交

**Objective:** 提交所有修改到git

**Files:**
- Commit: ic_kdj_j_1d.py + ic_kdj_j_1d_flow.md

**Step 1: 提交代码修改**
```bash
cd /home/admin/projects/factor_ic_analyzer
git add factor_ic/ic_kdj_j_1d.py
git commit -m "refactor(ic_kdj_j_1d): 修复10个规范问题，对齐ic_rsi_1d实现"
```

**Step 2: 提交流程文档**
```bash
git add factor_ic/docs/ic_kdj_j_1d_flow.md
git commit -m "docs(ic_kdj_j_1d): 创建流程文档，记录数据流向和输出结构"
```

**Verification:**
- git log显示提交记录
- 提交信息清晰描述修改内容

---

## 验收标准

完成后检查：
```
□ DEFAULT_MIN_STOCKS 常量存在
□ calculate_daily_ic_series 函数签名与 ic_rsi_1d.py 一致
□ 异常处理分层（ValueError直接raise）
□ 日期类型转换存在
□ total_days 使用 raw_metadata['total_days']
□ rolling_ic_mean NaN转为None
□ 打印字段访问路径正确
□ 输入验证显示可用列列表
□ 防御性校验完整（required_fields、排序）
□ 流程文档存在
□ 脚本运行成功无异常
□ 输出数据结构符合规范
□ Git提交完成
```

---

**Plan complete. Ready to execute using subagent-driven-development.**