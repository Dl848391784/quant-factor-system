#!/usr/bin/env python3
"""
检查路径字面量：禁止硬编码 result/、data_fetchers/result 等字符串
对应 PROJECT.md 规则 #9
"""

import re
import subprocess
import sys


FORBIDDEN_PATTERNS = [
    r'"result/"',
    r'"data_fetchers/result"',
    r'"factor_ic/result"',
    r'"backtest/result"',
    r'"comprehensive_factor/result"',
    r'"summary/result"',
    r"'result/'",
    r"'data_fetchers/result'",
]


def check_path_literals() -> int:
    """检查 staged Python 文件中的路径字面量"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
    )

    if not result.stdout:
        return 0

    python_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]

    violations = []
    for filepath in python_files:
        # 获取文件内容
        try:
            with open(filepath) as f:
                content = f.read()
        except FileNotFoundError:
            continue

        # 检查 forbidden patterns
        for pattern in FORBIDDEN_PATTERNS:
            matches = re.findall(pattern, content)
            if matches:
                violations.append(f"{filepath}: 发现 {pattern}")

    if violations:
        print("❌ 发现路径字面量违规：")
        for v in violations:
            print(f"   {v}")
        print("   请使用: from paths import FACTOR_IC_RESULT, ...")
        return 1

    print("✓ 路径字面量检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(check_path_literals())
