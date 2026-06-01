#!/usr/bin/env python3
"""
校验 PR 规范引用
对应 PROJECT.md PR 模板必填字段
"""

import os
import re
import sys


def validate_pr_reference() -> int:
    """校验 PR body 中的规范引用"""
    pr_body = os.environ.get("PR_BODY", "")

    if not pr_body:
        print("❌ PR body 为空，必须填写规范引用")
        return 1

    # 检查规则编号
    rule_pattern = r"#(\d)"
    rules_found = re.findall(rule_pattern, pr_body)

    if not rules_found:
        print("❌ 未找到规则编号引用（格式：#1, #5 等）")
        return 1

    # 检查行号
    line_pattern = r"行号\s*(\d+[-\d]*)"
    lines_found = re.findall(line_pattern, pr_body)

    if not lines_found:
        print("❌ 未找到 PROJECT.md 行号引用")
        return 1

    print(f"✓ 规范引用检查通过：规则 {rules_found}，行号 {lines_found}")
    return 0


if __name__ == "__main__":
    sys.exit(validate_pr_reference())
