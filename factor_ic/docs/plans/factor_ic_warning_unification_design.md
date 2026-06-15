# Factor IC 异常告警统一设计文档（轮 2）

**状态**: 起草中（轮 2B 完成 §1）
**提案人**: 云瑶
**关联**:
- 轮 2A 决策文档: `factor_ic/docs/plans/factor_ic_warning_decision.md`（commit `ccf2bdc`）
- 轮 1 启动日志去重: `factor_ic/docs/plans/factor_ic_startup_log_dedup_design.md`（commit `479e225`）
- MODULE.md M3（logger 传递）/ M19（异常处理双分支差异化）

---

## §1 背景

### 1.1 问题来源

`factor_ic/ic_amplitude_delta_1d.py` 代码审查（问题 4）原始诉求：

> `ic_std is None` 与 `icir is None` 两条 `logger.warning` 文案语义近似（均建议"检查因子数据分布"），无法帮助运维区分**是标准差本身为空**还是 **ICIR 计算失败**导致的差异，应将 ICIR 文案改为"ICIR 无法计算，请确认有效天数是否充足或标准差是否为零"以明确区分根因。

### 1.2 跨脚本现状

`grep "ICIR 无法计算" factor_ic/ic_*.py` 命中 **17 个入口脚本**，每脚本含一段近似的 4 条 `warning` block：

```python
# 异常状态告警（运维巡检用，四字段均需告警）
if ic_mean is None:
    logger.warning("本次计算 IC 均值为空，请检查数据源")
if ic_std is None:
    logger.warning("IC 标准差无法计算，请检查因子数据分布")
if icir is None:
    logger.warning("ICIR 无法计算，请检查因子数据分布")
if positive_ratio is None:
    logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")
```

——共 **17 × 4 = 68 处**重复 warning 字面量（参见 `ic_amplitude_delta_1d.py:113-121`）。

### 1.3 关键证据：四字段 None 状态强绑定

**证据 1**：错误兜底路径四字段一并 None（`common/ic_result_builder.py:254`）：

```python
"ic_metrics": {"ic_mean": None, "ic_std": None, "icir": None,
               "p_value": None, "p_value_display": "N/A"},
```

**证据 2**：正常路径将 `ic_metrics` JSON 字段填入数值（不会写入 None）（`common/ic_result_builder.py:101-107`）：

```python
ic_metrics = {
    "ic_mean": round(float(ic_mean), 6),
    "ic_std":  round(float(ic_std), 6),
    "icir":    round(float(icir), 4),
    ...
}
```

`round(float(NaN), 6)` 仍为 NaN（不是 None）；`icir = abs(ic_mean) / ic_std if ic_std > 0 else 0`（`ic_calculator.py:723`）零分母时 fallback 为 `0` 而非 None。

**证据 2 补充**：17 入口脚本通过 `ic_metrics.get("ic_mean")` 等 `.get()` 取值（`ic_amplitude_delta_1d.py:80-89`），仅当 `build_error_result` 触发后这 4 个字段才会同时为 `None`——再次印证四字段 None 强绑定。

**结论**：`ic_std is None` 与 `icir is None` 永远**同时**为真（来自 `build_error_result`），永远**同时**为假（来自正常路径）。原始诉求"区分根因文案"在当前代码路径下**无意义**。

### 1.4 Q3 grep 调查（外部依赖清洁性）

执行命令：
```bash
grep -rEn "ICIR 无法计算|IC 标准差无法计算|IC>0 占比无法|IC 均值为空|无法获取，请检查公共模块" \
     backtest/ summary/ comprehensive_factor/ data_fetchers/
grep -rEn "WARNING.*ICIR|WARNING.*IC 标准|grep.*ICIR" \
     --include="*.py" --include="*.sh" --include="*.yaml" --include="*.yml" .
```

两条命令均**无命中**——下游模块及全仓未通过文案匹配监控这 4 条 warning，方案变更无外部依赖阻塞。

### 1.5 本轮要解决的问题

| 维度 | 现状痛点 |
|------|---------|
| **代码冗余** | 17 脚本 × 4 行 = 68 处字面量重复 |
| **架构归属** | 异常告警本应由公共模块（数据完整性兜底位置）打，而非 17 入口脚本各自打 |
| **文案改名扩散成本** | 任何文案优化（如 ICIR 文案细化）必须 17 处同步修改 |
| **轮 2A 推翻原假设** | 四字段 None 强绑定，4 条 warning 实际只反映 1 个根因（`build_error_result` 触发），逻辑应合并为单条告警 |

### 1.6 与轮 1 的关系

轮 1（启动日志去重）已选定方案 ④：**公共模块 `factor_ic_runner.run_factor_ic_analysis` 集中收口启动横幅**，34 入口脚本通过 `extra_log_params` 注入扩展参数。

本轮（异常告警）拟采用**同一架构思想**：把 4 条 warning 收口到公共模块（具体收口位置在 §3 接口设计中确定），17 入口脚本只删除本地 warning block，不引入新参数——比轮 1 更简单。

两轮可在执行阶段**合并 PR**（同改 `factor_ic/common/`，同范围 17–34 入口脚本，CI 跑一次即可）。

---

## §2 目标

### 2.1 总体目标

**消除 17 入口脚本中重复的 4 条 None 状态告警字面量，将异常告警职责收口到公共模块单点维护，使运维巡检告警精准对应"build_error_result 触发"的真实根因。**

### 2.2 量化指标

| 维度 | 当前状态 | 目标状态 | 验证方法 |
|------|---------|---------|---------|
| 重复告警字面量数量 | 17 脚本 × 4 行 = **68 处** | **0 处**（17 脚本各自删除本地 warning block） | `grep -c "ICIR 无法计算" factor_ic/ic_*.py` 期望 0 |
| 告警字面量定义位置 | 17 入口脚本分散 | **公共模块单点**（≤ 1 处） | `grep -rln "ICIR 无法计算\|IC 均值为空\|IC 标准差无法计算\|IC>0 占比无法" factor_ic/` 期望 1 文件 |
| 入口脚本本地 warning 行数 | 平均每脚本 ~9 行（4 条 if + 注释） | 0 行（删除整个 block，含上方注释行 `# 异常状态告警...`） | 净减少 ≈ 17 × 9 = **153 行** |
| 覆盖入口脚本数 | 17 / 34 入口脚本含此 block | 17 / 34 全部完成迁移 | 见 §4 影响范围清单 |
| 运维侧告警条数（错误路径） | 单次 `build_error_result` 触发 4 条 warning | 单次触发 1 条整合告警 | 手动构造 fixture 跑一次 |
| 运维侧告警条数（正常路径） | 0 条（None 不会发生） | 0 条（行为不变） | 现有 4 passed 测试用例不退化 |

