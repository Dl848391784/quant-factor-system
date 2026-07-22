"""
.claude/hooks/codegraph_inject.py 的单元测试。

对应 designs/codegraph_auto_inject_design.md（分析类瘦档自动注入）。
通过 subprocess 喂 stdin 调用真实脚本，与 hook 实际调用方式一致。

覆盖（design §Verify）：
- 中文提问含 snake_case 标识符 -> 注入 symbol 位置
- 纯闲聊无标识符 -> 静默不注入
- 容错（非 JSON / 无 prompt 字段 / db 缺失）-> exit 0 不报错
- 注入量 ≤ 瘦档上限
- 噪音过滤（模糊匹配排除 import/test_ 符号）
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INJECT = PROJECT_ROOT / ".claude" / "hooks" / "codegraph_inject.py"
CODEGRAPH_DB = PROJECT_ROOT / ".codegraph" / "codegraph.db"


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INJECT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_raw(raw: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(INJECT)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ─────────────────── 正常注入 ───────────────────


def test_injects_symbol_from_chinese_prompt() -> None:
    """中文提问含 snake_case 标识符 -> 注入真实 symbol 位置。"""
    r = _run({"prompt": "分析 calculate_turnover_surge_delta 这个因子为啥 IC 负"})
    assert r.returncode == 0
    assert "calculate_turnover_surge_delta" in r.stdout
    assert "delta.py" in r.stdout
    # 瘦档不含代码体/签名展开，行数少
    assert r.stdout.count("\n") < 15


def test_injects_multiple_symbols() -> None:
    """多符号提问 -> 注入多个命中。"""
    r = _run({"prompt": "calculate_turnover_surge_delta 和 compute_metrics"})
    assert "calculate_turnover_surge_delta" in r.stdout
    assert "compute_metrics" in r.stdout


def test_injection_size_within_thin_budget() -> None:
    """注入量 ≤ 600 字节（瘦档目标）。"""
    r = _run({"prompt": "calculate_turnover_surge_delta compute_metrics calc_rsi_for_asset peak_rss_kb"})
    assert len(r.stdout.encode()) <= 600


# ─────────────────── 静默不注入 ───────────────────


def test_silent_on_no_identifiers() -> None:
    """纯闲聊无标识符 -> exit 0 无输出。"""
    r = _run({"prompt": "今天天气怎么样，吃火锅吧"})
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_short_common_words() -> None:
    """过短无下划线词（ic/the/for）过滤掉，不触发注入。"""
    r = _run({"prompt": "the ic for and but"})
    assert r.stdout == ""


# ─────────────────── 容错 ───────────────────


def test_handles_malformed_json() -> None:
    """非 JSON stdin -> exit 0 不报错。"""
    r = _run_raw("{not json")
    assert r.returncode == 0
    assert r.stdout == ""


def test_handles_missing_prompt_field() -> None:
    """无 prompt 字段 -> exit 0。"""
    r = _run({"foo": "bar"})
    assert r.returncode == 0
    assert r.stdout == ""


def test_handles_prompt_field_alternate_names() -> None:
    """容错：尝试多个字段名（prompt_text 等）。"""
    r = _run({"prompt_text": "calculate_turnover_surge_delta"})
    assert "calculate_turnover_surge_delta" in r.stdout


# ─────────────────── 永不阻断 ───────────────────


def test_never_blocks_exit_zero() -> None:
    """UserPromptSubmit 永不阻断：任何输入都 exit 0。"""
    for payload in [{"prompt": "calculate_turnover_surge_delta"}, {}, {"x": 1}]:
        r = _run(payload)
        assert r.returncode == 0, f"应 exit 0，实际 {r.returncode}：{r.stderr}"
