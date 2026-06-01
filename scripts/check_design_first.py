#!/usr/bin/env python3
"""
检查 Design-First 流程：涉及 2+ 文件改动的 PR 必须包含 design.md
对应 PROJECT.md 规则 #8 Design-First 流程

检查逻辑：
- PR 涉及 2+ 文件改动时，仓库 designs/ 目录下必须存在对应的 design.md 文件
- 文件命名：designs/<pr-number>.md 或 designs/<feature-name>.md

配置位置：PROJECT.md 行号 39-55
"""

import os
import subprocess
import sys
from pathlib import Path


def check_design_first() -> int:
    """检查 Design-First 流程"""
    # 获取 PR 涉及的文件数
    pr_body = os.environ.get("PR_BODY", "")

    # 检查是否有 design.md 文件链接
    if not pr_body:
        # 非 PR 环境，跳过检查
        print("非 PR 环境，跳过 Design-First 检查")
        return 0

    # 获取改动的文件数
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1"],
        capture_output=True,
        text=True,
    )

    if not result.stdout:
        return 0

    changed_files = result.stdout.strip().split("\n")
    file_count = len(changed_files)

    # 检查阈值
    max_files = 2

    if file_count > max_files:
        # 需要检查 design.md 是否存在
        designs_dir = Path(__file__).parent.parent / "designs"
        if not designs_dir.exists():
            print(f"❌ 涉及 {file_count} 个文件改动，但 designs/ 目录不存在")
            print("   请创建 designs/ 目录并添加 design.md")
            return 1

        # 检查是否有 design.md 文件
        design_files = list(designs_dir.glob("*.md"))
        if not design_files:
            print(f"❌ 涉及 {file_count} 个文件改动，但 designs/ 目录下无 design.md")
            print("   请添加 design.md 文件说明改动计划")
            return 1

        # 检查 PR body 是否引用 design.md
        if "design.md" not in pr_body.lower() and "designs/" not in pr_body.lower():
            print(f"❌ 涉及 {file_count} 个文件改动，但 PR 描述未引用 design.md")
            print("   请在 PR 描述中添加 design.md 文件链接")
            return 1

    print(f"✓ Design-First 检查通过：{file_count} 文件改动")
    return 0


if __name__ == "__main__":
    sys.exit(check_design_first())