### 2.3 行为契约（关键不变量）

迁移前后必须保持**完全一致**的对外可观测行为：

1. **不引入新告警通道**——继续使用 `logger.warning(...)`，不改用 `logger.error` 或 `raise`，不影响退出码
2. **不改变正常路径输出**——正常计算（`ic_mean/ic_std/icir/positive_ratio` 均为有效数值）零 warning，与现状一致
3. **不改变 IC 摘要日志**——`logger.info("\n%s", "\n".join(summary_lines))`（`ic_amplitude_delta_1d.py:111`，目前在每入口脚本本地实现）保留运维侧 5 行 `--- IC指标 ---` 摘要（迁移后是否随 §3 接口选型一并收口由 §3 决定，但摘要内容与触发时机不变）
4. **告警时机不变**——告警发生在 summary_lines 输出之后（`logger.info("\n%s", ...)` 紧邻位置），不提前到 `_calc_ic_metrics` 或推迟到 `__main__`
5. **告警内容信息密度不下降**——整合后的单条告警必须同时包含：因子名称、异常字段清单（`ic_mean/ic_std/icir/positive_ratio` 哪个为 None）、运维提示（"数据加载可能失败，请查看上方 ERROR 日志或检查 build_error_result 触发条件"）

### 2.4 非目标（明确划出）

| 非目标 | 理由 |
|--------|------|
| ❌ 拆分 ic_std 与 icir 文案细化（原始问题 4 诉求） | 轮 2A 已证明四字段 None 强绑定，区分文案无信号增益 |
| ❌ 改造 `build_error_result` 使其填充 NaN 而非 None | 涉及下游 JSON Schema 字段类型契约（17 脚本 + backtest/summary 消费方），属于**单独项目**，本轮不动 |
| ❌ 新增 NaN 状态告警（区分 None vs NaN） | 当前 `round(float(NaN), 6)` 路径在工程实践中不可达（已被前置 `dropna` 拦截），增告警等于增噪音 |
| ❌ 把告警升级为异常 `raise FactorCalcError` | 违反 MODULE.md M19——异常用于"业务流程必须中断"，告警用于"流程继续但需运维关注"，本场景显然属后者 |
| ❌ 改写 `_format_ic_performance` 等摘要构建函数 | 与告警职责无关，避免范围蔓延 |

### 2.5 验收标准

本轮设计文档**实施完成**的判定条件（用于轮 2H §11 更新记录）：

- [ ] 17 入口脚本本地 4 条 warning block 全部删除
- [ ] 公共模块新增 1 处集中告警（位置见 §3）
- [ ] `pytest factor_ic/test_cases/` 全绿（不退化）
- [ ] `ruff check factor_ic/` 全绿
- [ ] `grep -c "ICIR 无法计算" factor_ic/ic_*.py` = 0
- [ ] 手动构造 `build_error_result` 触发场景，确认告警日志输出 1 条且内容包含上述运维提示
- [ ] MODULE.md 增补 M3.x 子规范（公共模块告警归属）

---

## §3 接口设计

### 3.1 选型决策（方案 b：抽整段 summary 流程）

**轮 2D 调研数据**：

| 指标 | 数值 |
|------|------|
| 含 `summary_lines = [...]` 入口脚本 | 33 个（ic_*.py 共 34 个，仅 1 个用其他摘要形式） |
| 其中含 4 条 None warning block | 17 个（轮 2 原范围） |
| 其中**无** warning block 但有 summary_lines | **16 个**（同样可受益于公共化） |
| 17 含 warning 脚本 summary_lines 前 13 行 md5 一致性 | **16/17 一致**，1 例外 |

**例外脚本**：`ic_past_return_1d_1d.py:124` 在 summary_lines 中多打一行 `因子方向: {factor_direction}`（业务真实差异——首个引入因子方向显示的脚本）。

**结论**：选 **方案 b**——抽整段 summary 流程（含告警）到公共函数，支持可选扩展字段以容纳例外。复用基础好（16/17 一致）、独立可上线（不依赖轮 1）、净减 ~990 行（33 × ~30）。

### 3.2 公共函数签名

新建文件：`factor_ic/common/factor_summary_logger.py`（独立小模块，避免膨胀 `ic_result_builder.py`）

```python
"""
因子 IC 计算结果摘要日志工具。

职责：
  1. 输出标准 IC 摘要（5 行 --- IC指标 ---）
  2. 输出 None 状态告警（单条整合，运维巡检用）
  3. 支持入口脚本注入可选扩展字段（如"因子方向"）

设计参考：MODULE.md M3.x（公共模块告警归属）。
"""

from __future__ import annotations

import logging


def log_factor_summary(
    result: dict,
    factor_display_name: str,
    logger: logging.Logger,
    *,
    extra_summary_lines: list[str] | None = None,
) -> None:
    """
    打印因子 IC 计算结果摘要 + None 状态整合告警。

    Args:
        result: ``run_complex_factor_ic`` / ``run_factor_ic_analysis`` 返回值，
                必须包含 factor_name / update_mode / period / sample_stats /
                ic_metrics / ic_distribution_consistency 字段
                （build_error_result 兜底场景下 4 字段为 None，函数会自动识别并打告警）
        factor_display_name: 因子中文显示名（如 "振幅差分因子"），仅用于告警消息
        logger: 入口脚本传入的 logger（遵循 MODULE.md M3 logger 传递规范）
        extra_summary_lines: 可选附加摘要行，按顺序追加到 IC 指标摘要末尾
                             （例：``["因子方向: positive"]``）

    Returns:
        None。本函数只输出日志，不返回值，不抛异常。

    行为契约（与 §2.3 一致）：
        - 正常路径（4 字段均为数值）：仅输出 1 条 INFO 摘要
        - 错误路径（build_error_result 触发）：输出 1 条 INFO 摘要（字段显示 N/A）
                                              + 1 条 WARNING 整合告警
        - 不抛异常、不调用 sys.exit、不影响调用方控制流
    """
```

