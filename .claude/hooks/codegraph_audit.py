#!/usr/bin/env python3
"""
PostToolUse(Bash) 留痕：记录每次 codegraph 结构查询到会话 audit log。

对应设计 designs/codegraph_enforcement_gate_design.md（H15）。
gate.py 读本 log 判断"本会话是否查过结构"。

只留痕，永不阻断（exit 0）。
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = PROJECT_ROOT / ".claude" / ".cg_audit"

TRACKED_SUBCOMMANDS = ("callers", "callees", "impact", "affected", "context", "query")

# 匹配 `codegraph <subcmd> ...`（容忍前导路径/环境变量，如 /home/.../codegraph）
_CMD_RE = re.compile(
    r"(?:^|\s)(?:[\w/.-]+/)?codegraph\s+(" + "|".join(TRACKED_SUBCOMMANDS) + r")\b",
)


def _session_id() -> str:
    sid = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return sid or "_fallback"


def _parse_subcmd(command: str) -> str | None:
    """从命令字符串提取首个被留痕的 codegraph 子命令，无则 None。"""
    m = _CMD_RE.search(command or "")
    return m.group(1) if m else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    command = (payload.get("tool_input") or {}).get("command", "")
    subcmd = _parse_subcmd(command)
    if not subcmd:
        return 0  # 非 codegraph 结构查询，不留痕

    # 子命令后的首个 token 作"symbol/args"近似（够审计用，不追求精确解析）
    rest = _CMD_RE.search(command or "")
    tail = ""
    if rest:
        after = command[rest.end() :].strip()
        tail = after.split()[0] if after else ""

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    log = AUDIT_DIR / f"{_session_id()}.log"
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{ts}|{subcmd}|{tail}\n"
    try:
        with log.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        return 0  # 留痕失败不阻断 Bash（宁纵勿枉业务命令）
    return 0


if __name__ == "__main__":
    sys.exit(main())
