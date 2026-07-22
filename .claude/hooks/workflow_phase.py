#!/usr/bin/env python3
"""
UserPromptSubmit hook：工作流阶段注入。

对应设计 designs/workflow-system-design.md §3。
每轮用户提问时，读当前工作流 state.json，注入「当前阶段 + 允许/禁止动作 + 完成标记格式」。

仿 codegraph_inject.py 范式：
- additionalContext 协议注入（裸 stdout 不被投递）。
- 容错：stdin 解析失败 / state.json 缺失 / cwd 不在 worktree -> exit 0 静默不注入。
- UserPromptSubmit 永不阻断（exit 0 only）。
- 异常留痕 .claude/.wf_phase.log（观测性，仿 .cg_inject.log）。
"""

import json
import sys
import time
from pathlib import Path


# 主仓库根：hook 经 per-wf settings.json 以主仓库绝对路径调用（非 worktree 相对路径），
# 故 __file__.parents[2] = 主仓库根，state.json 在主仓库 .claude/workflows/ 下，正确读到。
# （若改回 worktree 相对路径，parents[2] 会指向 worktree 根，读不到 state。见 design 根因修复。）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WF_META_ROOT = PROJECT_ROOT / ".claude" / "workflows"
WF_WT_ROOT = PROJECT_ROOT / ".claude" / "worktrees"
PHASE_LOG = PROJECT_ROOT / ".claude" / ".wf_phase.log"

# 5 阶段顺序（与 wf-lib.sh WF_PHASES 一致；hook 独立持有，避免 source bash）
PHASES = ["understand", "plan", "execute", "review", "evolution"]

# 各阶段规则（注入给模型的"允许/禁止/产物/推进"四要素）
PHASE_RULES = {
    "understand": {
        "goal": "理清真实问题（问题背后要解决的本质，非字面请求）",
        "allow": "Read/Grep/Glob/codegraph 查证/AskUserQuestion 澄清",
        "deny": "Edit/Write 任何源码",
        "artifact": "understand.md（真实问题重述 + 边界 + 成功标准）",
        "advance": "闸门：完成后需用户 /wf gate 放行才进 plan",
    },
    "plan": {
        "goal": "针对真实问题设计实现方案",
        "allow": "understand 的工具 + 起草 design.md(H8)",
        "deny": "改源码",
        "artifact": "plan.md（方案 + 步骤 + 验证方法）",
        "advance": "闸门：完成后需用户 /wf gate 放行才进 execute",
    },
    "execute": {
        "goal": "按计划改代码（守 H9/H11/H15/no silent fallback）",
        "allow": "全工具集；改已有 .py 前先 codegraph impact（H15）",
        "deny": "—",
        "artifact": "代码 + commit + 测试通过",
        "advance": "自动推进到 review（无闸门）",
    },
    "review": {
        "goal": "对照真实问题判定 solved/partial/not（证据 file:line / 测试输出）",
        "allow": "评审 subagent(Agent)/codegraph impact/跑测试",
        "deny": "改实现",
        "artifact": "review.md（结论 + 证据）",
        "advance": "自动推进到 evolution（无闸门）",
    },
    "evolution": {
        "goal": "沉淀经验（写 memory 事实/更新 skill/补 design）",
        "allow": "写 memory/调 skill/补 design",
        "deny": "—",
        "artifact": "evolution.md + memory 写入",
        "advance": "终结（输出 PHASE_DONE: evolution 后工作流结束）",
    },
}


def _extract_prompt(payload: dict) -> str:
    """从 hook stdin payload 取提问文本（容错：试多个字段名）。"""
    for key in ("prompt", "prompt_text", "user_prompt", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    nested = payload.get("user_prompt", {})
    if isinstance(nested, dict):
        for key in ("prompt", "text", "content"):
            val = nested.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def _resolve_workflow_name(payload: dict) -> str | None:
    """从 cwd（worktree 路径）反查工作流名。

    worktree 路径形如 <repo>/.claude/worktrees/<name>。
    cwd 由 hook payload 提供（字段名容错）；缺失则读 os.getcwd()。
    """
    cwd = ""
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            cwd = val
            break
    if not cwd:
        cwd = str(Path.cwd())
    # 期望 cwd = .../.claude/worktrees/<name>
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _load_state(name: str) -> dict | None:
    """读 .claude/workflows/<name>/state.json，缺失/损坏返回 None。"""
    f = WF_META_ROOT / name / "state.json"
    if not f.exists():
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _log_invocation(status: str, name: str = "", phase: str = "", prompt_len: int = 0) -> None:
    """留痕 UserPromptSubmit 触发（观测性）。失败静默。"""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        with open(PHASE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}|wf={name}|phase={phase}|prompt_len={prompt_len}\n")
    except OSError:
        pass


def _format_injection(state: dict) -> str:
    """格式化阶段注入文本（当前阶段 + 规则四要素 + 完成标记格式）。"""
    name = state.get("name", "?")
    phase = state.get("phase", "understand")
    idx = state.get("index", 1)
    gate = state.get("gate", "pending")
    rules = PHASE_RULES.get(phase, {})
    try:
        total = len(PHASES)
    except Exception:
        total = 5
    lines = [
        "## WORKFLOW 当前阶段",
        f"工作流: {name} | 阶段: **{phase}** [{idx}/{total}] | gate: {gate}",
        f"- 目标: {rules.get('goal', '')}",
        f"- 允许: {rules.get('allow', '')}",
        f"- 禁止: {rules.get('deny', '')}",
        f"- 阶段产物: {rules.get('artifact', '')}",
        f"- 推进: {rules.get('advance', '')}",
        "完成本阶段后，回复末尾单独一行输出: `### PHASE_DONE: " + phase + "`",
        "（仅当阶段目标真正达成时输出；闸门阶段不会自动推进，需 /wf gate 放行）",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        _log_invocation("malformed_stdin")
        return 0
    if not isinstance(payload, dict):
        _log_invocation("non_dict")
        return 0

    prompt = _extract_prompt(payload)
    name = _resolve_workflow_name(payload)
    if not name:
        _log_invocation("no_worktree_cwd", prompt_len=len(prompt))
        return 0  # 不在 worktree 内（普通会话）-> 不注入

    state = _load_state(name)
    if not state:
        _log_invocation("no_state", name=name, prompt_len=len(prompt))
        return 0  # state 缺失 -> 不注入（可能未走 launcher）

    context = _format_injection(state)
    out = json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}},
        ensure_ascii=False,
    )
    sys.stdout.write(out)
    _log_invocation("injected", name=name, phase=state.get("phase", ""), prompt_len=len(prompt))
    return 0


if __name__ == "__main__":
    sys.exit(main())
