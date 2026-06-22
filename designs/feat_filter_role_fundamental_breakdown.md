# R3: filter 角色因子 + 基本面恶化过滤

**版本**: R3-v1
**作者**: 云瑶
**日期**: 2026-06-22
**状态**: Plan（Design-First）
**前置**: master_l1_l6_roadmap.md, R2 完成（filter 角色权重置 0 已生效）

---

## §1 What — 规范定义

把"累计跌幅 + 基本面恶化"硬过滤实现为 filter 角色因子族，
在 `stock_selector` 中作为**多头候选阶段**的硬约束（在排序之前应用），
而非在企稳过滤之后（apply_stabilization_filter）。

---

## §2 现状

| 项 | 状态 |
|---|---|
| FACTOR_ROLES 三角色枚举 | ✅ 已定义（factor_definitions.py:520） |
| filter 桶内容 | ❌ 空（factor_definitions.py:579 注释 "暂无 filter 角色因子"） |
| 累跌过滤实现 | ❌ 无 |
| stock_selector 现有过滤 | 仅 `apply_stabilization_filter`（企稳后置，不是基本面） |

---

## §3 How — 实施方案

### 3.1 第一批 filter 角色因子

**第一性原理**: filter 角色 = 已发生的客观事实（非概率信号），用经济意义阈值
（非百分位）做硬约束。第一批引入 1 个最关键的：

| 因子名 | 数据列 | 阈值 | 含义 |
|---|---|---|---|
| `cum_return_5d_breakdown` | 由 `return_5d` 派生 | `return_5d < -0.10`（-10%）| 5 日累计跌幅 >10% → 基本面恶化嫌疑 |

**第一性依据**:
- A 股 5 日累计 -10% 已触发"风险警示"经验阈值（券商风控规则）
- 中国信用周期：连续大跌时，技术反弹概率 < 基本面恶化概率（Minsky 1977）
- 不用百分位是因为"绝对跌幅"本身是经济意义边界

**为什么只引入 1 个**:
- 多 agent 协作期，引入越多 filter 风险越大
- 先观察 1 个的回归效果（fin 阶段），再决定是否扩展（return_10d, volume_dryup 等）

### 3.2 factor_definitions.py 改动

```python
# §1: 在 FACTOR_FAMILIES（如有）或紧邻新增
# §2: 在 FACTOR_ROLES 字典末尾加 filter 角色:

FACTOR_ROLES: dict[str, str] = {
    ...
    # --- 过滤器（基本面恶化, 硬过滤）---
    # 第一性原理: master_l1_l6_roadmap.md §2.3
    # 阈值依据: 5 日累计 -10% = 券商风控经验, 中国 A 股 ST 警示线邻近
    "cum_return_5d_breakdown": "filter",
}
```

**因子值定义**:
```python
# factor_definitions.py: FACTOR_DESCRIPTIONS
"cum_return_5d_breakdown": "5日累计跌幅过滤: 1=return_5d < -10% 触发过滤, 0=正常",
```

**注意**: 该"因子"不是真正的"信号"，而是过滤标记。值域 {0, 1}。
**不需要**新增 factor_generator 计算函数，因为依赖的 `return_5d` 已存在。
在 stock_selector 中**实时**从 `return_5d` 派生 `is_filter_breakdown` mask。

### 3.3 stock_selector.py 改动

#### 3.3.1 新增 `apply_filter_role_factors` 函数

**位置**: `apply_stabilization_filter`（L589）**之前** —— 因为 filter
是硬过滤，应在排序前应用，避免好不容易凑齐 top_n 又被过滤。

```python
def apply_filter_role_factors(
    candidates_df: pd.DataFrame,
    logger: logging.Logger | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """filter 角色因子硬过滤（master_l1_l6_roadmap.md §2.3）

    在排序前应用基本面恶化硬过滤. filter 角色因子被排除出候选池.

    当前阈值（v1.0, 单一过滤器）:
    - cum_return_5d_breakdown: return_5d < -0.10 → 排除

    Args:
        candidates_df: 候选股票 DataFrame（含 return_5d 等列）.
        logger: 日志对象.

    Returns:
        (filtered_df, exclusion_counts): 过滤后 DataFrame + 各过滤器排除数 dict.
    """
    if logger is None:
        logger = _logger

    exclusion_counts: dict[str, int] = {}
    df = candidates_df.copy()

    # cum_return_5d_breakdown: return_5d < -10%
    if "return_5d" in df.columns:
        breakdown_mask = df["return_5d"].notna() & (df["return_5d"] < -0.10)
        n_excluded = int(breakdown_mask.sum())
        exclusion_counts["cum_return_5d_breakdown"] = n_excluded
        if n_excluded > 0:
            df = df[~breakdown_mask].reset_index(drop=True)
            logger.info(
                "filter[cum_return_5d_breakdown]: 排除 %d 只 (return_5d < -10%%)",
                n_excluded,
            )
    else:
        logger.warning(
            "filter[cum_return_5d_breakdown]: 缺 return_5d 列, 跳过过滤"
        )
        exclusion_counts["cum_return_5d_breakdown"] = 0

    return df, exclusion_counts
```

#### 3.3.2 调用位置

在 `select_stocks` 主流程中（`sort_and_select` 之前）：

```python
# 现有: result_df = build_composite_factor(...)
# 现有: valid_mask = ...

# 新增 (R3): filter 角色硬过滤
result_df, filter_exclusions = apply_filter_role_factors(result_df, logger)
total_filter_excluded = sum(filter_exclusions.values())

# 现有: sorted_df = result_df[valid_mask].sort_values(...)
# 现有: top_stocks = sorted_df.head(top_n)

# 现有: top_stocks, excluded_by_confirmation = apply_stabilization_filter(...)
```

