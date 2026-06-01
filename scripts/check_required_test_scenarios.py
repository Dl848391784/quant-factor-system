#!/usr/bin/env python3
"""
检查必测场景清单：确认测试函数存在
对应 PROJECT.md 测试覆盖规范

检查逻辑：
- 扫描所有 test_cases/ 目录下的测试文件
- 确认必测场景函数名存在（非 100% 实现，但必须存在函数定义）

配置位置：PROJECT.md 行号 106-120
"""

import ast
import sys
from pathlib import Path


REQUIRED_TEST_FUNCTIONS = [
    "test_empty_df",
    "test_single_stock_df",
    "test_single_date_df",
    "test_nan_only_df",
    "test_output_schema_valid",
    "test_required_fields_present",
    "test_file_not_found",
    "test_invalid_json",
    "test_missing_column",
]


def get_test_functions(filepath: Path) -> set[str]:
    """从测试文件中提取所有测试函数名"""
    try:
        with open(filepath) as f:
            content = f.read()
    except FileNotFoundError:
        return set()

    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()

    functions = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            functions.add(node.name)

    return functions


def main() -> int:
    """检查必测场景函数是否存在"""
    project_root = Path(__file__).parent.parent

    # 扫描所有测试目录
    test_dirs = [
        project_root / "factor_ic" / "test_cases",
        project_root / "backtest" / "test_cases",
        project_root / "data_fetchers" / "test_cases",
        project_root / "comprehensive_factor" / "test_cases",
        project_root / "summary" / "test_cases",
        project_root / "tests" / "integration",
    ]

    all_functions = set()
    for test_dir in test_dirs:
        if test_dir.exists():
            for test_file in test_dir.glob("test_*.py"):
                functions = get_test_functions(test_file)
                all_functions.update(functions)

    # 检查必测场景
    missing = []
    for func in REQUIRED_TEST_FUNCTIONS:
        if func not in all_functions:
            missing.append(func)

    if missing:
        print("❌ 必测场景函数缺失：")
        for func in missing:
            print(f"   {func}")
        print("   请在测试文件中添加这些函数")
        return 1

    print(f"✓ 必测场景检查通过：{len(REQUIRED_TEST_FUNCTIONS)} 个函数全部存在")
    return 0


if __name__ == "__main__":
    sys.exit(main())
