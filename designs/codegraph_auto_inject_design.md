# Design: 分析类 codegraph 自动注入（瘦档）

> **任务**：用户提问时自动把 codegraph 真实调用结构注入上下文，抵消分析类 fabrication（讲"X 调用 Y"时凭记忆编造）。
> **日期**：2026-07-22
> **授权依据**：用户确认"分析类也该自动注入"+ 成本可接受（瘦档 ~100-300 token/次，见 §成本）。
> **关联**：`designs/codegraph_enforcement_gate_design.md`（门禁 H15，挡盲改）；本设计是它的**正交补充**--门禁管 tool call，注入管文本断言的 ground truth。
> **范围**：仅新增 `.claude/hooks/codegraph_inject.py` + 改 `.claude/settings.json` 注册。不改现有 gate/audit、不改业务代码、不改规范规则文本。

## What

新增 **UserPromptSubmit hook**：每次用户提问时，从提问文本抽取 Python 标识符，查 codegraph db，把匹配到的 symbol 位置信息（瘦档：name/kind/file_path:start_line，**不含代码体、不含签名展开**）注入上下文。

| 维度 | 取值 | 理由 |
|---|---|---|
| 触发点 | UserPromptSubmit（用户提问时）| 分析类 fabrication 多发生在无 tool call 的纯文本回答，PreToolUse 够不着 |
| 注入量 | 瘦档：每符号 ~60 字节，≤10 符号 ≈ 600 字节 ≈ 150 token | 实测 CLI query 含签名 9KB 太肥；直查 db 取 3 列可控 |
| 相关性 | 正则抽 snake_case 标识符（`[a-z][a-z0-9_]{2,}`）| 实测从中文提问精准抽出函数名；Python 项目符号多 snake_case |
| 容错 | 抽不到标识符 / db 缺失 / FTS5 无命中 -> exit 0 不注入 | hook 协议字段不确定，宁纵勿枉，绝不报错打断用户 |

## Why（根因 + 为何瘦档）

**根因**：`codegraph_enforcement_gate_design.md` 的 H15 门禁只在 tool call 触发，**够不着我在文本里编造调用关系**（fabrication 住在文本里，不经过 hook）。用户最早担心的正是这种。注入把 ground truth 摆到面前，从源头降低编造概率。

**为何瘦档**：实测（2026-07-22）--
- `codegraph query <sym>` 去 ANSI 后 ~9KB（含签名展开）≈ 3000 token/符号，肥档
- 直查 `nodes` 表取 `name/kind/file_path:start_line`，每条 ~60 字节 ≈ 15 token/符号
- spec_bridge 行 89 记的 ~38KB/call 大概是肥档量级，故当年嫌贵
- 瘦档：10 符号 ≈ 150 token/次，50 次/天 ≈ 7500 token，可忽略

## How

### 文件清单（2 个，单批，≤3 文件 ≤200 行）

| # | 文件 | 作用 |
|---|---|---|
| 1 | `.claude/hooks/codegraph_inject.py` | UserPromptSubmit：抽标识符 -> 查 db -> 注入 |
| 2 | `.claude/settings.json` | 加 UserPromptSubmit 注册（现有 PreToolUse/PostToolUse 保留）|

### inject.py 流程

```
1. 读 stdin JSON，取 prompt 文本（字段名尝试 prompt/prompt_text；解析失败 exit 0）
2. 正则抽 snake_case 标识符：[a-z][a-z0-9_]{2,}
   - 过滤：去停用词（如 "the", "for", "ic" 单独过短词；保留 ≥4 字符或含下划线的）
   - 去重，限前 10 个
3. db 缺失或无 .codegraph -> exit 0 不注入
4. 对每个标识符，sqlite3 查 nodes（精确 name 匹配优先）+ nodes_fts（模糊）：
   SELECT name, kind, file_path, start_line FROM nodes WHERE name = ? LIMIT 3
   UNION 若无精确命中，SELECT name, kind, file_path, start_line FROM nodes_fts WHERE nodes_fts MATCH ? LIMIT 3
5. 汇总命中（≤10 条），格式化为瘦档文本：
   "## codegraph 自动注入（H15 证据源，瘦档；断言须与此一致）
   - <name> (<kind>) - <file_path>:<start_line>
   - ...
   ⚠️ 以上为 db 索引真实结构，跨文件调用/影响面断言须与此对齐。"
6. 以结构化 JSON 输出（UserPromptSubmit 注入协议，2026-07-22 改）：
   {"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"<瘦档文本>"}}
   exit 0。**裸 stdout 不被投递进模型上下文**（端到端实测：重启后提问模型未见注入），
   必须用 additionalContext 字段。无命中/无标识符/db 缺失 -> 空 stdout exit 0（不输出 JSON）。
7. 留痕：每个返回点写一行到 .claude/.cg_inject.log（status|prompt_len|idents|hits），
   用于确认 UserPromptSubmit 是否真被 Claude Code 调用（观测性，非注入路径）。
```

### settings.json（追加 UserPromptUse）

```json
"UserPromptSubmit": [{
  "hooks": [{ "type": "command", "command": "python3 .claude/hooks/codegraph_inject.py" }]
}]
```

## Don't

