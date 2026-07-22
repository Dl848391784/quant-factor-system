"""
scripts/check_dead_branches.py 的单元测试

覆盖 H13 死代码分支检查：
- 模式 1：if False / if 0 / if None 块
- 模式 2：assert False 之后的可执行代码
- 模式 3：factor_ic/ic_*.py 中 `if result is None`（仅当 result 来自 run_factor_ic 时）

对应 PROJECT.md 规则 H13。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.check_dead_branches import _check_file


def _write(tmp_path: Path, content: str, name: str = "ic_factor.py") -> Path:
    """写入临时文件并返回路径。"""
    filepath = tmp_path / name
    filepath.write_text(textwrap.dedent(content).lstrip())
    return filepath


# ─────────────────── 模式 1：if False / if 0 ───────────────────


def test_if_false_fail(tmp_path: Path) -> None:
    fp = _write(tmp_path, "if False:\n    legacy_branch()\n")
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "if False" in violations[0]


def test_if_0_fail(tmp_path: Path) -> None:
    fp = _write(tmp_path, "if 0:\n    legacy_branch()\n")
    violations = _check_file(fp)
    assert len(violations) == 1


def test_if_true_pass(tmp_path: Path) -> None:
    """if True 不是死代码（虽然冗余但有时用于切换调试），不报警。"""
    fp = _write(tmp_path, "if True:\n    do_thing()\n")
    assert _check_file(fp) == []


def test_if_variable_pass(tmp_path: Path) -> None:
    fp = _write(tmp_path, "x = 1\nif x:\n    do_thing()\n")
    assert _check_file(fp) == []


# ─────────────────── 模式 2：assert False ───────────────────


def test_assert_false_with_unreachable_fail(tmp_path: Path) -> None:
    fp = _write(
        tmp_path,
        """
        def f():
            assert False
            unreachable_call()
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "assert False" in violations[0]


def test_assert_false_at_function_end_pass(tmp_path: Path) -> None:
    """assert False 在函数末尾（无后续代码）不算违规。"""
    fp = _write(
        tmp_path,
        """
        def f():
            assert False
        """,
    )
    assert _check_file(fp) == []


def test_assert_truthy_pass(tmp_path: Path) -> None:
    """assert <truthy> 不是不可达."""
    fp = _write(
        tmp_path,
        """
        def f():
            assert x > 0
            return x
        """,
    )
    assert _check_file(fp) == []


# ─────────────────── 模式 3：result is None 死守卫 ───────────────────


def test_none_guard_with_run_factor_ic_fail(tmp_path: Path) -> None:
    """同函数内有 result = run_factor_ic(...) + if result is None → 死守卫。"""
    fp = _write(
        tmp_path,
        """
        def main():
            result = run_factor_ic(spec, df)
            if result is None:
                sys.exit(1)
            return result
        """,
    )
    violations = _check_file(fp, check_none_guard=True)
    assert len(violations) == 1
    assert "if result is None" in violations[0]
    assert "run_factor_ic" in violations[0]


def test_none_guard_disabled_pass(tmp_path: Path) -> None:
    """check_none_guard=False（如非 factor_ic/ic_*.py 文件）应跳过模式 3。"""
    fp = _write(
        tmp_path,
        """
        def main():
            result = run_factor_ic(spec, df)
            if result is None:
                sys.exit(1)
        """,
    )
    assert _check_file(fp, check_none_guard=False) == []


def test_none_guard_other_callee_pass(tmp_path: Path) -> None:
    """result 不是来自 run_factor_ic（如 third-party / 自定义）→ 合法守卫，不报警。"""
    fp = _write(
        tmp_path,
        """
        def main():
            result = load_config(path)  # 文档：找不到时返回 None
            if result is None:
                sys.exit(1)
        """,
    )
    assert _check_file(fp, check_none_guard=True) == []


def test_none_guard_different_var_pass(tmp_path: Path) -> None:
    """不是 result 变量（如 config）→ 不命中模式 3。"""
    fp = _write(
        tmp_path,
        """
        def main():
            result = run_factor_ic(spec, df)
            config = load_config()
            if config is None:
                sys.exit(1)
            return result
        """,
    )
    assert _check_file(fp, check_none_guard=True) == []


def test_none_guard_module_attr_call_fail(tmp_path: Path) -> None:
    """支持 module.run_factor_ic 形式的调用。"""
    fp = _write(
        tmp_path,
        """
        def main():
            result = factor_ic.run_factor_ic(spec, df)
            if result is None:
                sys.exit(1)
        """,
    )
    violations = _check_file(fp, check_none_guard=True)
    assert len(violations) == 1


def test_allowlist_skips_none_guard(tmp_path: Path) -> None:
    """allowlist 命中的文件应跳过模式 3 检查。"""
    # 模拟 allowlist 路径需要 monkeypatch；此处仅验证 _check_file 接口可被外层 allowlist 短路
    # 真正的 allowlist 短路在 check_dead_branches() 入口处验证（_check_file 自身的相对路径计算）
    # 因此用真实 ic_*.py allowlist 文件名构造测试
    fp = tmp_path / "ic_amplitude_1d.py"
    fp.write_text(
        textwrap.dedent(
            """
            def main():
                result = run_factor_ic(spec, df)
                if result is None:
                    sys.exit(1)
            """
        ).lstrip()
    )
    # _check_file 不知道 tmp_path 是否在 allowlist（因为它的相对路径锚是脚本所在仓库）
    # 所以 tmp_path 中的 ic_amplitude_1d.py 仍会触发违规——这测的是脚本路径解析逻辑
    violations = _check_file(fp, check_none_guard=True)
    # 不在仓库内 → relative_to 失败 → 走 fallback rel=str(filepath) → 不在 allowlist → 触发违规
    assert len(violations) == 1


# ─────────────────── 边界 ───────────────────


def test_syntax_error_reports(tmp_path: Path) -> None:
    fp = tmp_path / "broken.py"
    fp.write_text("def f(\n")
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "语法错误" in violations[0]


def test_clean_file_pass(tmp_path: Path) -> None:
    fp = _write(
        tmp_path,
        """
        def main():
            result = run_factor_ic(spec, df)
            log_factor_summary(result, "x", logger)
        """,
    )
    assert _check_file(fp, check_none_guard=True) == []