### 3.3 函数实现要点

```python
def log_factor_summary(...) -> None:
    # ----- (1) 提取 ic_metrics / sample_stats / period / ic_distribution -----
    # 沿用入口脚本现有 .get() + or {} 防御模式
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    # ----- (2) 字段格式化（None → "N/A"，与现状完全一致）-----
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    # ----- (3) 构建 summary_lines（搬自入口脚本 line 97-110，文案完全一致）-----
    summary_lines = [
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    # 追加扩展行（容纳 ic_past_return_1d_1d.py 的"因子方向"等）
    if extra_summary_lines:
        summary_lines.extend(extra_summary_lines)

    logger.info("\n%s", "\n".join(summary_lines))

    # ----- (4) None 状态整合告警（替代原 4 条 warning）-----
    none_fields = [
        name
        for name, value in (
            ("ic_mean", ic_mean),
            ("ic_std", ic_std),
            ("icir", icir),
            ("positive_ratio", positive_ratio),
        )
        if value is None
    ]
    if none_fields:
        # 单条整合告警，符合 §2.3 第 5 条信息密度契约
        logger.warning(
            "%s IC 指标异常字段: %s（数据加载可能失败，请检查上方 ERROR 日志或 build_error_result 触发条件）",
            factor_display_name,
            ", ".join(none_fields),
        )
```

### 3.4 入口脚本调用方式

迁移前（17 脚本通用形式，参考 `ic_amplitude_delta_1d.py:80-121`，约 30 行）：

```python
ic_metrics = result.get("ic_metrics") or {}
sample_stats = result.get("sample_stats") or {}
# ... 字段提取、格式化、summary_lines 构建、logger.info ...
# 异常状态告警（运维巡检用，四字段均需告警）
if ic_mean is None:
    logger.warning("本次计算 IC 均值为空，请检查数据源")
if ic_std is None:
    logger.warning("IC 标准差无法计算，请检查因子数据分布")
if icir is None:
    logger.warning("ICIR 无法计算，请检查因子数据分布")
if positive_ratio is None:
    logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")
```

迁移后（17 脚本统一为 1 行调用）：

```python
from factor_ic.common.factor_summary_logger import log_factor_summary

log_factor_summary(result, "振幅差分因子", logger)
```

例外脚本 `ic_past_return_1d_1d.py` 调用形式：

```python
factor_direction = result.get("factor_direction", "unknown")
log_factor_summary(
    result,
    "过去 1 日收益因子",
    logger,
    extra_summary_lines=[f"因子方向: {factor_direction}"],
)
```

### 3.5 接口稳定性约束

- **`extra_summary_lines` 仅扩展，不替换**：保证基础 5 行 IC 指标始终输出，未来新增可选字段也通过追加列表实现
- **`factor_display_name` 必传**：避免告警消息缺失因子身份导致运维定位困难
- **不接受 `factor_name` 单独参数**：从 `result["factor_name"]` 自动提取，避免与 `factor_display_name`（运维侧中文名）混淆
- **不返回值**：明确"日志输出"语义，不让调用方误用为状态查询接口
- **import 路径稳定**：`factor_ic.common.factor_summary_logger.log_factor_summary`，未来若并入 `ic_result_builder.py` 需保留 re-export

### 3.6 不选公共模块内部直接打的理由

**候选方案**：在 `build_ic_result` / `build_error_result` 内部调用 `logger.warning(...)`。

**否决理由**：
1. **职责越界**——`build_*_result` 是**纯结构构建函数**（输入 → JSON 字典），加日志副作用违反单一职责
2. **logger 注入复杂**——`build_error_result` 当前未接受 logger 参数，加参等于改公共模块所有调用点
3. **告警文案需要中文因子名**——`build_*_result` 只有 `factor_name`（英文 ID），无法生成"振幅差分因子 IC 指标异常字段..."这种运维友好消息
4. **测试隔离**——纯函数易测，加日志后测试需 caplog fixture，复杂化测试代码

故公共函数 `log_factor_summary` 与 `build_*_result` 解耦，由入口脚本在拿到 result 后调用。

---

## §4 影响范围

### 4.1 新增文件

| 路径 | 类型 | 行数预估 | 说明 |
|------|------|---------|------|
| `factor_ic/common/factor_summary_logger.py` | 新文件 | ~70 行（含 docstring） | 公共模块，提供 `log_factor_summary()` |
| `factor_ic/test_cases/test_factor_summary_logger.py` | 新文件 | ~120 行 | 单元测试（正常路径 / 错误路径 / 扩展行 / caplog） |

### 4.2 修改的入口脚本（17 个）

下表为方案 b 覆盖的 17 入口脚本精确改动范围。**改动行号**指当前需要替换为单行 `log_factor_summary(...)` 调用的代码 block 起止（含 `ic_metrics = result.get(...)` 至最后一条 `logger.warning(...)`）。

