#!/usr/bin/env python3
"""
检查 sys.exit 退出码语义符合 PROJECT.md H12：
- 0 = 成功
- 1 = main() 运行时错误
- 2 = import-time 配置或注册失败

检查策略（AST 分析）：
- 扫描 factor_ic/ic_*.py 文件
- 模块顶层 try/except 块内（捕获 register_factor 等）的 sys.exit 必须用 exit code 2
- if __name__ == "__main__" 块内 except 中的 sys.exit 必须用 exit code 1
- 任何 sys.exit(0) 在 except 块中视为违规（隐藏失败）

对应 PROJECT.md 规则 H12 / AGENTS.md 规则 #6。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


# 检查范围：factor_ic/ic_*.py 入口脚本
TARGET_GLOB_PATTERNS = [
    "factor_ic/ic_*.py",
]

# 允许的退出码（按位置）
# R16 升级：模块顶层 except 不再用 sys.exit(2)，改为 logger.critical + raise，
# 因此 IMPORT_TIME_EXIT_CODE 不再使用（保留常量用于历史 grep 兼容）。
IMPORT_TIME_EXIT_CODE = 2  # noqa: F841 — R16 起仅供历史参考，不在检查中使用
RUNTIME_EXIT_CODE = 1  # __main__ 块内 except


def _is_main_guard(node: ast.If) -> bool:
    """判断是否为 if __name__ == '__main__' 块。"""
    test = node.test
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False
    left = test.left
    if not (isinstance(left, ast.Name) and left.id == "__name__"):
        return False
    if len(test.comparators) != 1:
        return False
    right = test.comparators[0]
    return isinstance(right, ast.Constant) and right.value == "__main__"


def _extract_exit_codes(node: ast.AST) -> list[tuple[int, int | None]]:
    """提取 AST 子树内所有 sys.exit(N) 的 (lineno, exit_code) 元组。

    返回 exit_code=None 表示 sys.exit 无参数或参数非常量。
    """
    codes: list[tuple[int, int | None]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        # 匹配 sys.exit(...)
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "exit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "sys"
        ):
            continue
        if not child.args:
            codes.append((child.lineno, None))
            continue
        arg = child.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            codes.append((child.lineno, arg.value))
        else:
            codes.append((child.lineno, None))
    return codes


def _check_file(filepath: Path) -> list[str]:
    """检查单个文件，返回违规列表（空表示合规）。"""
    try:
        source = filepath.read_text()
    except FileNotFoundError:
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return [f"{filepath}:{e.lineno}: 语法错误，跳过 ({e.msg})"]

    violations: list[str] = []

    for stmt in tree.body:
        # ① 模块顶层 try/except 块（捕获 register_factor 等 import-time 失败）
        # H12 R16 升级：禁止 sys.exit（会杀 importlib 宿主进程），必须以 raise 收尾
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                # 检查是否有 sys.exit
                exit_codes = _extract_exit_codes(handler)
                for lineno, code in exit_codes:
                    code_repr = "" if code is None else str(code)
                    violations.append(
                        f"{filepath}:{lineno}: 模块顶层 except 禁止 sys.exit({code_repr})，"
                        f"会杀 importlib.import_module 宿主进程；H12 要求改为 logger.critical + raise"
                    )
                # 检查是否包含 raise（裸 raise 或 raise NewError）
                has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(handler))
                if not has_raise and not exit_codes:
                    # 既无 sys.exit 也无 raise → except 块吞异常（H12 隐性违规）
                    violations.append(
                        f"{filepath}:{handler.lineno}: 模块顶层 except 必须以 raise 收尾"
                        f"（H12 要求让调用方决定退出行为，不可吞异常）"
                    )

        # ② if __name__ == "__main__" 块内的 try/except
        if isinstance(stmt, ast.If) and _is_main_guard(stmt):
            for inner in ast.walk(stmt):
                if not isinstance(inner, ast.Try):
                    continue
                for handler in inner.handlers:
                    for lineno, code in _extract_exit_codes(handler):
                        if code is None:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except 中 sys.exit 无常量参数（H12 要求 exit 1）"
                            )
                        elif code == 0:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except 中 sys.exit(0) 隐藏失败，"
                                f"H12 要求运行时错误用 exit {RUNTIME_EXIT_CODE}"
                            )
                        elif code != RUNTIME_EXIT_CODE:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except 中 sys.exit({code})，"
                                f"H12 要求运行时错误用 exit {RUNTIME_EXIT_CODE}"
                            )

    return violations


def _staged_files() -> list[Path]:
    """获取 staged 的目标文件（pre-commit 模式）。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout:
        return []
    files = result.stdout.strip().split("\n")
    return [Path(f) for f in files if _matches_target(f)]


def _all_target_files(repo_root: Path) -> list[Path]:
    """获取所有目标文件（CI 全量模式）。"""
    files: list[Path] = []
    for pattern in TARGET_GLOB_PATTERNS:
        files.extend(repo_root.glob(pattern))
    return files


def _matches_target(filepath: str) -> bool:
    """判断文件是否在检查范围内。"""
    return any(re.match(pattern.replace("*", ".*"), filepath) for pattern in TARGET_GLOB_PATTERNS)


def check_exit_codes(mode: str = "staged") -> int:
    """主检查入口。

    Args:
        mode: "staged"（pre-commit, 仅 staged 文件） / "all"（CI 全量）
    """
    repo_root = Path(__file__).parent.parent
    files = _staged_files() if mode == "staged" else _all_target_files(repo_root)

    if not files:
        if mode == "staged":
            return 0
        print("⚠️  未找到目标文件")
        return 0

    all_violations: list[str] = []
    for filepath in files:
        all_violations.extend(_check_file(filepath))

    if all_violations:
        print("❌ 发现 H12 退出码违规：")
        for v in all_violations:
            print(f"   {v}")
        print()
        print("   H12 规则（R16 修正后）：")
        print("   - 模块顶层 try/except register_factor → logger.critical + raise（禁止 sys.exit）")
        print(f"   - __main__ 块 except → sys.exit({RUNTIME_EXIT_CODE})")
        print("   - 禁止 except 块中 sys.exit(0)")
        return 1

    print(f"✓ H12 退出码检查通过（共 {len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "staged"
    if mode not in ("staged", "all"):
        print(f"usage: {sys.argv[0]} [staged|all]")
        sys.exit(2)
    sys.exit(check_exit_codes(mode))
