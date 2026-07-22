---
name: workflow-creation
description: 建工作流系统 + 运行诊断。触发：新建/改工作流、ac-ark --workflow、阶段不推进、注入没生效、/wf 报错、worktree hook 失效、模型否认收到注入。
version: 1.0
---

# workflow-creation

> 建工作流 + 运行诊断手册。自包含。真源 = `designs/workflow-system-design.md`。
> 核心铁律：**worktree 内 `.claude/` 文件是 git checkout 快照，主仓库改动需 commit + 重建 worktree 才同步**。本 skill 大半诊断结论都源于此。

## 0. 系统全景（5 秒理解）

```
ac-ark --workflow <name>  ─►  scripts/workflow/wf-launch.sh
                                  │ 建 git worktree(.claude/worktrees/<name>, 分支 wf/<name>)
                                  │ + state.json(.claude/workflows/<name>/) + 钉 session
                                  │ 起 claude: --settings(per-wf) --append-system-prompt-file(phase-rules) --session-id
                                  ▼
   原生 claude TUI（worktree 内）
     ├─ workflow_phase.py (UserPromptSubmit) → 注入「## WORKFLOW 当前阶段」到 hook_additional_context attachment
     ├─ workflow.md (output style)           → 引导模型输出 ## PHASE: <phase> [n/5] 横幅
     ├─ workflow_advance.py (Stop)          → 检 ### PHASE_DONE 标记 → 闸门判定 → 推进 state
     └─ /wf status|next|back|jump|gate|done → 手动控制
```

**5 阶段**：understand 理解和求证问题（禁改源码）-> plan 生成执行计划（禁改源码）-> execute 执行 -> review 审核结果 -> evolution 进化。显示用中文名，逻辑层（state/PHASE_DONE/jump）用英文标识。
**推进**：自动 + 闸门。`understand->plan`、`plan->execute` 需 `/wf gate` 放行；其余自动推进。

## 1. 建工作流 / 改工作流

### 1.1 新建一个工作流（用户侧）
```bash
ac-ark --workflow <name>              # 新建（停在 understand）
ac-ark --workflow <name> --resume      # 续接
ac-ark --workflow list                 # 列举
ac-ark --workflow <name> --done        # 归档（删 worktree+分支+元数据）
```
- `<name>` 仅小写字母/数字/连字符/下划线，≤64（`wf-lib.sh` 校验）。
- 必须在 repo 内运行（launcher 用 `git rev-parse` 反查主仓库根）。

### 1.2 改工作流脚本/hook/command 后**必须重建 worktree**
worktree 内的 `.claude/hooks/*.py`、`.claude/output-styles/*.md`、`.claude/commands/*.md`、`scripts/workflow/*.sh` 都是 **git checkout 快照**。主仓库改这些文件后，**已有 worktree 内不更新**。
- 改完 → `git commit` → 退出会话 → `ac-ark --workflow <name> --done` → `ac-ark --workflow <name>` 重建。
- **唯一例外**：per-wf `settings.json`（在主仓库 `.claude/workflows/<name>/`，gitignored，非快照）改了即时生效，但会话需重启加载。

### 1.3 关键文件职责（改前必读）
| 文件 | 职责 | 改动影响 |
|---|---|---|
| `scripts/workflow/wf-launch.sh` | 建/续 worktree+state+settings，起 claude | 启动行为 |
| `scripts/workflow/wf-lib.sh` | 阶段定义+state 读写+`wf_write_settings`+路径解析 | state/settings 生成 |
| `scripts/workflow/wf-cmd.sh` | `/wf` 子命令逻辑 | 手动控制 |
| `scripts/workflow/phase-rules.md` | append-system-prompt，各阶段行为规则 | 模型阶段行为 |
| `.claude/hooks/workflow_phase.py` | UserPromptSubmit 注入当前阶段 | 注入内容 |
| `.claude/hooks/workflow_advance.py` | Stop 检 PHASE_DONE 推进 | 自动推进 |
| `.claude/output-styles/workflow.md` | output style，横幅格式+遵从引导 | 显示格式 |
| `.claude/commands/wf.md` | `/wf` slash 命令入口 | 命令路由 |

## 2. ⚠️ 运行诊断手册（按症状查）

### 症状 A：注入没生效（`.wf_phase.log` 无 `injected` 行，或模型说"没有注入"）

**先分清两种"没生效"**：
- A1. hook **没被调用**（日志无任何新行）
- A2. hook **被调用了**（日志有 `injected`/`no_state`），但模型说没收到