| # | 路径 | 改动行号 | 净减行数 | 文件总行数（迁移前 → 迁移后） | 中文显示名（factor_display_name 参数值） |
|---|------|---------|---------|-----------------------------|------------------------------------------|
| 1 | `ic_amplitude_delta_1d.py` | 80-121 | 42 → 1 = **-41** | 139 → ~98 | "振幅差分因子" |
| 2 | `ic_capital_flow_intensity_1d.py` | 72-110 | 39 → 1 = **-38** | 124 → ~86 | "资金流强度因子" |
| 3 | `ic_industry_amplitude_trend_1d.py` | 67-105 | 39 → 1 = **-38** | 119 → ~81 | "行业振幅趋势因子" |
| 4 | `ic_industry_earnings_growth_1d.py` | 68-106 | 39 → 1 = **-38** | 120 → ~82 | "行业盈利增长因子" |
| 5 | `ic_industry_momentum_5d_1d.py` | 69-107 | 39 → 1 = **-38** | 121 → ~83 | "行业 5 日动量因子" |
| 6 | `ic_industry_pe_trend_1d.py` | 69-107 | 39 → 1 = **-38** | 121 → ~83 | "行业 PE 趋势因子" |
| 7 | `ic_industry_roe_trend_1d.py` | 68-106 | 39 → 1 = **-38** | 120 → ~82 | "行业 ROE 趋势因子" |
| 8 | `ic_industry_turnover_trend_1d.py` | 67-105 | 39 → 1 = **-38** | 119 → ~81 | "行业换手率趋势因子" |
| 9 | `ic_past_return_1d_1d.py` ⚠️ | 99-143 | 45 → 4 = **-41** | 161 → ~120 | "过去 1 日涨幅因子" |
| 10 | `ic_return_5d_1d.py` | 123-165 | 43 → 1 = **-42** | 183 → ~141 | "5 日累计涨幅因子" |
| 11 | `ic_tail_price_position_delta_1d.py` | 83-123 | 41 → 1 = **-40** | 138 → ~98 | "尾盘位置差分因子" |
| 12 | `ic_tail_price_slope_1d.py` | 282-324 | 43 → 1 = **-42** | 340 → ~298 | "尾盘价格趋势斜率因子" |
| 13 | `ic_tail_volume_shrink_1d.py` | 276-318 | 43 → 1 = **-42** | 334 → ~292 | "尾盘缩量程度因子" |
| 14 | `ic_tail_volume_shrink_delta_1d.py` | 83-123 | 41 → 1 = **-40** | 138 → ~98 | "尾盘缩量差分因子" |
| 15 | `ic_turnover_surge_delta_1d.py` | 82-122 | 41 → 1 = **-40** | 137 → ~97 | "换手突增差分因子" |
| 16 | `ic_volume_price_strength_1d.py` | 67-105 | 39 → 1 = **-38** | 119 → ~81 | "量价齐升强度因子" |
| 17 | `ic_volume_ratio_1d.py` | 101-144 | 44 → 1 = **-43** | 162 → ~119 | "量比因子" |
| | **合计** | **697 行 → ~20 行** | **净减 ≈ 670 行** | | |

⚠️ 第 9 行 `ic_past_return_1d_1d.py` 是 §3.1 识别的例外脚本，迁移后调用形式为：

```python
factor_direction = result.get("factor_direction", "unknown")
log_factor_summary(
    result,
    "过去 1 日涨幅因子",
    logger,
    extra_summary_lines=[f"因子方向: {factor_direction}"],
)
```

故净减为 **45 → 4 行**（4 行包含 `factor_direction` 提取 + 4 行 `log_factor_summary(...)` 多行调用），而非常规的 -X → 1。

### 4.3 不在本轮范围（明确排除）

| 类别 | 数量 | 处理 |
|------|------|------|
| 含 summary_lines 但**无** None warning block 的脚本 | 16 个（§3.1 表格中已列） | **不在轮 2 实施范围**——这 16 个脚本同样可受益于 `log_factor_summary`，但本轮聚焦"原始问题 4 范围内的 17 脚本"。轮 3 或独立 PR 处理。 |
| 不含 summary_lines 的 ic_*.py | 1 个（`ic_*.py` 共 34，含 summary 33，剩余 1）| 单独评估。 |
| 公共模块 `ic_result_builder.py` / `factor_ic_runner.py` | - | **不动**——避免与轮 1 冲突 |
| `__main__` 异常捕获块（line 130-139）| - | **不动**——MODULE.md M19 规范，已合规 |
| `run_factor_ic_analysis` 函数签名 | - | **不动**——与轮 1 解耦 |

### 4.4 测试影响

**直接影响测试**：
- `factor_ic/test_cases/test_ic_amplitude_delta_1d.py` 等 17 个对应入口脚本测试——均依赖 `factor_name`（pytest 输出）和 result JSON 结构断言，不依赖 logger 输出文案，**预期不退化**
- 现有 4 passed 5 skipped 基线（`test_ic_amplitude_delta_1d.py`）保持

**新增测试**：
- `test_factor_summary_logger.py` 覆盖：
  - 正常路径（4 字段数值）：1 条 INFO，0 条 WARNING
  - 错误路径（4 字段全 None，模拟 `build_error_result`）：1 条 INFO（含 N/A）+ 1 条 WARNING（含字段清单）
  - 扩展行：`extra_summary_lines=["因子方向: positive"]` 正确追加
  - 部分 None：`ic_mean=数值, ic_std=None`（理论不可达但兜底覆盖）

### 4.5 文档影响

| 文档 | 改动类型 |
|------|---------|
| `factor_ic/MODULE.md` | 新增 M3.x 子规范"公共模块告警归属"（详见 §10） |
| `factor_ic/docs/plans/factor_ic_warning_decision.md` | 状态字段更新为"已实施" |
| `factor_ic/docs/plans/factor_ic_warning_unification_design.md` | 本文档 §11 更新记录补完 |
| 入口脚本流程文档（17 × `<脚本名>_flow.md`） | 仅在涉及"结果摘要输出"段落的描述需更新为引用公共函数（轮 2 实施时一并 grep 处理） |

---

## §5 规范引用

### 5.1 复用既有规范（不重复定义）

| 规范 | 行号 | 本设计如何遵循 |
|------|------|---------------|
| **M3. 公共模块 logger 由调用方传入** | `factor_ic/MODULE.md:345-374` | `log_factor_summary(result, factor_display_name, logger)` 强制要求调用方传 logger（不接受 None fallback——本函数纯粹为日志服务，没有 logger 等于无意义调用） |
| **M19. 异常按类型分类处理** | `factor_ic/MODULE.md:698-741` | 本函数**不抛异常**，只输出 WARNING；`__main__` 异常捕获块 line 130-139 不动，原 `FactorCalcError / Exception` 双分支差异化保留 |
| **M22. CLI 异常按类别选择 `logger.error` 或 `logger.exception`** | `factor_ic/MODULE.md:777-833` | 本函数仅 `logger.warning(...)`，与 M22 的 error/exception 选择无冲突——None 状态属"流程继续但需运维关注"语义，warning 是正确级别 |
| **PROJECT.md 规则 #5: 因子方向由实际 IC 决定** | `PROJECT.md` | 不影响——本函数只输出摘要，不修改因子方向判断逻辑 |
| **PROJECT.md Design-First** | `AGENTS.md L92` | 本设计文档即为 Design-First 产出，覆盖 17 + 2 文件改动 |
| **PROJECT.md 任务粒度 ≤3 文件 ≤200 行** | `AGENTS.md` | 实施时按 §6 分批执行，每批 ≤3 文件 |

