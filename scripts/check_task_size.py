#!/usr/bin/env python3
"""
检查任务粒度：不超过 3 个文件、不超过 200 行代码
对应 PROJECT.md 任务粒度指引

阈值硬编码在此脚本中：
- MAX_FILES = 3
- MAX_LINES = 200
配置位置：PROJECT.md 行号 55-67
"""

import subprocess
import sys
from contextlib import suppress


def check_task_size() -> int:
    """检查本次提交的文件数和行数"""
    # 获取 staged 文件列表
    result = subprocess.run(
        ["git", "diff", "--cached", "--stat"],
        capture_output=True,
        text=True,
    )

    if not result.stdout:
        # 无 staged 文件，跳过检查
        return 0

    lines = result.stdout.strip().split("\n")
    file_count = len(lines) - 1  # 最后一行是统计汇总

    # 解析总行数
    total_insertions = 0
    for line in lines[:-1]:
        parts = line.split()
        if len(parts) >= 4:
            # 格式: filename | N insertions | M deletions
            for part in parts:
                if part.endswith("insertion") or part.endswith("insertion(s)"):
                    with suppress(ValueError, IndexError):
                        total_insertions += int(parts[parts.index(part) - 1])

    # 检查阈值
    max_files = 3
    max_lines = 200

    if file_count > max_files:
        print(f"❌ 任务粒度超限：{file_count} 个文件 > {max_files}")
        print("   请拆分成多次任务提交")
        return 1

    if total_insertions > max_lines:
        print(f"❌ 任务粒度超限：{total_insertions} 行代码 > {max_lines}")
        print("   请拆分成多次任务提交")
        return 1

    print(f"✓ 任务粒度检查通过：{file_count} 文件，{total_insertions} 行")
    return 0


if __name__ == "__main__":
    sys.exit(check_task_size())
