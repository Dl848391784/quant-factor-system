# 八轮代码审查才收敛的教训（2026-05-06）

> **根因**: 每轮审查遗漏不同维度 → 缺少调度层Guardrail强制覆盖全部维度

---

## 问题现象

| 轮次 | 问题数 | 遗漏维度 |
|------|--------|----------|
| 第一轮 | 14处 | 配置文件、辅助方法 |
| 第二轮 | 7处 | 边界检查、内存性能 |
| 第三轮 | 6处 | 因子映射一致性 |
| 第四轮 | 4处 | JavaScript注释、约束默认值 |
| 第五轮 | 4处 | 导入路径、引擎类型 |
| 第六轮 | 3处 | forward_return_3d作为因子 |
| 第七轮 | 6处 | IC_DIRECTIONS/FCTOR_FIELD_MAP跨文件一致性 |
| 第八轮 | 0处 | ✅ 终于收敛 |

---

## 根因分析

| 层级 | 问题描述 |
|------|----------|
| **L1** | 每轮审查发现新问题，无法收敛 |
| **L2** | 没有明确的审查维度清单 |
| **L3** | **调度层缺少Guardrail强制覆盖全部维度** |
| **L4** | **没有Baseline状态记录，不知道之前查了什么** |

---

## Harness解决方案

### 1. 调度层Guardrail强制执行

**位置**: `~/.openclaw/workspace/memory/guardrails/code_review_dispatch.md`

**内容**: 10项审查维度全部强制检查

| # | 维度 | 负责Agent |
|---|------|-----------|
| 1-3 | 逻辑/引用/赋值 | 云柏 📝 |
| 4-6 | 并发/边界/数据处理 | 云汐 🧪 |
| 7-10 | 配置/内存/异常/质量 | 共查 |

### 2. Baseline状态追踪

**位置**: `~/.openclaw/workspace/memory/review_baseline.json`

**内容**: 记录已查进度、遗漏维度、收敛状态

```json
{
  "dimensions_coverage": {"逻辑错误": 3, ...},
  "missing_dimensions": [],
  "convergence_status": "converged"
}
```

### 3. Output Contract（Artifact-first）

**位置**: `~/.openclaw/workspace/memory/contracts/review_output_contract.md`

**内容**: Structured JSON格式，对话只显示summary+preview

### 4. 自动收敛判断

**停止条件**（全部满足）：
- 连续2轮新发现问题 < 3
- dimensions_coverage全>0
- missing_dimensions为空
- 语法检查通过

---

## 效率对比

| 模式 | 轮数 | 效率 |
|------|------|------|
| **无Guardrail** | 8轮才收敛 | ❌ 低效 |
| **有Guardrail** | ≤4轮收敛 | ✅ 目标 |

---

## 教训记录到Memory

| 教训 | Memory条目 |
|------|------------|
| 审查维度遗漏反复发生 | **八轮审查才收敛 → 缺少调度层Guardrail强制覆盖** |
| Baseline状态未追踪 | **不知道之前查了什么 → 每轮遗漏不同维度** |
| 收敛判断缺失 | **不知道何时停止 → 无限轮审查** |
| 主agent自己审查 | **未按职责分工 → 应调度云柏/云汐** |

---

## 文件清单

| 文件 | 用途 |
|------|------|
| `guardrails/code_review_dispatch.md` | 调度层强制检查清单 |
| `review_baseline.json` | 审查进度状态 |
| `contracts/review_output_contract.md` | Artifact-first输出契约 |

---

*Harness是缰绳，让审查可控可收敛。* 🎯