### 5.2 与 M3 的契合度细化

M3 原文："公共模块函数不独立创建 logger，接收调用方传入的 logger 参数（`logger=None` fallback）"

本函数 `log_factor_summary` 偏离 M3 的 `logger=None` fallback 模式——**直接强制必传**。理由：

| M3 通用场景 | `log_factor_summary` 场景 |
|-------------|--------------------------|
| `load_data_from_cache(cache_path, logger=None)`：函数主职责是返回数据，logger 仅辅助 | 本函数主职责就是**输出日志**，无 logger 等于"调用了一个什么都不做的函数" |
| 独立 fallback 还能正常返回 | 独立 fallback 会把日志写到 `factor_summary_logger.log`，违反 M3 设计意图（日志要定位到调用方） |

故本函数**强化 M3**——签名层面消除 `logger=None`，让违规调用在编译期暴露，而非运行期写错日志文件。

### 5.3 与 M19 的边界澄清

M19 适用范围："业务异常 raise FactorCalcError / 未预期异常 logger.exception"——这是**异常**处理规范。

本设计的"None 状态告警"**不是异常**：
- 不中断业务流程（result 仍可被下游消费）
- 不改变退出码（`__main__` 仍按 `result is None` / `FactorCalcError` 决定 exit code）
- 仅供运维巡检参考（grep WARNING 关键字定位失败因子）

故本设计**不属于 M19 的应用场景**，无需也不应升级为异常。

### 5.4 新增 M3.x 子规范（轮 2H §10 详化）

本设计将沉淀为 **M3.x 公共模块告警归属**子规范：当多个入口脚本出现相同的 `logger.warning(...)` block 时，应抽到 `factor_ic/common/` 单一公共函数中，避免文案扩散。

完整规范文本见 §10。

---

## §6 实施步骤

### 6.1 实施总览

按 PROJECT.md 任务粒度约束（≤3 文件 / ≤200 行/批），17 入口脚本拆 6 批迁移。每批：① 修改 → ② ruff → ③ pytest → ④ commit。

```
Step 1  公共模块 + 单元测试         (新建 2 文件 / ~190 行)
Step 2  迁移批 1（3 个常规脚本）     ic_amplitude_delta_1d / ic_capital_flow_intensity_1d / ic_volume_ratio_1d
Step 3  迁移批 2（3 个行业脚本）     ic_industry_amplitude_trend / ic_industry_earnings_growth / ic_industry_momentum_5d
Step 4  迁移批 3（3 个行业脚本）     ic_industry_pe_trend / ic_industry_roe_trend / ic_industry_turnover_trend
Step 5  迁移批 4（3 个尾盘脚本）     ic_tail_price_position_delta / ic_tail_price_slope / ic_tail_volume_shrink
Step 6  迁移批 5（3 个尾盘+收益脚本）ic_tail_volume_shrink_delta / ic_turnover_surge_delta / ic_return_5d
Step 7  迁移批 6（2 + 例外脚本）     ic_volume_price_strength / ic_past_return_1d_1d ⚠️
Step 8  MODULE.md M3.x 增补 + 流程文档同步 + 决策文档状态更新
Step 9  最终验证 + 全量 pytest + ruff
```

### 6.2 详细步骤

#### Step 1：公共模块 + 单元测试

| 动作 | 路径 | 说明 |
|------|------|------|
| 新建 | `factor_ic/common/factor_summary_logger.py` | 实现 `log_factor_summary()`（§3.2 + §3.3 草案） |
| 新建 | `factor_ic/test_cases/test_factor_summary_logger.py` | 4 场景测试（§4.4） |
| 验证 | `ruff check factor_ic/common/factor_summary_logger.py factor_ic/test_cases/test_factor_summary_logger.py` | 全绿 |
| 验证 | `pytest factor_ic/test_cases/test_factor_summary_logger.py -v` | 4 passed |
| commit | `feat(factor_ic): 新增 factor_summary_logger 公共模块（含单元测试）` | 引用本设计 §3 |

#### Step 2-7：迁移批模板（每批 3 脚本）

每批均按以下 5 步操作，**只列 Step 2 模板，Step 3-7 同构**：

```bash
# 1. 编辑 3 脚本：删除指定行号 block，替换为 1 行 log_factor_summary(...) 调用
#    ic_amplitude_delta_1d.py        line 80-121  →  log_factor_summary(result, "振幅差分因子", logger)
#    ic_capital_flow_intensity_1d.py line 72-110  →  log_factor_summary(result, "资金流强度因子", logger)
#    ic_volume_ratio_1d.py           line 101-144 →  log_factor_summary(result, "量比因子", logger)
#    （行号详见 §4.2 表格）

# 2. ruff 自动修复 + 格式化
ruff check --fix factor_ic/ic_amplitude_delta_1d.py \
                 factor_ic/ic_capital_flow_intensity_1d.py \
                 factor_ic/ic_volume_ratio_1d.py
ruff format factor_ic/ic_amplitude_delta_1d.py \
            factor_ic/ic_capital_flow_intensity_1d.py \
            factor_ic/ic_volume_ratio_1d.py

# 3. ruff 检查剩余问题
ruff check factor_ic/ic_amplitude_delta_1d.py \
           factor_ic/ic_capital_flow_intensity_1d.py \
           factor_ic/ic_volume_ratio_1d.py

# 4. pytest 对应测试用例
pytest factor_ic/test_cases/test_ic_amplitude_delta_1d.py \
       factor_ic/test_cases/test_ic_capital_flow_intensity_1d.py \
       factor_ic/test_cases/test_ic_volume_ratio_1d.py -v

# 5. 显式路径 commit（多 agent 并行隔离规则）
git commit \
  factor_ic/ic_amplitude_delta_1d.py \
  factor_ic/ic_capital_flow_intensity_1d.py \
  factor_ic/ic_volume_ratio_1d.py \
  -m "refactor(factor_ic): 迁移批 1/6 — 3 脚本接入 log_factor_summary

净减约 117 行（41+38+38）。引用 design.md §4.2 / §6 Step 2。"
```