- ❌ 不注入代码体/签名展开（肥档，~3000 token/符号）
- ❌ 不阻断（exit 0 only；UserPromptSubmit 不该挡用户提问）
- ❌ 不依赖 hook 协议具体字段名（容错：解析失败静默 exit 0）
- ❌ 不改现有 gate.py/audit.py（正交，互不影响）
- ❌ 不预读全库（只查抽到的标识符）

## When

每次用户提问触发。抽不到标识符（纯闲聊/无代码内容）-> 静默不注入。

## Verify

- [x] `pytest test_cases/test_codegraph_inject.py`：9 passed（2026-07-22，JSON 改后仍全过）
- [x] 脚本级 JSON 输出：`json.loads` 通过，`hookSpecificOutput.additionalContext` 含瘦档 + symbol + delta.py（2026-07-22）
- [x] 脚本级静默：无标识符/db 缺失/非 JSON stdin -> 空 stdout exit 0（2026-07-22）
- [x] 注入量：JSON 包封后单符号 348B、4 符号 591B，≤600 瘦档达标（2026-07-22 实测）
- [x] 留痕日志：`.cg_inject.log` 记录每次调用 status/idents/hits（脚本级，2026-07-22）
- [x] **端到端 JSON 投递（已验证）**：会话 transcript 出现 `attachment.type=hook_additional_context`、content 含「## codegraph 自动注入...delta.py:87」、hookEvent=UserPromptSubmit（L258，2026-07-22）。对比 L6/L112 旧裸 stdout 为 `hook_success` 未注入，证明 JSON 修复必要且生效。
- [x] **触发留痕（已验证）**：`.cg_inject.log` 有真实提问触发记录（`status=injected`，2026-07-22 14:53）
- [ ] **模型可见性**（未 100% 证实）：注入进入消息数组（transcript 证明），但是否渲染进模型可见上下文无法从模型侧确认；A 方案复述兜底。

## 运行约定（A 方案，2026-07-22 用户确认）

重启会话使 `settings.json` 的 UserPromptSubmit 注册生效后：
- **显式复述**：assistant 每轮回答前，把注入的「## codegraph 自动注入」段落原样复述出来作为证据源，让用户在对话主区可见、可审计。
- 注入本身只喂真不验断言（§风险 #4）；可见性靠复述补上，对齐 H15「跨文件断言必附证据」。
- 若该轮注入为空（无标识符/db 缺失），不强行编造段落，正常作答。
- **前提**：注入生效依赖 JSON additionalContext 投递（2026-07-22 H1 修复），端到端待重启验证（见 §Verify 末两项）。未验证通过前，assistant 用手动跑 hook 产出等价段落作 fallback。

## 成本（实测 2026-07-22）

- 瘦档：~150 token/次（10 符号 × 15 token）
- 50 次/天提问 ≈ 7500 token
- 长 20 轮会话累计 ≈ 5k-20k token（随 cache TTL 波动）
- 对比肥档（context 含代码）：~3000 token/次，长会话 100k+，本次明确不选

## 风险与已知前提

1. **hook 协议端到端已验证**（2026-07-22，经会话 transcript 铁证）：
   - 脚本级：`echo '{"prompt":"..."}' | python3 .claude/hooks/codegraph_inject.py` 输出合法 JSON（`json.loads` 通过，单符号 348B）。
   - **端到端铁证（会话 transcript）**：`~/.claude/projects/<proj>/<sid>.jsonl` 记录每个含标识符的提问后产生 `type=attachment` 的注入消息。对比三时点（同会话）：
     - L6/L112（旧裸 stdout 代码）：`attachment.type=hook_success`，含 `stdout`/`exitCode` 字段 = **裸 stdout 被当 hook 成功输出记录，未作为 additionalContext 注入**。
     - L258（新 JSON 代码）：`attachment.type=hook_additional_context`，`content=["## codegraph 自动注入...delta.py:87"]` + `hookEvent=UserPromptSubmit` = **正确注入消息数组**。
   - 结论：H1（裸 stdout 不被投递，需结构化 JSON additionalContext）已证实并修复；JSON 修复后注入生效。
   - **触发确认（H2 排除）**：`.claude/.cg_inject.log` 有真实提问触发记录（`status=injected`）；transcript 的 L6/L112/L258 三条 attachment 证明 UserPromptSubmit 确被 CC 调用。
   - **可见性 nuance（唯一未 100% 证实）**：transcript 证明注入进入消息数组（binary: `H.messages.push(hook_additional_context...)`），但无法从模型侧确认它是否渲染进模型*可见*上下文 vs 仅作 isMeta 内部记录。A 方案靠 assistant 显式复述兜底可见性。
   - **时序坑**：改 `settings.json` 需重启会话才生效；改 `inject.py` 同理需重启加载新代码。
2. **相关性靠正则**：纯中文提问无英文标识符时抽不到，不注入（可接受--无代码内容的问题不需结构注入）。启发式，非精确。
3. **索引新鲜度**：沿用 gate 的 72h 警告逻辑（注入时若过期附一行警告，不阻断）。
4. **与 H15 门禁正交**：注入只喂真，不验断言；验断言靠未来"事后证据链审核"（依赖未知能力：审查输出文本的 hook，待核实）。