**A1 诊断**：检查 per-wf settings.json 的 hook command 是否**主仓库绝对路径**。
```bash
python3 -c "import json;d=json.load(open('.claude/workflows/<name>/settings.json'));print([h['command'] for v in d['hooks'].values() for g in v for h in g['hooks']])"
```
- 若是相对路径 `python3 .claude/hooks/x.py` → **bug**（worktree cwd 下解析到 worktree 内，可能缺文件或 parents[2] 错）。修复：`wf_write_settings` 必须用 `$WF_REPO_ROOT/.claude/hooks/x.py`（见 design §10）。
- 若是绝对路径但 worktree 内缺 `codegraph_gate.py`/`codegraph_audit.py`（未跟踪文件不进 worktree）→ 必须用主仓库绝对路径引用主仓库内文件。

**A2 诊断（关键，易误判）**：注入走 `hook_additional_context` **attachment**，**不在 user message 文本里**。别在 user message 找注入。
```bash
# 查 session jsonl 的 attachment 行
python3 -c "
import json
for line in open('~/.claude/projects/<proj>/<sid>.jsonl'.replace('~',__import__('os').path.expanduser('~'))):
    ev=json.loads(line)
    if ev.get('type')=='attachment':
        a=ev.get('attachment',{})
        if a.get('type')=='hook_additional_context': print('✓ 注入已投递:', str(a.get('content',[''])[0])[:100])
"
```
- attachment 有 `## WORKFLOW 当前阶段` → **注入成功**，问题在模型（见症状 D）。
- attachment 无 → hook 没输出 additionalContext，查 `workflow_phase.py` 是否走了 `no_state` 分支（state 没读到，见症状 C）。

### 症状 B：阶段不自动推进（`### PHASE_DONE` 后没进下一阶段）

**诊断**：看 `.wf_advance.log`。
```bash
tail -5 .claude/.wf_advance.log
```
- `no_done_marker|tlen=0` → Stop hook 跑了但 transcript 读出空。**`-p` 模式正常现象**（-p 下 transcript 字段可能空）；交互式应正常。别用 `-p` 验证推进。
- `no_done_marker|tlen=N`（N>0）→ transcript 有内容但没 PHASE_DONE 标记。模型没输出标记（可能严格守"目标达成才输出"规则，给了空任务）。看 assistant 回复有没有 `### PHASE_DONE:`。
- `gated_block|phase=understand` → **闸门正常阻断**（understand/plan 需 `/wf gate` 放行）。这是设计行为，非 bug。
- `no_state` → state 没读到（见症状 C）。

**验证推进**：用真实交互式会话（非 `-p`），给模型一个**可完成的小 execute 任务**（如"读 X 文件确认存在后输出 ### PHASE_DONE: execute"）。`-p` 模式 transcript 不可靠。

### 症状 C：`/wf status` 或 hook 报 "state.json 缺失"

**根因**：`WF_REPO_ROOT` 解析到 worktree 根（非主仓库根），state 在主仓库 `.claude/workflows/<name>/`。
- 报错路径含 `worktrees/<name>/.claude/workflows/` → 确认此根因。
- **修复已落地**：`wf-lib.sh` 的 `WF_REPO_ROOT` 用 `git rev-parse --git-common-dir` 反查主仓库根。若仍报错，检查 `wf-lib.sh` 是否含此逻辑（worktree 内可能是旧版快照，见 §1.2 重建）。
- **`/wf` 报错专项**：slash 命令 `wf.md` 必须用 git 反查主仓库根调主仓库 `wf-cmd.sh`（绝对路径），不能用 worktree 内相对路径 `bash scripts/workflow/wf-cmd.sh`。
- **fallback 陷阱**：`WF_REPO_ROOT` 若含**两行**（主仓库根重复）→ `$(A || B && C)` 的 `||/&&` 优先级 bug，git 成功后仍执行 `&& pwd`。修复：拆成 `if` 判断（见 commit 5f5cc0f）。

### 症状 D：模型否认收到注入（说"没有 hook 注入"/"不在工作流中"）