#### Step 7：例外脚本特殊处理

`ic_past_return_1d_1d.py` 不能直接套模板——需保留 `factor_direction` 提取并通过 `extra_summary_lines` 注入：

```python
# 替换 line 99-143（45 行）为下面 4 行：
factor_direction = result.get("factor_direction", "unknown")
log_factor_summary(
    result,
    "过去 1 日涨幅因子",
    logger,
    extra_summary_lines=[f"因子方向: {factor_direction}"],
)
```

迁移后跑 `pytest factor_ic/test_cases/test_ic_past_return_1d_1d.py -v` **必须**断言"因子方向"行仍出现在 INFO 摘要中（caplog 验证）。

#### Step 8：文档同步

| 动作 | 路径 |
|------|------|
| 增补 | `factor_ic/MODULE.md`（新增 M3.x 节，详见 §10） |
| 更新 | `factor_ic/docs/plans/factor_ic_warning_decision.md`（状态：决策中 → 已实施，添加实施 commit 引用） |
| 更新 | 17 × `factor_ic/docs/<脚本名>_flow.md`（仅"结果摘要输出"段落，统一改为引用 `log_factor_summary`） |
| commit | `docs(factor_ic): M3.x + 17 流程文档同步 log_factor_summary 引用` |

#### Step 9：最终验证

```bash
# 字面量清零检查
test $(grep -c "ICIR 无法计算" factor_ic/ic_*.py) -eq 0

# 单点定义检查
test $(grep -rln "ICIR 无法计算\|IC 均值为空\|IC 标准差无法计算\|IC>0 占比无法" factor_ic/ | wc -l) -le 1

# 全量测试
pytest factor_ic/test_cases/ -v --cov-fail-under=70

# 全量 ruff
ruff check factor_ic/
ruff format --check factor_ic/

# Mypy
mypy factor_ic/
```

### 6.3 commit 节奏

按 superpowers-workflow 偏好（每轮 ruff+pytest 通过后立即 commit，不询问用户）：

| Step | commit message 模板 |
|------|---------------------|
| Step 1 | `feat(factor_ic): 新增 factor_summary_logger 公共模块（含单元测试）` |
| Step 2-7 | `refactor(factor_ic): 迁移批 N/6 — X 脚本接入 log_factor_summary` |
| Step 8 | `docs(factor_ic): M3.x + 流程文档同步 log_factor_summary 引用` |

**所有 commit 显式路径**（多 agent 并行隔离规则，不裸 `-m`），**不主动 push**。

### 6.4 单批失败回滚

任一批 ruff / pytest 不绿：
1. **不 commit**
2. `git checkout -- <批内 3 脚本>` 撤回当前批改动
3. 回到 Plan 阶段排查（按 superpowers-workflow Debug Phase）
4. 单脚本最小化重试，找到失败因子后再扩到批

详细回滚见 §8。

---

## §7 验证清单

### 7.1 单元测试（test_factor_summary_logger.py）

| 用例 | 输入 | 期望输出 | 验证方法 |
|------|------|---------|---------|
| **正常路径** | 4 字段均为数值（ic_mean=0.05, ic_std=0.12, icir=0.42, positive_ratio=0.55）| 1 条 INFO 摘要（`IC 均值: 0.0500` 等格式化）；0 条 WARNING | `caplog.records` 过滤 level / message |
| **错误路径（4 字段全 None）** | 模拟 `build_error_result` 返回的 result | 1 条 INFO（IC 字段显示 N/A）+ 1 条 WARNING（含 `ic_mean, ic_std, icir, positive_ratio` 全部 4 字段名）| caplog WARNING 字符串包含 4 个字段名 |
| **扩展行注入** | `extra_summary_lines=["因子方向: positive"]` | INFO 摘要末尾追加 1 行；WARNING 不变 | INFO 内容含"因子方向: positive" |
| **部分 None（理论不可达）** | ic_mean=0.05 但 ic_std=None | 1 条 INFO + 1 条 WARNING（仅含 `ic_std`）| 兜底覆盖，避免未来逻辑变化遗漏 |

### 7.2 集成测试（17 入口脚本）

每批 commit 后跑：

```bash
pytest factor_ic/test_cases/test_<迁移脚本>.py -v
```

**断言不退化**：原 4 passed 5 skipped 基线保持。

### 7.3 行为契约验证（§2.3 五条）

| 契约 | 验证命令 |
|------|---------|
| 不引入新告警通道 | `grep -E "logger\.(error\|exception)\|raise " factor_ic/common/factor_summary_logger.py` 无业务异常 |
| 不改变正常路径输出 | Step 9 全量 pytest 通过 |
| 不改变 IC 摘要日志 | 手动构造 fixture，diff 迁移前后 INFO 输出完全一致 |
| 告警时机不变 | `pytest -k "summary_log_order"` 验证 INFO 在 WARNING 之前 |
| 信息密度不下降 | caplog 断言 WARNING 含因子名 + 字段清单 + 运维提示 |

### 7.4 §2.5 验收标准 7 项 checklist 复核

实施完成后逐项核对（见 §2.5 表格），任一未达 = 视为未完成。

### 7.5 跨脚本一致性验证

