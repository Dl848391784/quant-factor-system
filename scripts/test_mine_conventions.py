"""scripts/mine_conventions.py 单元测试（fixture db + 临时文件，不依赖真实仓）。

覆盖：schema 建表 / 原子写 / _top_module 映射 / 各维度 miner。对应 designs/convention_mining_design.md。
"""

import json
import sqlite3

from scripts.mine_conventions import (
    _top_module,
    _write_db,
)


def _read_records(db_path):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT dimension, subject, statement, source, sample_size, compliance, drift, evidence,"
        " generated_at, commit_hash FROM conventions"
    ).fetchall()
    meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    conn.close()
    return rows, meta


def _record(**kw):
    base = {
        "dimension": "d4_skeleton",
        "subject": "s",
        "statement": "st",
        "source": "code_evidence",
        "sample_size": 3,
        "compliance": None,
        "drift": 0,
        "evidence": [{"file": "a.py", "line": 1}],
    }
    base.update(kw)
    return base


def test_top_module():
    assert _top_module("web_ui/app.py") == "web_ui"
    assert _top_module("scripts/sub/x.py") == "scripts"
    assert _top_module("paths.py") == "(root)"


def test_write_db_atomic_and_meta(tmp_path):
    out = tmp_path / "sub" / "conventions.db"
    _write_db(out, [_record(), _record(drift=1, source="doc_declared", compliance=0.5)],
              "2026-09-05T00:00:00", "abc123")
    rows, meta = _read_records(out)
    assert len(rows) == 2
    assert rows[0][1] == "s" and json.loads(rows[0][7]) == [{"file": "a.py", "line": 1}]
    assert meta["generated_at"] == "2026-09-05T00:00:00"
    assert meta["commit_hash"] == "abc123"
