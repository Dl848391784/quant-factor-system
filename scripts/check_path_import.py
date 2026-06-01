#!/usr/bin/env python3
"""
检查路径导入：所有使用路径常量的脚本必须 `from paths import ...`
对应 PROJECT.md 规则 #7 路径导入

使用 AST 静态分析，精确识别：
- 赋值给路径变量的场景
- 传给文件操作 API 的场景
- 禁止字符串字面量形式的路径

配置位置：PROJECT.md 行号 44-58
"""

import ast
import subprocess
import sys


PATH_CONSTANTS = [
    "FACTOR_IC_DATA",
    "DATA_FETCHERS_RESULT",
    "FACTOR_IC_RESULT",
    "BACKTEST_RESULT",
    "COMPREHENSIVE_FACTOR_RESULT",
    "SUMMARY_RESULT",
]


def check_path_import(filepath: str) -> list[str]:
    """检查文件是否正确导入 paths 模块"""
    violations = []

    try:
        with open(filepath) as f:
            content = f.read()
    except FileNotFoundError:
        return violations

    # 解析 AST
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations

    # 检查是否导入 paths
    has_paths_import = False
    imported_names = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "paths":
                has_paths_import = True
                for alias in node.names:
                    imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "paths":
                    has_paths_import = True

    # 检查是否使用了路径常量但未导入
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in PATH_CONSTANTS:
            if not has_paths_import or node.id not in imported_names:
                violations.append(f"{filepath}: 使用 {node.id} 但未 from paths import")

    # 检查字符串字面量中的路径
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "result/" in node.value or "/result" in node.value:
                violations.append(f"{filepath}: 发现路径字面量 '{node.value}'")

    return violations


def main() -> int:
    """检查所有 staged Python 文件"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
    )

    if not result.stdout:
        return 0

    python_files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]

    all_violations = []
    for filepath in python_files:
        violations = check_path_import(filepath)
        all_violations.extend(violations)

    if all_violations:
        print("❌ 路径导入检查失败：")
        for v in all_violations:
            print(f"   {v}")
        print("   请使用: from paths import FACTOR_IC_DATA, ...")
        return 1

    print("✓ 路径导入检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