```bash
# 字面量清零（核心验证）
[ "$(grep -c "ICIR 无法计算" factor_ic/ic_*.py)" -eq 0 ] && echo PASS || echo FAIL

# 单点定义
[ "$(grep -rln "ICIR 无法计算\|IC 均值为空\|IC 标准差无法计算\|IC>0 占比无法" factor_ic/ | wc -l)" -le 1 ] && echo PASS || echo FAIL

# 17 脚本均已 import 公共函数
for f in $(grep -l "ICIR 无法计算" factor_ic/ic_*.py 2>/dev/null; ls factor_ic/ic_amplitude_delta_1d.py factor_ic/ic_capital_flow_intensity_1d.py ...); do
  grep -q "from factor_ic.common.factor_summary_logger import log_factor_summary" "$f" || echo "MISSING: $f"
done
```

---

## §8 回滚

### 8.1 单批回滚（首选）

实施过程中任一批失败：

```bash
# 撤回当前批 3 脚本未 commit 改动
git checkout -- factor_ic/ic_<脚本1>.py factor_ic/ic_<脚本2>.py factor_ic/ic_<脚本3>.py

# 回到 Plan 阶段，单脚本最小化重试
```

**关键**：失败时**不 commit**，避免污染主分支历史。

### 8.2 已 commit 单批回滚

若某批已 commit 后才发现问题：

```bash
# 反向 commit（保留历史，符合多 agent 协作）
git revert <commit_sha> --no-edit

# 或交互式 rebase 删除（仅当未 push 时）
git rebase -i HEAD~N  # 标记该 commit 为 drop
```

**禁用 `git reset --hard`**——多 agent 并行规则，避免误删他人改动。

### 8.3 全量回滚（极端情况）

整体方案被推翻（如新增公共函数引入不可解决的循环依赖）：

```bash
# 找到 Step 1 commit（feat: 新增 factor_summary_logger）
git log --oneline | grep "factor_summary_logger"

# 反向 revert 所有相关 commit（按时间倒序）
git revert <Step9>..<Step1> --no-edit
```

回滚后**不删除** design.md / decision.md，作为失败教训留底。

### 8.4 回滚触发条件

| 条件 | 触发动作 |
|------|---------|
| 单批 ruff / pytest 不绿 | 8.1 单批回滚 |
| 已 commit 后发现 caplog 断言失败 | 8.2 git revert |
| 实施过程发现 §3.6 否决方案中的某个问题被低估（如循环依赖）| 8.3 全量回滚 + 重写 §3 |
| 17 脚本中 >3 个测试退化 | 8.3 全量回滚（说明设计本身有缺陷）|

---

## §9 风险预案

### 9.1 已识别风险矩阵

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| R1 | 例外脚本 `ic_past_return_1d_1d.py` 的 `factor_direction` 字段不在 result 中（KeyError）| 低 | 中 | `result.get("factor_direction", "unknown")` 默认值兜底；Step 7 单独跑测试 |
| R2 | `extra_summary_lines` 参数被未来调用方误用为列表/字符串混传 | 中 | 低 | 类型注解 `list[str] \| None`；Step 1 单元测试覆盖 `extra_summary_lines=["str"]` 场景 |
| R3 | 17 脚本测试中存在隐式依赖 logger 输出文案的 caplog 断言 | 中 | 高 | Step 2 前 grep `caplog.*ICIR\|caplog.*均值为空` 全 17 测试，发现即先迁移测试断言 |
| R4 | 例外脚本扩展行未来扩散（其他脚本也开始用 `extra_summary_lines`） | 中 | 低 | M3.x 规范明确"扩展行属临时容器，超 3 个脚本使用即应升级为正式参数" |
| R5 | `factor_display_name` 中文名书写不一致（"因子" 后缀有无）| 高 | 低 | §4.2 表格已统一所有 17 个 display_name 为 `XX因子` 后缀，实施时直接复制 |
| R6 | 与轮 1 实施时间冲突（同时改 factor_ic/common/）| 低 | 中 | 轮 2 新建独立文件 `factor_summary_logger.py`，轮 1 改 `factor_ic_runner.py`，路径无冲突 |
| R7 | mypy 检查失败：`logging.Logger` import 路径变化 | 低 | 低 | Step 1 设计阶段已确认 `import logging` + `logging.Logger`；与现有公共模块一致 |

### 9.2 R3 详细预案（最高影响风险）

**触发场景**：某入口脚本测试用例形如：

```python
def test_xxx_warning(caplog):
    ...
    assert "ICIR 无法计算" in caplog.text  # ← 迁移后此断言失效
```

**预防扫描**：Step 2 实施前先跑：

```bash
grep -rn "caplog.*ICIR\|caplog.*均值为空\|caplog.*IC 标准差\|caplog.*IC>0 占比" \
     factor_ic/test_cases/
```

如有命中，**先在同 PR 内迁移测试断言**到新文案：

```python
# 旧
assert "ICIR 无法计算" in caplog.text
# 新
assert "IC 指标异常字段" in caplog.text
assert "icir" in caplog.text  # 字段清单含 icir
```

### 9.3 风险监控

实施过程每批 commit 后追加日志至 `factor_ic_warning_unification_design.md` §11 更新记录，记录：
- 批次时间
- pytest 结果
- 任何意外行为

---

## §10 MODULE.md M3.x 子规范草稿

### 10.1 增补位置

`factor_ic/MODULE.md` 现有 M3 在 line 345-374，M4 在 line 378。M3.x 应置于 M3 与 M4 之间，新增 line 376（M3 末尾分隔线）之后。

### 10.2 草稿全文

```markdown
## M3.1. 公共模块告警归属（同文案 logger.warning ≥ 3 次即抽公共函数）

**What**:当多个入口脚本（factor_ic/ic_*.py）出现**相同或近似**的 `logger.warning(...)` block 时,该告警逻辑应抽到 `factor_ic/common/` 单一公共函数中,由入口脚本调用,而非各脚本本地复制粘贴。

**Why**:本规范来自轮 2 历史教训——`ICIR 无法计算` 等 4 条 None 状态告警曾在 17 个入口脚本中字面量重复 68 次,任一文案优化（如细化错误根因）需 17 处同步修改,扩散成本高、易遗漏。

**How**:

```python
# ✓ 正确：公共函数集中定义告警文案
# factor_ic/common/factor_summary_logger.py
def log_factor_summary(result, factor_display_name, logger, *, extra_summary_lines=None):
    ...
    if none_fields:
        logger.warning(
            "%s IC 指标异常字段: %s（数据加载可能失败...）",
            factor_display_name, ", ".join(none_fields),
        )