**判定**：先按症状 A2 确认 attachment 已投递。若 attachment 有注入但模型否认 → 模型遵从问题。
- **ark-code-latest 已知行为**：能读 `hook_additional_context` attachment（会引用其中的 symbol/阶段名），但有时**逻辑上否认注入存在**。
- **output style 措辞放大**：旧版"若本轮无注入...按正常风格回复"引导模型倾向判断"无注入"。修复：output style 明确"注入在 attachment，见 `## WORKFLOW 当前阶段` 段落即须遵循，禁止声称没有注入"（见 commit ffa2029）。
- **改善验证**：重建 worktree（含新版 output style）后，模型应不再否认。可能仍不严格输出 `## PHASE:` 横幅格式，但会用自然语言准确报告阶段+闸门+推进方式 → 功能达标。

### 症状 E：管道 `printf | claude` 测试出 `Execution error`

**这是测试方法伪问题，非工作流 bug**。管道 EOF 触发 claude 异常。真实 TTY 交互不受影响。
- **别用管道模拟交互会话验证**。用真实 TTY 或 `-p`（注意 -p 下 transcript 不可靠，见症状 B）。

### 症状 F：置顶阶段清单没建 / 不同步（5 阶段任务不显示或状态错）

置顶清单机制：`workflow_phase.py` 每轮注入「任务清单目标状态」块，模型用 `TaskCreate`/`TaskUpdate` 镜像。源真值是 `state.json`，任务只做镜像。
- **首轮无清单**：模型没执行 TaskCreate。检 `.wf_phase.log` 有 `injected` 行 -> 注入到位，问题在模型；`.claude/output-styles/workflow.md` 未加载则强规则失效（检 per-wf settings.json 的 `outputStyle: workflow`）。
- **清单状态与当前阶段不符**：读注入段「任务清单」5 行看 hook 给的目标状态，与实际 TaskList 对比。目标错 -> hook bug（查 `state.json` 的 `index`）；目标对但清单错 -> 模型漏 TaskUpdate，用 `/wf status` 促模型下一轮对齐。
- **execute 工作子任务把 5 阶段任务顶掉**：模型违规改了 5 阶段任务的 subject/顺序。规则：工作子任务追加在下方，5 个阶段任务全程保留。

## 3. 排查方法论（systematic-debugging 适配）

排查工作流问题按此顺序，避免在管道假象上浪费时间：

1. **先看日志，别猜**：`.wf_phase.log`（注入）、`.wf_advance.log`（推进）、`.cg_inject.log`（codegraph 对照）。日志写哪？主仓库 `.claude/`（修复后）；若 worktree 内有 `.wf_*.log` → 旧版 bug（hook PROJECT_ROOT 指错，见 design §10）。
2. **分清"没调用"vs"调用了没投递"vs"投递了模型不遵循"**：三层次，日志+attachment 分别诊断（症状 A1/A2/D）。
3. **看 session jsonl 的 attachment**：注入真相在 `hook_additional_context` attachment，不在 user message。
4. **worktree 快照优先怀疑**：任何"改了不生效"，先想 worktree 内是不是旧版快照（§1.2）。
5. **验证用真实交互，别用管道/-p**：管道有 Execution error（症状 E），-p transcript 不可靠（症状 B）。

## 4. 不要做的事

- ❌ **用 worktree 相对路径调脚本/hook**：`bash scripts/workflow/wf-cmd.sh`、`python3 .claude/hooks/x.py` 在 worktree cwd 下解析到 worktree 内旧版快照。必须主仓库绝对路径。
- ❌ **靠 `parents[2]` 在 worktree 内找主仓库根**：worktree 内 hook 文件的 `parents[2]` = worktree 根。用 `git rev-parse --git-common-dir` 反查。
- ❌ **用 `printf | claude` 验证交互行为**：Execution error 伪问题。
- ❌ **用 `-p` 验证推进**：-p 下 transcript 可能空，Stop hook 读不到 PHASE_DONE。
- ❌ **在 user message 文本里找注入**：注入在 `hook_additional_context` attachment。
- ❌ **改脚本/hook 不 commit 就期望生效**：worktree 是快照，必须 commit + 重建。
- ❌ **`WF_REPO_ROOT` 用 `$(A || B && C)` 单行**：优先级 bug 致两行拼接。

## 5. 触发关键词速查

- "建工作流 / 新建工作流 / ac-ark --workflow" → §1
- "注入没生效 / 阶段没注入 / 模型说没注入" → §2 症状 A/D
- "阶段不推进 / PHASE_DONE 没推进" → §2 症状 B
- "/wf 报错 / state 缺失 / state.json not found" → §2 症状 C
- "worktree 内 hook 失效 / 改了不生效" → §1.2 + §2 症状 A1
- "模型否认注入 / 不输出横幅" → §2 症状 D
- "Execution error / 管道测试" → §2 症状 E
