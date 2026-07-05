# Design: 替换 codegraph-context plugin 为 superpowers-workflow-injection plugin

> **任务**：删除现有 `codegraph-context` plugin，新建 `superpowers-injection` plugin，每次 `pre_llm_call` 自动注入 superpowers-workflow skill 核心骨架到 LLM 上下文。
> **日期**：2026-06-30
> **关联规范**：PROJECT.md 弱模型防御规则 #12（Design-First：涉及 2+ 文件改动）

---

## 1. 现状分析

| 项 | 当前状态 |
|---|---|
| 启用 plugin | `~/.hermes/config.yaml` 中 `plugins.enabled: ['codegraph-context']` |
| Plugin 目录 | `~/.hermes/plugins/codegraph-context/` |
| Hook 机制 | `pre_llm_call` callback，返回 `{"context": "..."}` 注入到 user message |
| 注入内容 | codegraph 模块摘要（6-8K token）+ FTS5 关键字匹配 |
| 问题 | 即使问非开发问题也注入 6-8K codegraph；弱模型容易跳过 skill 加载（"AGENTS.md 入口守门员"曾踩坑） |

## 2. 设计目标

- ✅ 删除 codegraph-context plugin
- ✅ 新建 superpowers-injection plugin
- ✅ 每次 `pre_llm_call` 自动注入 superpowers-workflow SKILL.md 主文件内容（约 38KB）
- ✅ 保留 workspace 感知（兼容 WebUI `[Workspace::v1: /path]` 前缀）
- ✅ 保留 try/except 崩溃保护
- ✅ 更新 config.yaml 启用列表

## 3. 设计原则

1. **系统级强制注入**：跟原 codegraph plugin 同样的零合规机制——不需要 LLM 主动加载 skill
2. **精简内容**：只注入 SKILL.md 主文件（38KB/697行），不注入 326 个 references 索引（references 按需 skill_view 加载）
3. **智能裁剪**：可选——根据用户消息是否涉及开发任务，决定注入"完整骨架" vs "精简提醒"
4. **零合规成本**：插件崩溃不中断主循环（沿用原 plugin 的 try/except 模式）
5. **不破坏 skill 系统**：SKILL.md 仍可被 skill_view 主动加载（用于按需加载 references）

## 4. 实施方案

### Step 1: 新建 plugin 目录 `~/.hermes/plugins/superpowers-injection/`

**文件结构**：
```
~/.hermes/plugins/superpowers-injection/
├── plugin.yaml
├── __init__.py            # 入口，注册 pre_llm_call hook
└── skill_injector.py      # 注入逻辑（读 SKILL.md + 注入）
```

### Step 2: plugin.yaml（最小化配置）

```yaml
name: superpowers-injection
version: 1.0.0
description: "Auto-inject superpowers-workflow skill core into every LLM call via pre_llm_call hook. Workspace-aware. Zero agent compliance required."
author: "YunYao"
hooks:
  - pre_llm_call
```

### Step 3: __init__.py（hook 注册）

沿用 codegraph-context 的结构：
- `_extract_workspace(user_message)` → 提取 WebUI workspace 前缀（保留向后兼容）
- `_on_pre_llm_call(user_message, ...)` → 注入 SKILL.md 主文件
- `register(ctx)` → `ctx.register_hook("pre_llm_call", _on_pre_llm_call)`

### Step 4: skill_injector.py（核心注入逻辑）

**输入**：cleaned_msg（去除 workspace 前缀）+ workspace_path（可空）
**输出**：格式化字符串，包含：
1. 一行提示：`[已自动注入 superpowers-workflow skill]`
2. SKILL.md 完整内容（38KB）

**实现要点**：
- SKILL.md 路径：优先读 `~/.hermes/skills/software-development/superpowers-workflow/SKILL.md`
- 缓存：避免每次 LLM call 都读磁盘（用 `@functools.lru_cache` 缓存内容，文件 mtime 变化时刷新）
- 异常保护：找不到 SKILL.md → 跳过注入（不报错）
- 可选裁剪：根据消息判断是否开发任务 → 完整 vs 精简（v1.0 先全部注入）

### Step 5: 更新 `~/.hermes/config.yaml`

```diff
 plugins:
   enabled:
-    - codegraph-context
+    - superpowers-injection
   disabled: []
```

### Step 6: 删除旧 plugin

```bash
rm -rf ~/.hermes/plugins/codegraph-context/
rm -rf ~/.hermes/plugins/codegraph-context/__pycache__/
```

### Step 7: 验证

- 重启 gateway（或 Hermes WebUI 重新加载 plugin）
- 发送测试消息 → 确认 superpowers-workflow 内容被注入
- 验证 codegraph-context 不再注入

## 5. 风险评估

