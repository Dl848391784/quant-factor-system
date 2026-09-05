# test_cases/test_conventions_inject.py
"""conventions_inject.py 单元测试：漂移加载/格式化/过期判定/容错。对应 designs/convention_mining_design.md。"""

import importlib.util
import io
import json
import sqlite3
import sys
from pathlib import Path


HOOK_PATH = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "conventions_inject.py"
spec = importlib.util.spec_from_file_location("conventions_inject", HOOK_PATH)
INJECT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(INJECT)


def _fixture_db(tmp_path, drifts=1, commit="abc123"):
    db = tmp_path / "conventions.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conventions (
          id INTEGER PRIMARY KEY, dimension TEXT NOT NULL, subject TEXT NOT NULL,
          statement TEXT NOT NULL, source TEXT NOT NULL, sample_size INTEGER NOT NULL,
          compliance REAL, drift INTEGER NOT NULL DEFAULT 0, evidence TEXT NOT NULL,
          generated_at TEXT NOT NULL, commit_hash TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.execute(
        "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
        " compliance, drift, evidence, generated_at, commit_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("d3_style", "H11 日志风格", "f-string 7 处 vs 惰性 143 处", "doc_declared", 150,
         0.95, drifts, "[]", "2026-09-05T00:00:00", commit),
    )
    conn.execute("INSERT INTO meta VALUES ('commit_hash', ?)", (commit,))
    conn.commit()
    conn.close()
    return db


def test_load_and_format_with_drift(tmp_path):
    db = _fixture_db(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    drifts, total = INJECT._load(conn)
    conn.close()
    assert total == 1 and len(drifts) == 1
    text = INJECT._format(drifts, total, gap=None)
    assert "H11 日志风格" in text and "⚠️" in text and "cvx" in text


def test_format_none_when_clean(tmp_path):
    db = _fixture_db(tmp_path, drifts=0)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    drifts, total = INJECT._load(conn)
    conn.close()
    assert drifts == []
    assert INJECT._format(drifts, total, gap=2) is None  # 无漂移且未过期 → 不注入
    assert INJECT._format(drifts, total, gap=9) is not None  # 过期 → 注入过期提示


def test_main_injects_and_never_blocks(tmp_path, monkeypatch):
    db = _fixture_db(tmp_path)
    monkeypatch.setattr(INJECT, "CONV_DB", db)
    monkeypatch.setattr(INJECT, "_commit_gap", lambda root, base: 1)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "改一下日志"})))
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    assert INJECT.main() == 0
    payload = json.loads(buf.getvalue())
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "H11 日志风格" in ctx


def test_main_silent_on_missing_db(tmp_path, monkeypatch):
    monkeypatch.setattr(INJECT, "CONV_DB", tmp_path / "nope.db")
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    assert INJECT.main() == 0
    assert buf.getvalue() == ""
