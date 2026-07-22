#!/usr/bin/env python3
"""
Stop hook：工作流阶段推进。

对应设计 designs/workflow-system-design.md §3。
每轮 assistant 回复结束后，读 transcript_path JSONL 取上一条 assistant 文本，
检测 `### PHASE_DONE: <phase>` 标记 -> 推进 state.json -> 闸门判定 -> 打印阶段切换横幅。

防御式（设计 §风险#1）：transcript_path 字段名/格式不确定时降级为提示用户敲 /wf next，
绝不阻断（Stop hook exit 0 only；非零会阻止会话结束，违反设计意图）。

不阻断原则：本 hook 只推进 + 打印横幅；即便检测失败也 exit 0。
闸门：understand->plan、plan->execute 需 gate=passed 才推进；否则提示用户 /wf gate。
"""

import json
import re
import sys
import time
from pathlib import Path


# 主仓库根：hook 经 per-wf settings.json 以主仓库绝对路径调用（非 worktree 相对路径），
# 故 __file__.parents[2] = 主仓库根，state.json 在主仓库 .claude/workflows/ 下，正确读到。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
WF_META_ROOT = PROJECT_ROOT / ".claude" / "workflows"
WF_WT_ROOT = PROJECT_ROOT / ".claude" / "worktrees"
ADVANCE_LOG = PROJECT_ROOT / ".claude" / ".wf_advance.log"

PHASES = ["understand", "plan", "execute", "review", "evolution"]
# 闸门：这些阶段完成后进下一阶段需 gate=passed
GATED_AFTER = {"understand", "plan"}

# 完成标记正则
DONE_RE = re.compile(r"###\s*PHASE_DONE:\s*(\w+)", re.IGNORECASE)


def _log(status: str, **kw) -> None:
    """留痕 Stop 触发（观测性）。失败静默。"""
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        parts = [f"{k}={v}" for k, v in kw.items()]
        with open(ADVANCE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts}|{status}|{'|'.join(parts)}\n")
    except OSError:
        pass


def _resolve_workflow_name(payload: dict) -> str | None:
    """从 cwd 反查工作流名（与 workflow_phase.py 一致）。"""
    cwd = ""
    for key in ("cwd", "working_dir", "current_dir"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            cwd = val
            break
    if not cwd:
        cwd = str(Path.cwd())
    parts = Path(cwd).parts
    if "worktrees" in parts:
        i = parts.index("worktrees")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _load_state(name: str) -> dict | None:
    f = WF_META_ROOT / name / "state.json"
    if not f.exists():
        return None
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(name: str, state: dict) -> None:
    f = WF_META_ROOT / name / "state.json"
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def _last_assistant_text(transcript_path: str) -> str:
    """读 transcript JSONL，取最后一条 assistant message 的文本。

    防御式：transcript_path 缺失/格式不符/解析失败 -> 返回 ""（触发降级）。
    JSONL 每行是一个 event；assistant 文本通常在 type=assistant 的 message.content[].text。
    """
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    texts = []
    try:
        with open(transcript_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 容错多种 transcript schema：找 assistant role 的 text content
                msg = ev.get("message") if isinstance(ev, dict) else None
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content")
                if isinstance(content, str):
                    texts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
    except OSError:
        return ""
    # 取最后一条非空（最近一次 assistant 回复）
    for t in reversed(texts):
        if t.strip():
            return t
    return ""


def _emit(msg: str) -> None:
    """打印阶段切换横幅到 stdout（TUI 可见）。"""
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def _advance(state: dict, name: str) -> None:
    """执行推进：更新 phase/index/gate/history。"""
    cur = state["phase"]
    idx = PHASES.index(cur)
    nxt = PHASES[idx + 1] if idx + 1 < len(PHASES) else None
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
    # 关闭当前阶段 history exit
    hist = state.get("history", [])
    if hist and hist[-1].get("exited_at") is None:
        hist[-1]["exited_at"] = now
        hist[-1]["via"] = "auto-stop"
    if nxt:
        hist.append({"phase": nxt, "entered_at": now, "exited_at": None, "via": "auto-stop"})
        state["phase"] = nxt
        state["index"] = idx + 2  # 1-based
        # 新阶段的 gate：若新阶段的前置是闸门来源（即 cur in GATED_AFTER），但本推进已是放行后，
        # 故新阶段 gate=passed（已通过）；否则新阶段 gate 取决于其自身是否是闸门目标
        state["gate"] = "passed" if cur in GATED_AFTER else "pending"
    else:
        state["gate"] = "done"  # evolution 完成终结
    state["history"] = hist
    state["updated_at"] = now
    _save_state(name, state)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        _log("malformed_stdin")
        return 0
    if not isinstance(payload, dict):
        return 0

    name = _resolve_workflow_name(payload)
    if not name:
        _log("no_worktree_cwd")
        return 0  # 普通会话，不推进

    state = _load_state(name)
    if not state:
        _log("no_state", wf=name)
        return 0

    cur = state.get("phase", "understand")

    # 读 transcript 取上一条 assistant 文本
    transcript_path = ""
    for key in ("transcript_path", "transcriptPath", "transcript"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            transcript_path = val
            break
    text = _last_assistant_text(transcript_path)

    # 检测完成标记
    m = DONE_RE.search(text)
    if not m:
        _log("no_done_marker", wf=name, phase=cur, tlen=len(text))
        return 0  # 未完成标记，不推进
    done_phase = m.group(1).lower()
    if done_phase != cur:
        _log("done_mismatch", wf=name, phase=cur, done=done_phase)
        return 0  # 标记的阶段与当前不符，不推进（防误）

    # 闸门判定
    if cur in GATED_AFTER:
        gate = state.get("gate", "pending")
        if gate != "passed":
            # 闸门未放行：不自动推进，提示用户
            _emit(
                f"\n┌─ WORKFLOW · {name} · {cur} 完成，闸门待放行 ─────────────┐\n"
                f"│ 阶段 {cur} 已完成（检测到 PHASE_DONE），但进 {PHASES[PHASES.index(cur) + 1]} 需闸门。│\n"
                f"│ 输入 /wf gate 放行，或 /wf next 强制推进。            │\n"
                f"└──────────────────────────────────────────────────────┘"
            )
            _log("gated_block", wf=name, phase=cur, gate=gate)
            return 0

    # 终结？
    if cur == "evolution":
        _emit(f"\n╔═ WORKFLOW · {name} · 已完成全部 5 阶段（evolution 终结）══╗")
        _log("finished", wf=name, phase=cur)
        state["gate"] = "done"
        state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        _save_state(name, state)
        return 0

    # 推进
    nxt_idx = PHASES.index(cur) + 1
    nxt = PHASES[nxt_idx]
    _advance(state, name)
    _emit(
        f"\n╔═ WORKFLOW · {name} · 阶段切换 ─────────────────────────════╗\n"
        f"║ {cur} [{nxt_idx}/5]  ──►  {nxt} [{nxt_idx + 1}/5]               ║\n"
        f"╚════════════════════════════════════════════════════════════╝"
    )
    _log("advanced", wf=name, frm=cur, to=nxt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