| 风险 | 缓解措施 |
|------|----------|
| 注入 38KB 太大，每次都注入 | 38KB 比 codegraph 6-8K 大约 5-6 倍——需要评估。v1.0 先实测，必要时按"开发任务"判断精简 |
| 弱模型读 SKILL.md 后反而跳过 skill_view | SKILL.md 主文件已精简到 697 行，关键章节齐全；弱模型读完应能执行入口守门员 |
| 删除 codegraph 后开发者失去代码结构视图 | 短期影响：开发者失去"自动代码结构提示"。替代方案：按需 `sqlite3 .codegraph/...` 查询 |
| SKILL.md 路径硬编码到 ~/.hermes | 通过 `pathlib.Path.home()` + `os.path.expanduser` 兼容；保留回退到 `which skill` 或环境变量 `HERMES_SKILLS_DIR` |

## 6. 性能影响估算

- **每次 LLM call 多消耗**：~38KB（697 行）≈ 9-10K token（输入端）
- **对比 codegraph**：原 6-8K → 现在 9-10K（增加约 30%）
- **vs 按需 skill_view**：之前 user 主动调一次 skill_view 消耗 ~38KB 一次，现在每次都消耗
- **任务量**：如果项目每天 50 次 LLM call → 额外消耗 450-500K token/天
- **收益**：零合规要求——agent 不会再跳过 skill 加载

## 7. 不在本次范围

- ❌ 不修改 SKILL.md 内容（v2.0 精简已完成）
- ❌ 不删除项目中的 `.codegraph/codegraph.db`（codegraph 数据本身还有用，可手动查询）
- ❌ 不改其他 plugin（如果存在）
- ❌ 不实现"智能裁剪"（v1.0 全部注入，v2.0 再优化）

## 8. 执行步骤（10 步）

```
Step 1: 创建 ~/.hermes/plugins/superpowers-injection/ 目录
Step 2: 写 plugin.yaml
Step 3: 写 skill_injector.py（SKILL.md 注入逻辑）
Step 4: 写 __init__.py（hook 注册）
Step 5: 备份并修改 ~/.hermes/config.yaml（enabled 列表）
Step 6: 删除旧 codegraph-context/ 目录
Step 7: 验证 plugin 加载（重载 gateway 或 WebUI）
Step 8: 发送测试消息确认注入生效
Step 9: 提交本次改动（git 或直接 git add plugin 目录）
Step 10: 更新 design.md 状态为 "已实施"
```

## 9. 验证标准

- [ ] `~/.hermes/plugins/superpowers-injection/` 目录存在
- [ ] `~/.hermes/plugins/codegraph-context/` 目录已删除
- [ ] `config.yaml` 中 `enabled` 列表更新为 `['superpowers-injection']`
- [ ] 重启后 plugin 加载日志无错误
- [ ] 发送测试消息，下一轮 LLM 响应中能正确引用入口守门员、4 阶段流程等 SKILL.md 关键内容（无需主动 skill_view）
- [ ] ruff check plugin 文件（基础语法）
- [ ] plugin 异常时不中断主循环（手动构造异常验证）

## 10. 提交消息模板

```
替换 codegraph-context plugin 为 superpowers-injection plugin

目的：弱模型 agent 经常跳过 skill 加载（AGENTS.md 入口守门员曾踩坑），
改为系统级强制注入 superpowers-workflow skill 主文件（38KB/697行）到
每次 LLM call 的上下文。

变更：
- 删除 ~/.hermes/plugins/codegraph-context/（旧 plugin）
- 新建 ~/.hermes/plugins/superpowers-injection/（新 plugin）
  - plugin.yaml：声明 pre_llm_call hook
  - __init__.py：hook 注册
  - skill_injector.py：SKILL.md 注入逻辑（含缓存）
- ~/.hermes/config.yaml：plugins.enabled 从 codegraph-context 改为 superpowers-injection

效果：
- 注入量：~9-10K token/call（vs codegraph 6-8K/call）
- 零合规要求：agent 不再需要主动 skill_view('superpowers-workflow')
- 完整 SKILL.md 内容（含入口守门员、4阶段流程、15 条精选 pitfall、Skill 协作矩阵）
- 保留 workspace 感知 + try/except 崩溃保护

后续优化（v2.0 范围）：
- 根据用户消息判断"是否开发任务"，决定注入完整骨架 vs 精简提醒
- references 索引按需 skill_view 加载
```

## 11. 关联规范引用

- **PROJECT.md 弱模型防御规则 #12（Design-First）**：本次涉及 1+3+1 = 5 个文件改动，先提交 design.md 审核
- **PROJECT.md 规则 #5（数据驱动）**：基于实证——"弱模型 agent 经常跳过 skill 加载"是项目历史教训
- **superpowers-workflow §Anti-Rationalization**：用户的判断"codegraph 没必要"是数据驱动决策，符合方法论