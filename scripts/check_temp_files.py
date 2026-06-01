#!/usr/bin/env python3
"""
检查临时文件位置：必须放在 temporary/ 目录
对应 PROJECT.md 规则 #3
"""

import subprocess
import sys


TEMP_PATTERNS = [
    "temp_",
    "_temp",
    "debug_",
    "_debug",
    "test_temp_",
]


def check_temp_files() -> int:
    """检查 staged 文件是否是临时文件"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
        capture_output=True,
        text=True,
    )

    if not result.stdout:
        return 0

    added_files = result.stdout.strip().split("\n")
    violations = []

    for filepath in added_files:
        # 检查是否是临时文件
        filename = filepath.split("/")[-1]
        is_temp = any(pattern in filename.lower() for pattern in TEMP_PATTERNS)

        if is_temp and not filepath.startswith("temporary/"):
            violations.append(filepath)

    if violations:
        print("❌ 临时文件位置违规：")
        for v in violations:
            print(f"   {v}")
        print("   请移动到 temporary/ 目录")
        return 1

    print("✓ 临时文件位置检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(check_temp_files())
