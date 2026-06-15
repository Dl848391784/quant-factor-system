"""factor_calculator 拆分后的指纹验证（design.md §9.2）。

用法：
    PYTHONPATH=. python temporary/factor_calculator_verify_fingerprint.py

退出码：
    0  全部一致
    1  有指纹漂移
    2  基线文件不存在 / 加载失败
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 复用基线脚本的数据构造与指纹计算逻辑
from temporary.factor_calculator_baseline_fingerprint import (
    _build_panel,
    _hash_df_col,
    collect_fingerprints,
)

BASELINE_PATH = Path(__file__).parent / "factor_calculator_baseline_fingerprint.json"


def main() -> int:
    if not BASELINE_PATH.exists():
        print(f"ERROR: baseline not found → {BASELINE_PATH}", file=sys.stderr)
        print("       run factor_calculator_baseline_fingerprint.py first", file=sys.stderr)
        return 2

    baseline = json.loads(BASELINE_PATH.read_text())
    expected = baseline["fingerprints"]
    expected_panel_hash = baseline["panel_hash"]

    panel = _build_panel()
    actual_panel_hash = _hash_df_col(panel, "close")
    if actual_panel_hash != expected_panel_hash:
        print(
            f"ERROR: panel hash drift "
            f"({actual_panel_hash} != {expected_panel_hash}); "
            f"data construction changed",
            file=sys.stderr,
        )
        return 1

    actual = collect_fingerprints(panel)

    drifts: list[tuple[str, str, str]] = []
    missing: list[str] = []
    for name, exp in expected.items():
        if name not in actual:
            missing.append(name)
            continue
        if actual[name] != exp:
            drifts.append((name, exp, actual[name]))

    new_keys = set(actual) - set(expected)

    if not drifts and not missing and not new_keys:
        print(f"OK: {len(actual)} fingerprints match baseline")
        return 0

    if drifts:
        print(f"DRIFT: {len(drifts)} factor(s) changed:", file=sys.stderr)
        for name, exp, act in drifts:
            print(f"  - {name}: expected={exp} got={act}", file=sys.stderr)
    if missing:
        print(f"MISSING: {len(missing)} factor(s) gone:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
    if new_keys:
        print(f"NEW: {len(new_keys)} factor(s) added (re-baseline?):", file=sys.stderr)
        for name in sorted(new_keys):
            print(f"  + {name}: {actual[name]}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
