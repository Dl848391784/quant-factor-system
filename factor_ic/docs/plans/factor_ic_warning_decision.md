# factor_ic 异常告警改造 - 决策文档（2A）

**状态**: pending-decision（仅决策选型，未进入完整 design.md 编写）
**作者**: 云瑶
**创建**: 2026-06-15
**关联问题**: 用户原始问题 4（ICIR/ic_std 告警文案语义差异化）

---

## 1. 用户原始诉求

> "ic_std is None 和 icir is None 的告警语义几乎相同（均提示"检查因子数据分布"），
> 无法帮助运维区分是标准差本身为空还是 ICIR 计算失败导致的差异，
> 应将 ICIR 为 None 的告警文案改为"ICIR 无法计算，请确认有效天数是否充足或标准差是否为零"
> 以明确区分原因。"

**隐含假设**：4 条 warning（ic_mean/ic_std/icir/positive_ratio）的 None 触发条件
**互相独立**——某次失败可能只 ICIR 是 None，其他正常；运维需要从文案区分。

---

## 2. 根因分析（推翻假设）

### 2.1 触发路径追溯

| 路径 | 入口 | 触发条件 | 4 字段 None 状态 |
|------|------|---------|-----------------|
| **A. 上游加载失败** | `build_error_result()` 行 247-301 | 数据加载/校验失败 | **4 字段同时 None** |
| **B. 正常计算** | `build_ic_result()` 行 100-107 | 任何成功路径 | **4 字段同时非 None**（NaN→`round(float(NaN))` 仍是 NaN，**不是 None**） |

**证据链（factor_ic/common/ic_result_builder.py）**：

```python
# 路径 A：错误兜底，line 254
"ic_metrics": {"ic_mean": None, "ic_std": None, "icir": None, ...}
# ↑ 4 个 None 是绑定的

# 路径 B：正常计算，line 100-107
ic_metrics = {
    "ic_mean": round(float(ic_mean), 6),    # 有 ic_series 必有值
    "ic_std": round(float(ic_std), 6),      # NaN 时此处仍是 float NaN，不是 None
    "icir": round(float(icir), 4),          # 同上
    ...
}
```

**ICIR 公式**（`ic_calculator.py` 行 723）：
```python
icir = abs(ic_mean) / ic_std if ic_std > 0 else 0
# ↑ 当 ic_std=0 时 icir=0（不是 None）；当 ic_std=NaN 时 icir=NaN（不是 None）
```

### 2.2 推论

**当前公共模块代码下，"icir is None 但 ic_std 非 None" 的情况不存在。**

因此用户原始问题 4 中"区分是标准差本身为空还是 ICIR 计算失败"的运维诉求，
**在当前实现下无法通过文案区分根因**——因为根因只有一个：上游数据加载失败。

### 2.3 入口脚本侧旁证

22 处脚本统一使用：
```python
if ic_std is None: logger.warning("IC 标准差无法计算，请检查因子数据分布")
if icir is None: logger.warning("ICIR 无法计算，请检查因子数据分布")
```

四条 warning 触发条件强绑定 → 实际线上日志中 4 条同时出现或都不出现。
告警风暴 + 文案趋同 = 运维仍然只能查到一条根因。

---

## 3. 方案对比

| # | 方案 | 健康度 | 改动范围 | 是否解决根因 | 推荐 |
|---|------|--------|---------|-------------|------|
| ① | 仅按用户原意改 ICIR 文案 | ❌ 给运维误导 | 22 脚本 | ❌ 4 条同时触发，文案区分无意义 | ❌ |
| ② | 入口删冗余 warning，仅保留 ic_mean 总告警 | ✅ 与现实绑定一致 | 22 脚本 | ✅ | △ 备选 |
| ③ | 入口保留 4 条但文案改为"上游加载失败" | ✅ 引导查根因 | 22 脚本 | ✅ | △ 备选 |
| ④ | 公共模块改造让 ic_std/icir 真正能独立 None | ✅✅ 最彻底 | 22 脚本+公共+测试 | ✅ 但工作量过大 | ❌ 过度工程 |
| **⑤+②** | **公共模块集中打一条准确告警 + 入口删 4 行 warning** | **✅✅ 与轮 1 同思路** | **1 公共+22 脚本（仅删行）** | **✅** | **✅✅ 推荐** |

