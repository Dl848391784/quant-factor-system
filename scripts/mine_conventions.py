#!/usr/bin/env python3
"""mine_conventions - 项目约定蒸馏器（designs/convention_mining_design.md）。

从代码实证蒸馏隐性约定（隐性约定 = 代码中统计上稳定重复的模式）：
- D1 共享工具使用图谱（codegraph db 反查 paths.py 符号）+ H7 路径字面量违规扫描
- D2 分层依赖方向（import 边聚合成模块对）+ H1 子集（后端禁 import web_ui）
- D3 写法模式（日志 f-string vs %-惰性；退出码分布）
- D4 骨架模式（scripts/ 族的 argparse/main/paths 导入率）

仲裁原则：不裁决只呈证。doc_declared 规则有实证违反 → drift=1，由人决断。

用法：python3 scripts/mine_conventions.py [--codegraph-db PATH] [--out PATH] [--root DIR]
退出码（H12）：0=正常；1=未预期错误（codegraph db 缺失/查询失败）。
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_CG_DB = Path(".codegraph") / "codegraph.db"
DEFAULT_OUT = Path(".conventions") / "conventions.db"
EVIDENCE_CAP = 5

SCHEMA_SQL = """
CREATE TABLE conventions (
  id INTEGER PRIMARY KEY,
  dimension TEXT NOT NULL,
  subject TEXT NOT NULL,
  statement TEXT NOT NULL,
  source TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  compliance REAL,
  drift INTEGER NOT NULL DEFAULT 0,
  evidence TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  commit_hash TEXT
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""

# 维度 miner 注册表：统一签名 fn(cg, root, files) -> list[dict]，逐 task 追加
DIMENSIONS: tuple = ()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _git_tracked_py(root: Path) -> list[str]:
    return [ln for ln in _git(root, "ls-files", "--", "*.py").splitlines() if ln]


def _top_module(rel: str) -> str:
    parts = Path(rel).parts
    return parts[0] if len(parts) > 1 else "(root)"


def _open_codegraph(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"codegraph db 不存在: {db_path}（先跑 codegraph index）")
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _write_db(out_path: Path, records: list[dict], generated_at: str, commit_hash: str) -> None:
    """原子写：先写临时文件再 rename，避免半截 db 被 cvx/inject 读到。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            "INSERT INTO conventions (dimension, subject, statement, source, sample_size,"
            " compliance, drift, evidence, generated_at, commit_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    r["dimension"], r["subject"], r["statement"], r["source"], r["sample_size"],
                    r["compliance"], r["drift"], json.dumps(r["evidence"], ensure_ascii=False),
                    generated_at, commit_hash,
                )
                for r in records
            ],
        )
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?,?)",
            [("generated_at", generated_at), ("commit_hash", commit_hash)],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp, out_path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="项目约定蒸馏器（designs/convention_mining_design.md）")
    parser.add_argument("--codegraph-db", type=Path, default=DEFAULT_CG_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    try:
        cg = _open_codegraph(args.codegraph_db)
    except (FileNotFoundError, sqlite3.OperationalError) as e:
        print(f"mine_conventions: {e}", file=sys.stderr)
        return 1
    try:
        files = _git_tracked_py(args.root)
        commit_hash = _git(args.root, "rev-parse", "HEAD")
        records: list[dict] = []
        for fn in DIMENSIONS:
            records.extend(fn(cg, args.root, files))
        _write_db(args.out, records, time.strftime("%Y-%m-%dT%H:%M:%S"), commit_hash)
    except (sqlite3.Error, subprocess.CalledProcessError, OSError) as e:
        print(f"mine_conventions: 蒸馏失败: {e}", file=sys.stderr)
        return 1
    finally:
        cg.close()

    n_drift = sum(r["drift"] for r in records)
    print(f"conventions: {len(records)} 条（drift {n_drift}）-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
