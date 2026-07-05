# Design: factor-development skill 精简方案

> **任务**：将 `~/.hermes/skills/quant-development/factor-development/SKILL.md` 从 156KB/1825行 精简到 ~50KB/~600行（-68%）
> **策略**：跟 superpowers-workflow 同套路（激进拆分到 references/）
> **日期**：2026-06-30
> **关联规范**：PROJECT.md 弱模型防御规则 #12（Design-First：涉及 2+ 文件改动）

---

## 1. 现状分析（已读全文）

| 指标 | 数值 |
|---|---|
| SKILL.md 字节 | 156,242 |
| SKILL.md 行数 | 1,825 |
| references/ 文件数 | 213 |
| references/ 总行数 | 35,140 |
| 当前最大 skill | 是（TOP 1） |

## 2. 拆分边界（按行数实测）

### 主文件保留（约 600 行）

| 节 | 行数 | 性质 |
|---|---|---|
| Overview | 2 | 必留 |
| Trigger | 25 | 核心入口索引 |
| Phase 2: IC 脚本开发模式 | 63 | 精简版入口（指向 detail） |
| Phase 3: 分层回测脚本模式 | 52 | 精简版入口 |
| Phase 4: Pipeline 与权重选择模式 | 124 | 完整保留（实战高频） |
| 因子命名规范 + 重命名 | 27 | 必留 |
| 前置检查 + 验证 + Pattern 18 | 84 | 必留 |
| Support Files | 116 | references 索引 |

### 拆出到 references/（约 1000 行）