### 3.1 推荐方案 ⑤+② 详解

**核心思路**（与轮 1 `extra_log_params` 架构连贯）：

1. **公共模块** `factor_ic_runner.py` 在结果构建后统一检查关键字段：
   ```python
   ic_metrics = result.get("ic_metrics") or {}
   if ic_metrics.get("ic_mean") is None:
       _logger.warning(
           "IC 指标无法获取，根因：上游数据加载/计算失败；"
           "ic_std/icir/positive_ratio 同时缺失，请检查 build_error_result 触发原因"
       )
   ```
2. **入口脚本** 删除 4 条 `if X is None: logger.warning(...)` block（每脚本约 8 行）

### 3.2 与轮 1 架构一致性

| 维度 | 轮 1（启动日志） | 轮 2（异常告警） |
|---|---|---|
| 当前问题 | 公共+入口双打 | 4 条 warning 假装独立但实际绑定 |
| 收口方向 | 公共模块统一打横幅 | 公共模块统一打总告警 |
| 入口动作 | 删 logger.info | 删 4×if-warning block |
| 接口扩展 | extra_log_params | 无（直接在 runner 末尾检查） |

---

## 4. 风险与限制

### 4.1 风险

| 风险 | 概率 | 预案 |
|------|------|------|
| 上游 pipeline 用 grep "ICIR 无法计算" 监控 | 中 | 改造前 `grep -rE "ICIR 无法计算" backtest/ summary/ comprehensive_factor/` 排查 |
| 公共模块改造若被回滚，22 脚本 warning 已删 → 静默失败 | 高 | Step 拆分：先公共模块加新 warning + 灰度（保留入口旧 warning），观察一周后再批量删 |
| 用户/团队期望"4 条独立信号" | 低 | 本决策文档明示根因绑定证据，沟通后落地 |

### 4.2 不解决的问题

- **方案 ⑤+② 不修改 ic_std/icir 在 NaN 时的处理**：仍然是 NaN→`round(float(NaN))`
- 若团队真需要"ic_std 独立失败信号"（即方案 ④ 场景），需独立立项

---

## 5. 决策点（待确认）

请就以下点拍板，再决定是否进入 2B（design.md 骨架）：

### Q1：根因分析（§2）是否被你接受？
- 选项 a：接受，4 条 warning 触发条件强绑定属实
- 选项 b：你怀疑还有其他路径会触发部分 None，需要继续追

### Q2：选型方案
- 选项 a：⑤+②（推荐，公共模块集中收口）
- 选项 b：③（最小改动，保留 4 个访问点但改文案）
- 选项 c：原始 ①（仅按用户原意修文案，明知误导）
- 选项 d：暂停轮 2，先完成轮 1 执行再回头

### Q3：是否需要事先做"22 脚本→上游 grep 监控"调查？
（即方案 4.1 风险表第一行的预案）
- 选项 a：是，下一轮先做 grep 调查
- 选项 b：否，直接进入 2B 骨架

---

## 6. 关联文档

- 轮 1 design：`factor_ic/docs/plans/factor_ic_startup_log_dedup_design.md`
- 公共模块：`factor_ic/common/ic_calculator.py:716-723`、`ic_result_builder.py:100-107, 247-301`
- MODULE.md M22：错误信息含上下文 + 合法值 + 问题定位（本方案需扩展遵循）

---

## 7. 更新记录

| 时间 | 版本 | 说明 |
|------|------|------|
| 2026-06-15 | v1.0-decision | 决策文档完成，根因推翻原始假设；待用户拍板 Q1-Q3 |