# 入口脚本仅调用
from factor_ic.common.factor_summary_logger import log_factor_summary
log_factor_summary(result, "振幅差分因子", logger)
```

**Don't**:

```python
# ❌ 17 脚本各自重复 4 条 warning 字面量
if ic_mean is None:
    logger.warning("本次计算 IC 均值为空，请检查数据源")
if ic_std is None:
    logger.warning("IC 标准差无法计算，请检查因子数据分布")
if icir is None:
    logger.warning("ICIR 无法计算，请检查因子数据分布")
if positive_ratio is None:
    logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")
```

**When**:

- ≥ 3 个入口脚本出现**相同或近似**告警文案 → **必须**抽公共函数
- 偶发性单脚本特定告警（如某因子特有的业务告警）→ 保留本地
- 告警文案随因子参数变化（如不同窗口期阈值）→ 保留本地或封装为参数化公共函数

**Examples**:

| 场景 | 处理方式 |
|------|---------|
| ic_mean / ic_std / icir / positive_ratio 四字段 None 告警（17 脚本一致） | 抽到 `log_factor_summary` |
| `logger.warning("rolling_ic_mean 长度异常")` 仅出现 1 处 | 保留本地 |
| 不同因子各自的"参数越界"告警，文案略有差异 | 抽公共函数 + 接收 `factor_display_name` 参数 |

**Verify**:

```bash
# 同文案 warning 出现次数检查
grep -rcE "logger\.warning\([\"'][^\"']+[\"']\)" factor_ic/ic_*.py | sort | uniq -c | sort -rn | head

# 公共告警函数命名规范（log_xxx_summary / log_xxx_anomalies 等）
grep -rEn "^def log_" factor_ic/common/
```

**配套规范**:

- 与 M3（公共模块 logger 由调用方传入）一致：公共告警函数必须接收 logger 参数
- 公共告警函数允许偏离 M3 的 `logger=None` fallback 默认（强制必传），理由：函数主职责即"输出日志",无 logger 等于无意义调用
- 公共告警函数**不抛异常**,仅 `logger.warning(...)`；异常处理走 M19 路径
```

### 10.3 与 M3 的关系

| 维度 | M3（既有） | M3.1（新增） |
|------|-----------|--------------|
| 适用对象 | 公共模块**所有**函数 | 公共模块**告警类**函数 |
| 核心约束 | logger 由调用方传入（避免日志写错文件）| 同文案 warning ≥ 3 次必须抽公共函数（避免文案扩散）|
| logger 参数 | 接收 `logger=None` fallback | 强制必传（M3 的强化版） |

M3.1 是 M3 的**专用化扩展**，不矛盾、不替代。

---

## §11 更新记录

| 日期 | 轮次 | 改动 | commit |
|------|------|------|--------|
| 2026-06-15 | 轮 2A | 决策文档（推荐方案 ⑤+②）| `ccf2bdc` |
| 2026-06-15 | 轮 2B | §1 背景（含 ic_result_builder.py:254 证据链）| 待 commit |
| 2026-06-15 | 轮 2C | §2 目标（量化指标 + 5 行为契约 + 5 非目标 + 7 验收清单）| 待 commit |
| 2026-06-15 | 轮 2D | §3 接口设计（方案 b 选型 + `log_factor_summary` 签名/实现/调用方式）| 待 commit |
| 2026-06-15 | 轮 2D 修正 | 行号纠错 3 处（§1.3 / §2.3 第 3 / 第 4 条）| 待 commit |
| 2026-06-15 | 轮 2E | §4 影响范围（17 脚本精确清单 + 净减 670 行 + 排除范围）| 待 commit |
| 2026-06-15 | 轮 2F-1 | §5 规范引用（M3 / M19 / M22 + M3 偏离论证）| 待 commit |
| 2026-06-15 | 轮 2F-2 | §6 实施步骤（9 step + 6 批次 + commit 节奏）| 待 commit |
| 2026-06-15 | 轮 2G | §7 验证清单 + §8 回滚 + §9 风险预案（R1-R7）| 待 commit |
| 2026-06-15 | 轮 2H | §10 MODULE.md M3.1 草稿 + §11 更新记录 | 本轮 commit |

### 11.1 实施阶段动态更新（占位，待执行后填充）

| 日期 | 批次 | pytest 结果 | commit | 备注 |
|------|------|-------------|--------|------|
| TBD | Step 1 公共模块 | TBD | TBD | TBD |
| TBD | Step 2 迁移批 1 | TBD | TBD | TBD |
| ... | ... | ... | ... | ... |

### 11.2 修订说明

| 修订点 | 原文 | 修正 | 原因 |
|--------|------|------|------|
| §2.2 净减估算 | "净减少 ≈ 17 × 9 = **153 行**" | 应为 **697 → 20 行 ≈ 净减 670 行**（详见 §4.2 实测）| 估算时仅算 4 条 warning，未算整段 summary 流程 |
| §10 子规范编号 | "M3.x" | 落实为 **M3.1** | M3 既有规范无子节，M3.1 是首个子节 |

---

## 设计文档完结

本设计文档（`factor_ic_warning_unification_design.md`）至此完整覆盖：

1. ✅ §1 背景与证据链（推翻原始问题 4 假设）
2. ✅ §2 目标与行为契约
3. ✅ §3 接口设计（方案 b：`log_factor_summary` 公共函数）
4. ✅ §4 影响范围（17 脚本精确清单 + 净减 ~670 行）
5. ✅ §5 规范引用（M3 / M19 / M22）
6. ✅ §6 实施步骤（9 step / 6 批次）
7. ✅ §7 验证清单（单元 + 集成 + 行为契约 + 一致性）
8. ✅ §8 回滚（3 级策略）
9. ✅ §9 风险预案（7 条风险 + R3 详化）
10. ✅ §10 MODULE.md M3.1 子规范草稿
11. ✅ §11 更新记录（含 §2.2 净减估算修订说明）

**审核状态**: 等待最终审核 → 进入轮 2 实施 PR。