#### 3.3.3 meta 字段

`stock_selection_result.json` 的 meta 加：
```json
{
  "meta": {
    ...
    "excluded_by_filter_role": {
      "cum_return_5d_breakdown": 12
    }
  }
}
```

### 3.4 测试

新增 `comprehensive_factor/test_cases/test_filter_role.py`:

```python
def test_breakdown_excluded():
    """return_5d=-12% 的股票被排除"""

def test_breakdown_kept_at_threshold():
    """return_5d=-10% 等于阈值 → 不排除（严格 <）"""

def test_missing_column_skipped():
    """无 return_5d 列 → 跳过过滤 + warning, 不报错"""

def test_nan_return_5d_kept():
    """return_5d=NaN → 不排除（无法判断）"""

def test_exclusion_count_logged():
    """log 含 '排除 N 只' 消息"""

def test_integration_with_stabilization():
    """filter -> sort -> stabilization 三段链路顺序正确"""
```

### 3.5 PROJECT.md / MODULE.md 同步

**comprehensive_factor/MODULE.md**: 新增章节"§ 角色过滤链路":

```markdown
## 角色过滤链路（v2.41, R3 新增）

stock_selector 过滤顺序（硬→软）:
1. is_untradeable=1 (factor_loader 加载层)
2. is_low_liquidity=1 (factor_loader 加载层, R1)
3. filter 角色因子 (apply_filter_role_factors, R3)
4. 综合因子计算 + 排序
5. apply_stabilization_filter (企稳确认)
```

**factor_definitions.py 顶部 docstring**: 同步 filter 角色定义。

---

## §4 Don't — 禁止事项

| ❌ | 原因 |
|---|---|
| 把 filter 因子放进 composite 加权（weight > 0） | filter = 硬约束, 不是连续信号 |
| 用百分位阈值（如 P10） | filter 是经济意义边界, 不是相对排名 |
| 在 apply_stabilization_filter 之后做 | 排序后再过滤会破坏 top_n 凑齐逻辑 |
| 第一版引入多个 filter 因子 | 增量验证, 1 个验完再扩展 |
| 让 filter 因子需 factor_generator 计算 | return_5d 已存在, 派生即可 |
| 跳过 r2 完成就做 r3 | R2 让 filter 权重置 0, R3 才能让"角色"完整对应过滤行为 |

---

## §5 Why — 设计理由

### 5.1 为什么是排序前过滤

如果在 apply_stabilization_filter（排序后）做基本面过滤，会出现：
- 综合因子 Top10 选中一只 -12% 阴跌股 → 基本面过滤排除 → 从 Top11/Top12 递补
- 递补股票可能也是 -8%/-9% 的弱势股
- → 没有从根上消除阴跌候选池

排序前过滤直接砍掉基本面差的股票，剩下的 valid 候选池本身就健康。

### 5.2 为什么阈值是 -10%

- 中国 A 股单日跌幅上限 10%（个股，2020 前）/20%（科创板/创业板）
- 5 日累计 -10% ≈ "无可挽回的下行趋势" 经验阈值
- 券商两融业务"风险等级"调整线（实务经验）

### 5.3 与 R1 流动性过滤的区别

| 维度 | R1 流动性 | R3 基本面 |
|---|---|---|
| 时机 | factor_generator（数据层） | stock_selector（选股层） |
| 阈值 | 截面 P5（自适应） | -10%（绝对值） |
| 影响范围 | 所有下游模块 IC/分层/权重 | 仅最终选股 |
| 失效场景 | 数据缺 volume/close | 数据缺 return_5d |

不冲突，各司其职。

---

## §6 When — 适用场景

**默认启用**: 所有 stock_selection 流程。
**临时禁用**: `stock_selector --disable-filter-role`（ablation 实验或紧急回退）。

---

## §7 Verify — 验证方法

```bash
# 1. 单元测试
pytest comprehensive_factor/test_cases/test_filter_role.py -v

# 2. 选股回归（fin 阶段）
python comprehensive_factor/stock_selector.py
cat comprehensive_factor/result/stock_selection_result.json | python -m json.tool | grep -A5 excluded_by_filter_role
# 期望: cum_return_5d_breakdown > 0 (如 10-30 只)

# 3. 阴跌股核查
# 期望: 002570 (return_5d ≈ -8%) 仍在候选 (未到 -10% 阈值)
#       600439 (return_5d ≈ -14%) 被排除
```

---

## §8 实施批次拆分（H9 ≤3 文件 ≤200 行）

| 批 | 文件 | 行数 |
|---|---|---|
| r3a | `factor_definitions.py` + `comprehensive_factor/MODULE.md` | ~30 |
| r3b | `comprehensive_factor/stock_selector.py` + `comprehensive_factor/test_cases/test_filter_role.py` | ~120 |

---

## §9 后续扩展（不在本次范围）

R3 v1.0 仅引入 1 个 filter 因子。后续可考虑：

- `cum_return_10d_breakdown`: 10 日累跌 > 15%
- `volume_dryup`: 5 日 amount 中位数 < 1000 万（基本面流动性枯竭）
- `industry_breakdown`: 所属行业 10 日跌幅 > 8%（行业风险传染）

每个扩展独立 design.md + commit，不批量上线。

---

## §10 回滚预案

```bash
# 完全回滚
git revert <r3a_sha> <r3b_sha>

# 临时禁用
python comprehensive_factor/stock_selector.py --disable-filter-role
```