| 新文件 | 来源（SKILL.md 行号） | 预计行数 | 内容 |
|---|---|---|---|
| `references/ic-script-development-detail.md` | L92-323 (Phase 2 IC 脚本开发流程 233行) | ~230 | IC 脚本完整规范：FactorSpec 三种模式、SPEC 声明位置、Pitfall #168-#177、None→异常链、startup 日志规范、guard 模式 |
| `references/code-organization-detail.md` | L517-832 (Phase 5 代码组织模式 316行) | ~310 | Pattern 3 公共模块抽取、Pattern 4 独立函数、Pattern 6 大数据加载内存优化 + 三轮升级（ijson/chunked/array.array）+ Pattern 11 Pipeline 集成 + OOM 排查三件套（Pitfall #79/#81/#82） |
| `references/pitfalls-catalog.md` | L834-1591 (Pitfalls 汇总 355行+其他) | ~750 | 100+ pitfall 按主题分类：新增因子(#1-12)、分层回测(#31-33)、factor_cli(#34-36,83)、选股权重(#13-18)、数据管线静默缺陷(#83-97)、缓存与级联(#37-38)、综合因子(#39-44)、NaN 处理(#45)、报告(#49-54)、选股策略(#55-56,59-60)、相关性(#61-62)、pandas/JSON/Decimal/akshare 等 |
| `references/case-study-fundamental-momentum.md` | L1190-1552 (方案B 基本面动量因子 402行) | ~400 | _merge_asof_financial 辅助函数、Pattern 15 数据频率合并策略、Pattern 16 多方案 industry 列管理、Pattern 17 流式 JSON 写入、ΔROE/ΔPE 计算模式、financial_data 验证、akshare 数据源切换、资金流因子 |

## 3. 主文件精简后结构

```
# Factor Development Workflow (v2.43 精简版)

## Overview (2 行)

## Trigger (25 行) - 触发条件索引

## Phase 2: IC 脚本开发模式 (63 行) - 入口 + → references/ic-script-development-detail.md

## Phase 3: 分层回测脚本模式 (52 行) - 完整保留

## Phase 4: Pipeline 与权重选择模式 (124 行) - 完整保留

## Phase 5: 代码组织模式 (30 行) - 入口 + → references/code-organization-detail.md

## Pitfalls 汇总 (10 行) - 索引 + → references/pitfalls-catalog.md

## 方案B：基本面动量因子 (10 行) - 索引 + → references/case-study-fundamental-momentum.md

## 因子命名规范 (10 行)

## 因子重命名 Checklist (17 行)

## 前置检查：系统性因子数据完整性验证 (15 行)

## 验证步骤 (20 行)

## 单点定义原则 (9 行)

## Pattern 18: Single Source of Truth Migration (40 行)

## Support Files (~150 行) - 按主题分类 references 索引
```

预计主文件 ~600 行 / ~50KB。

## 4. 设计原则

1. **零内容丢失**：references 已有 213 个文件，1:1 拆出 4 个新文件
2. **零合并**：不合并任何已有 references（避免合并判断风险，留给后续）
3. **不破坏引用**：所有拆出内容保持原顺序、原措辞、原行号（便于追溯历史教训）
4. **索引清晰**：主文件保留 references 索引（Support Files 章节），按主题分类

## 5. 风险评估

| 风险 | 缓解措施 |
|---|---|
| 拆出的 references 内容跟主文件脱节 | 主文件保留 Support Files 索引 + 每个 Phase 保留入口段落 + 详细指针 |
| 用户/agent 找不到拆出的内容 | Trigger 章节保留所有引用，且 references 索引按主题分组 |
| 主文件太薄导致弱模型忽略 | 600 行仍有足够上下文，保留 4 阶段流程骨架 + Pitfall 索引 |

## 6. 不在本次范围

- ❌ 不修改 references/ 已有 213 个文件
- ❌ 不修改 templates/
- ❌ 不合并 references（避免内容丢失风险）
- ❌ 不删除任何历史教训

## 7. 执行步骤（8 步）

```
Step 1: 创建 references/ic-script-development-detail.md（230 行）
Step 2: 创建 references/code-organization-detail.md（310 行）
Step 3: 创建 references/pitfalls-catalog.md（750 行）
Step 4: 创建 references/case-study-fundamental-momentum.md（400 行）
Step 5: 精简 SKILL.md 主文件到 ~600 行 / ~50KB
Step 6: 验证（grep 引用、字节数、结构完整性）
```

## 8. 验证标准

- [ ] SKILL.md ≤ 60KB（缩减 ≥ 60%）
- [ ] SKILL.md ≤ 700 行（缩减 ≥ 60%）
- [ ] 4 个新 references 文件已创建
- [ ] 所有 SKILL.md 中引用 `references/xxx.md` 都能命中（不含新增 4 个的命中验证）
- [ ] Python 语法检查通过（用 py_compile）
- [ ] 文件总字节数变化：原 156KB 主文件 → ~50KB 主文件 + ~30KB 新 references = 净 -76KB

## 9. 提交消息模板

```
精简 factor-development skill：SKILL.md 156KB → ~50KB

按 superpowers-workflow 同套路（激进拆分方向）：
- 主文件只保留：Overview + Trigger + 各 Phase 入口 + 索引
- 拆出 4 个主题 references：IC 脚本详解、代码组织、Pitfall 目录、基本面动量案例
- 不修改 references/ 已有 213 个文件
- 不合并任何历史教训

变更文件：
- SKILL.md: 1825 行 → ~600 行
- 新增 references/ic-script-development-detail.md（~230 行）
- 新增 references/code-organization-detail.md（~310 行）
- 新增 references/pitfalls-catalog.md（~750 行）
- 新增 references/case-study-fundamental-momentum.md（~400 行）

验证：
- SKILL.md 字节数：156242 → ~50000（缩减 68%）
- 零内容丢失（所有拆出内容 1:1 保留）
```

## 10. 关联规范引用

- **PROJECT.md 弱模型防御规则 #12（Design-First）**：本次涉及 1+4 = 5 个文件改动，先提交 design.md 审核
- **PROJECT.md 规则 #5（数据驱动）**：基于 superpowers-workflow 优化实测（171→38KB，节省 78%）复用同一模式
- **superpowers-workflow L562/L1219**：每轮 ruff+pytest 通过后立即 commit，本设计文档作为提交参考