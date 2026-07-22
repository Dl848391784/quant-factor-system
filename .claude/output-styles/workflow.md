---
name: workflow
description: 5 阶段工作流显示层。每条响应首行输出阶段横幅 ## PHASE: <phase> [n/5]，保持精炼，不在可见文本写冗长推理。
---

# Workflow Output Style

你正处于 5 阶段工作流中。当前阶段由 UserPromptSubmit hook 注入（见「## WORKFLOW 当前阶段」段落）。本 output style 规定你的**可见输出格式**。

## 硬性要求

1. **每条响应首行**输出阶段横幅，格式严格如下（取代普通问候/寒暄）：
   ```
   ## PHASE: <phase> [n/5]
   ```
   - `<phase>` = 当前阶段名（understand/plan/execute/review/evolution）
   - `n` = 阶段序号（understand=1 … evolution=5）
   - 取当前阶段来自 hook 注入段落。若本轮无注入（非工作流会话），不输出横幅、按正常风格回复。

2. **保持精炼**：可见文本只放结论与动作，不写冗长推理过程。
   - 推理归思考块管（TUI 独立渲染）；可见文本是给用户读的结论。
   - 调查类：先给结论，再附关键证据（file:line / codegraph 输出 / 测试输出），不流水账。

3. **工具动作可见**：正常使用 Read/Grep/Edit/Bash 等工具，工具调用本身会在 TUI 显示，无需在文本里复述每个工具调用。

4. **阶段完成标记**：当当前阶段目标真正达成时，在回复**末尾**单独一行输出：
   ```
   ### PHASE_DONE: <phase>
   ```
   - 只在目标达成时输出；未达成绝不输出。
   - 此标记供 Stop hook 检测推进（闸门阶段不会自动进下一阶段）。

## 各阶段输出侧重

- **understand**：重述你对真实问题的理解 + 边界 + 成功标准，问澄清问题（用 AskUserQuestion 当不确定）。产出 understand.md。
- **plan**：给方案 + 步骤 + 验证方法，不写代码体。产出 plan.md。
- **execute**：改代码、跑测试、commit。每步附证据（测试输出/commit hash）。
- **review**：给 solved/partial/not 判定 + 对照成功标准的证据。产出 review.md。
- **evolution**：给沉淀了什么（memory/skill/design 更新）。产出 evolution.md。

## 示例

```
## PHASE: execute [3/5]

按 plan.md 步骤 1 修正 turnover surge 计算：改用 log 差分替代差值，避免 NaN 传播。

[执行 Edit / Bash pytest …]

3 个测试通过。commit: a1b2c3f

### PHASE_DONE: execute
```
