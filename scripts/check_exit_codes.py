#!/usr/bin/env python3
"""
检查 sys.exit 退出码语义符合 PROJECT.md H12：
- 0 = 完全成功
- 1 = 未预期错误（程序 bug） / 兜底
- 2 = (R16 弃用，模块顶层改 logger.critical + raise)
- 3 = 辅助层失败（R17，SummaryLogError）
- 4 = DataSchemaError（R18，数据 schema 不匹配，需检查上游列契约）
- 5 = FactorCalcError（R19，因子计算内部失败，需检查计算代码）
- R20 = main() 函数体内禁 sys.exit，必须 raise 让 __main__ 块统一处理

检查策略（AST 分析）：
- ① 模块顶层 try/except 块（R16）：禁止 sys.exit，必须 logger.critical + raise
- ② if __name__ == "__main__" 块内 except：按异常类名→允许 exit 码集合差异化
  （EXCEPTION_TO_ALLOWED_EXIT_CODES，多值兼容旧 sys.exit(1) + 新 sys.exit(4/5)）
- ③ R20：main() 函数体内禁 sys.exit（仅对 R20_MIGRATED_FILES 白名单强制）
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
RUNTIME_EXIT_CODE = 1  # __main__ 块内 except（默认/兜底）

# R18+R19+R17 升级：__main__ 块按 except 异常类名差异化退出码。
# 映射策略：异常类名 → 允许的 exit 码集合（多值兼容旧实现）。
# - 多值允许：旧文件用 sys.exit(1) 兼容，新实现用差异化码（4/5/3）；扩散完成后可收紧为单值
# - 未在表中命中 → 回退到默认 RUNTIME_EXIT_CODE（仅允许 exit 1）
EXCEPTION_TO_ALLOWED_EXIT_CODES: dict[str, set[int]] = {
    "DataSchemaError": {1, 4},  # R18: 4=新差异化（检查上游数据），1=旧兼容
    "FactorCalcError": {1, 5},  # R19: 5=新差异化（检查计算代码），1=旧兼容
    "SummaryLogError": {3},  # R17: 强制 exit 3（辅助层失败专用）
    "Exception": {RUNTIME_EXIT_CODE},  # 兜底：程序 bug → exit 1
}

# R20: main() 函数体内禁 sys.exit，必须 raise 让 __main__ 块统一处理。
# 仅对已迁移文件强制（白名单），未迁移文件保持向后兼容（旧 main 内含 sys.exit(3) for R17）。
# 扩散完成后此白名单将切换为黑名单（默认全部强制）。
R20_MIGRATED_FILES: frozenset[str] = frozenset(
    {
        "ic_industry_momentum_5d_1d.py",  # R3 落地（design.md §6 完整 7 issue 修复）
        # R4 扩散批次后增补
    }
)


def _handler_exception_names(handler: ast.ExceptHandler) -> list[str]:
    """提取 except 子句捕获的异常类名列表（含 except (A, B) 元组形式）。

    返回空列表表示裸 except 或捕获非 Name 节点（如属性访问 module.Error）。
    """
    if handler.type is None:
        return []  # 裸 except
    names: list[str] = []
    targets = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for t in targets:
        if isinstance(t, ast.Name):
            names.append(t.id)
        elif isinstance(t, ast.Attribute):
            names.append(t.attr)  # 如 exceptions.DataSchemaError → DataSchemaError
    return names


def _allowed_exit_codes_for_handler(handler: ast.ExceptHandler) -> set[int]:
    """根据 except 捕获的异常类名计算允许的退出码集合。

    多个异常类时取并集（兼容旧 except (DataSchemaError, FactorCalcError) 写法）。
    无命中时回退默认 RUNTIME_EXIT_CODE。
    """
    names = _handler_exception_names(handler)
    if not names:
        return {RUNTIME_EXIT_CODE}
    allowed: set[int] = set()
    for name in names:
        allowed |= EXCEPTION_TO_ALLOWED_EXIT_CODES.get(name, {RUNTIME_EXIT_CODE})
    return allowed


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
        # R18+R19+R17：按 except 异常类名差异化允许的 exit 码（多值兼容旧实现）
        if isinstance(stmt, ast.If) and _is_main_guard(stmt):
            for inner in ast.walk(stmt):
                if not isinstance(inner, ast.Try):
                    continue
                for handler in inner.handlers:
                    allowed_codes = _allowed_exit_codes_for_handler(handler)
                    handler_names = _handler_exception_names(handler) or ["<bare except>"]
                    handler_repr = "/".join(handler_names)
                    for lineno, code in _extract_exit_codes(handler):
                        if code is None:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except {handler_repr} 中 "
                                f"sys.exit 无常量参数（H12 要求 exit ∈ {sorted(allowed_codes)}）"
                            )
                        elif code == 0:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except {handler_repr} 中 "
                                f"sys.exit(0) 隐藏失败，H12 要求 exit ∈ {sorted(allowed_codes)}"
                            )
                        elif code not in allowed_codes:
                            violations.append(
                                f"{filepath}:{lineno}: __main__ except {handler_repr} 中 "
                                f"sys.exit({code})，H12 要求 exit ∈ {sorted(allowed_codes)}"
                            )

    # ③ R20：main() 函数体内禁 sys.exit（仅对已迁移文件强制）
    # 未迁移文件保持向后兼容；扩散完成后 R20_MIGRATED_FILES 切换为黑名单
    if filepath.name in R20_MIGRATED_FILES:
        for stmt in tree.body:
            if isinstance(stmt, ast.FunctionDef) and stmt.name == "main":
                for lineno, code in _extract_exit_codes(stmt):
                    code_repr = "" if code is None else str(code)
                    violations.append(
                        f"{filepath}:{lineno}: R20 违规 — main() 函数体内禁 sys.exit({code_repr})，"
                        f"必须 raise 具名异常让 __main__ 块统一处理（PROJECT.md H12 R20）"
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
        print("   H12 规则（R16/R17/R18/R19/R20）：")
        print("   - ① 模块顶层 except register_factor → logger.critical + raise（禁止 sys.exit）")
        print("   - ② __main__ except 按异常类名差异化 exit 码：")
        print("       DataSchemaError → exit 4（R18）/ 1（旧兼容）")
        print("       FactorCalcError → exit 5（R19）/ 1（旧兼容）")
        print("       SummaryLogError → exit 3（R17）")
        print("       Exception → exit 1（兜底）")
        print("   - ③ R20: main() 函数体内禁 sys.exit，必须 raise 让 __main__ 处理")
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
