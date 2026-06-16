#!/usr/bin/env python3
"""
检查死代码分支符合 PROJECT.md H13：
- 禁止 if False: / if 0: 块（明确不可达）
- 禁止 assert False 之后的可执行代码（不可达）
- 禁止 factor_ic/ic_*.py 中 `if result is None` 模式（callee 永不返回 None 的 regression guard）

注：死代码检查无法纯静态判定（需跨文件分析 callee 行为），本脚本只检查
确定性死代码模式 + 项目特定 regression guard。复杂死代码仍依赖 code review。

对应 PROJECT.md 规则 H13 / AGENTS.md 规则 #14。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


# 全量检查范围（不可达分支模式 1+2）
GENERAL_GLOB_PATTERNS = [
    "factor_ic/**/*.py",
    "backtest/**/*.py",
    "comprehensive_factor/**/*.py",
    "data_fetchers/**/*.py",
    "summary/**/*.py",
]

# 项目特定 regression guard 范围（模式 3：if result is None）
NONE_GUARD_GLOB_PATTERNS = [
    "factor_ic/ic_*.py",
]

# Allowlist：尚未迁移的历史文件（H13 渐进迁移）。
# 新增文件不应进此列表；修复后从列表删除一行。
# 对应 PROJECT.md H13 当前覆盖范围 ⏳ 待审计。
NONE_GUARD_ALLOWLIST = frozenset(
    {
        "factor_ic/ic_amplitude_1d.py",
        "factor_ic/ic_amplitude_delta_1d.py",
        "factor_ic/ic_bollinger_pb_1d.py",
        "factor_ic/ic_capital_flow_intensity_1d.py",
        "factor_ic/ic_capital_flow_ratio_trend_1d.py",
        "factor_ic/ic_industry_pe_trend_1d.py",
        "factor_ic/ic_industry_roe_trend_1d.py",
        "factor_ic/ic_intraday_intensity_1d.py",
        "factor_ic/ic_kdj_j_1d.py",
        "factor_ic/ic_ma5_deviation_1d.py",
        "factor_ic/ic_momentum_strength_1d.py",
        "factor_ic/ic_near_high_ratio_5_1d.py",
        "factor_ic/ic_overnight_ret_1d.py",
        "factor_ic/ic_past_return_1d_1d.py",
        "factor_ic/ic_positive_day_ratio_5_1d.py",
        "factor_ic/ic_price_position_1d.py",
        "factor_ic/ic_return_3d_1d.py",
        "factor_ic/ic_return_5d_1d.py",
        "factor_ic/ic_rsi_1d.py",
        "factor_ic/ic_tail_price_position.py",
        "factor_ic/ic_tail_price_position_delta_1d.py",
        "factor_ic/ic_tail_price_slope_1d.py",
        "factor_ic/ic_tail_price_volume_intensity.py",
        "factor_ic/ic_tail_volume_acceleration_1d.py",
        "factor_ic/ic_tail_volume_shrink_1d.py",
        "factor_ic/ic_tail_volume_shrink_delta_1d.py",
        "factor_ic/ic_turnover_surge_1d.py",
        "factor_ic/ic_turnover_surge_delta_1d.py",
        "factor_ic/ic_volume_price_strength_1d.py",
        "factor_ic/ic_volume_ratio_1d.py",
    }
)


def _is_unreachable_constant(node: ast.expr) -> bool:
    """判断 if 测试条件是否为不可达的常量（False / 0 / None）。"""
    if isinstance(node, ast.Constant):
        return node.value is False or node.value == 0 or node.value is None
    return False


def _is_assert_false(stmt: ast.stmt) -> bool:
    """判断是否为 assert False（含 0 / None 等假值常量）。"""
    if not isinstance(stmt, ast.Assert):
        return False
    test = stmt.test
    return isinstance(test, ast.Constant) and not test.value


def _check_unreachable_branches(tree: ast.AST, filepath: Path) -> list[str]:
    """检查模式 1：if False / if 0 / if None 块。"""
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_unreachable_constant(node.test):
            violations.append(f"{filepath}:{node.lineno}: 死代码分支 `if {ast.unparse(node.test)}:`（H13 要求删除）")
    return violations


def _check_assert_false(tree: ast.AST, filepath: Path) -> list[str]:
    """检查模式 2：assert False 之后的可执行代码。"""
    violations: list[str] = []

    # 遍历所有有 body 的 AST 节点
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body):
            if _is_assert_false(stmt) and i < len(body) - 1:
                next_stmt = body[i + 1]
                violations.append(f"{filepath}:{next_stmt.lineno}: `assert False` 之后存在不可达代码（H13 要求删除）")
    return violations


def _function_assigns_run_factor_ic_to_result(func_node: ast.AST) -> bool:
    """检查函数体内是否有 `result = run_factor_ic(...)` 赋值。

    用于精确判定 result 来源：仅当 callee 是 run_factor_ic 时，
    `if result is None` 才是死守卫（callee 文档明确永不返回 None）。
    """
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Assign):
            continue
        # 检查 targets 含 result
        has_result_target = any(isinstance(t, ast.Name) and t.id == "result" for t in node.targets)
        if not has_result_target:
            continue
        # 检查右值是 run_factor_ic(...) 调用
        value = node.value
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Name) and func.id == "run_factor_ic":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "run_factor_ic":
                return True
    return False


def _check_none_guard_in_ic_main(tree: ast.AST, filepath: Path) -> list[str]:
    """检查模式 3：factor_ic/ic_*.py 中的 `if result is None` 死守卫。

    精确判定：必须同时满足
    1. 同函数内有 `result = run_factor_ic(...)` 赋值
    2. 该函数内有 `if result is None:` 守卫

    callee `run_factor_ic` 已审计：失败走 build_error_result(返回 dict) 或 raise，
    永不返回 None。caller 写 `if result is None` 是死分支。
    """
    violations: list[str] = []
    # 遍历所有函数定义（顶层 + 嵌套）
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _function_assigns_run_factor_ic_to_result(func):
            continue
        # 找该函数体内的 `if result is None:` 守卫
        for node in ast.walk(func):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if not isinstance(test, ast.Compare):
                continue
            if not (len(test.ops) == 1 and isinstance(test.ops[0], ast.Is)):
                continue
            if not (
                len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            ):
                continue
            if not (isinstance(test.left, ast.Name) and test.left.id == "result"):
                continue
            violations.append(
                f"{filepath}:{node.lineno}: `if result is None:` 死守卫"
                f"（callee run_factor_ic 永不返回 None，H13 要求删除）"
            )
    return violations


def _check_file(filepath: Path, check_none_guard: bool = False) -> list[str]:
    """检查单个文件。

    Args:
        filepath: 待检查文件
        check_none_guard: 是否启用模式 3（仅 factor_ic/ic_*.py 启用）
    """
    try:
        source = filepath.read_text()
    except FileNotFoundError:
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return [f"{filepath}:{e.lineno}: 语法错误，跳过 ({e.msg})"]

    violations: list[str] = []
    violations.extend(_check_unreachable_branches(tree, filepath))
    violations.extend(_check_assert_false(tree, filepath))
    if check_none_guard:
        # Allowlist 命中则跳过模式 3（H13 渐进迁移：历史文件先豁免，新增文件立即拦截）
        try:
            rel = str(filepath.relative_to(Path(__file__).parent.parent))
        except ValueError:
            rel = str(filepath)
        if rel not in NONE_GUARD_ALLOWLIST:
            violations.extend(_check_none_guard_in_ic_main(tree, filepath))
    return violations


def _matches_any(filepath: str, patterns: list[str]) -> bool:
    """fnmatch 风格匹配（** 转 .*）。"""
    for pattern in patterns:
        # 转换 glob 到正则
        regex = pattern.replace(".", r"\.").replace("**/", ".*").replace("*", "[^/]*")
        if re.fullmatch(regex, filepath):
            return True
    return False


def _staged_files() -> list[tuple[Path, bool]]:
    """获取 staged 的目标文件，返回 [(path, check_none_guard), ...]。"""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        check=False,
    )
    if not result.stdout:
        return []
    files = result.stdout.strip().split("\n")
    out: list[tuple[Path, bool]] = []
    for f in files:
        if not f.endswith(".py"):
            continue
        in_general = _matches_any(f, GENERAL_GLOB_PATTERNS)
        in_none_guard = _matches_any(f, NONE_GUARD_GLOB_PATTERNS)
        if in_general or in_none_guard:
            out.append((Path(f), in_none_guard))
    return out


def _all_target_files(repo_root: Path) -> list[tuple[Path, bool]]:
    """全量扫描目标文件。"""
    seen: set[Path] = set()
    out: list[tuple[Path, bool]] = []

    none_guard_files = set()
    for pattern in NONE_GUARD_GLOB_PATTERNS:
        for fp in repo_root.glob(pattern):
            none_guard_files.add(fp.resolve())

    for pattern in GENERAL_GLOB_PATTERNS:
        for fp in repo_root.glob(pattern):
            resolved = fp.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append((fp, resolved in none_guard_files))

    # 添加只在 NONE_GUARD 中的文件（理论上 GENERAL 已包含 factor_ic/**/*.py）
    for fp in none_guard_files - seen:
        out.append((Path(fp), True))
    return out


def check_dead_branches(mode: str = "staged") -> int:
    """主检查入口。"""
    repo_root = Path(__file__).parent.parent
    files = _staged_files() if mode == "staged" else _all_target_files(repo_root)

    if not files:
        if mode == "staged":
            return 0
        print("⚠️  未找到目标文件")
        return 0

    all_violations: list[str] = []
    for filepath, check_none in files:
        all_violations.extend(_check_file(filepath, check_none_guard=check_none))

    if all_violations:
        print("❌ 发现 H13 死代码违规：")
        for v in all_violations:
            print(f"   {v}")
        print()
        print("   H13 规则：")
        print("   - 禁止 `if False:` / `if 0:` / `if None:` 等死分支")
        print("   - 禁止 `assert False` 之后的可执行代码")
        print("   - 禁止 factor_ic/ic_*.py 中 `if result is None:` 死守卫")
        print("   详见 PROJECT.md H13 判定边界。")
        return 1

    print(f"✓ H13 死代码检查通过（共 {len(files)} 个文件）")
    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "staged"
    if mode not in ("staged", "all"):
        print(f"usage: {sys.argv[0]} [staged|all]")
        sys.exit(2)
    sys.exit(check_dead_branches(mode))
