"""
scripts/check_exit_codes.py 的单元测试

覆盖 H12 退出码检查的正反例：
- 合规：模块顶层 try/except register → sys.exit(2)；__main__ except → sys.exit(1)
- 违规：顶层 except → sys.exit(1)；__main__ except → sys.exit(0)；__main__ except → sys.exit(2)

对应 PROJECT.md 规则 H12 / AGENTS.md 规则 #6。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from scripts.check_exit_codes import _check_file


def _write(tmp_path: Path, content: str) -> Path:
    """写入临时文件并返回路径。"""
    filepath = tmp_path / "ic_factor.py"
    filepath.write_text(textwrap.dedent(content).lstrip())
    return filepath


# ─────────────────────────── 合规样本 ───────────────────────────


def test_import_time_exit_2_pass(tmp_path: Path) -> None:
    """模块顶层 try/except register_factor → sys.exit(2) 应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError as e:
            sys.exit(2)
        """,
    )
    assert _check_file(fp) == []


def test_runtime_exit_1_pass(tmp_path: Path) -> None:
    """__main__ except → sys.exit(1) 应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except Exception:
                sys.exit(1)
        """,
    )
    assert _check_file(fp) == []


def test_no_exit_calls_pass(tmp_path: Path) -> None:
    """文件无 sys.exit 调用应通过。"""
    fp = _write(tmp_path, "x = 1\n")
    assert _check_file(fp) == []


def test_combined_correct_pass(tmp_path: Path) -> None:
    """import-time exit 2 + runtime exit 1 同时存在应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError:
            sys.exit(2)

        def main():
            pass

        if __name__ == "__main__":
            try:
                main()
            except DataSchemaError:
                sys.exit(1)
            except Exception:
                sys.exit(1)
        """,
    )
    assert _check_file(fp) == []


# ─────────────────────────── 违规样本 ───────────────────────────


def test_import_time_exit_1_fail(tmp_path: Path) -> None:
    """模块顶层 except 用 sys.exit(1) 应违规。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError:
            sys.exit(1)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "exit 2" in violations[0]
    assert "sys.exit(1)" in violations[0]


def test_runtime_exit_0_fail(tmp_path: Path) -> None:
    """__main__ except 用 sys.exit(0) 隐藏失败应违规。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except Exception:
                sys.exit(0)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "exit(0) 隐藏失败" in violations[0]


def test_runtime_exit_2_fail(tmp_path: Path) -> None:
    """__main__ except 用 sys.exit(2) 应违规（仅 import-time 才是 2）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except Exception:
                sys.exit(2)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "exit 1" in violations[0]
    assert "sys.exit(2)" in violations[0]


def test_exit_no_arg_fail_in_top_try(tmp_path: Path) -> None:
    """顶层 except 中 sys.exit() 无参数应违规。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError:
            sys.exit()
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "无常量参数" in violations[0]


def test_multiple_violations(tmp_path: Path) -> None:
    """多个违规应全部报告。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError:
            sys.exit(1)

        if __name__ == "__main__":
            try:
                main()
            except DataSchemaError:
                sys.exit(0)
            except Exception:
                sys.exit(2)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 3


# ─────────────────────────── 边界条件 ───────────────────────────


def test_exit_outside_except_ignored(tmp_path: Path) -> None:
    """非 except 块内的 sys.exit 不应被检查（如 main() 内 if-else 退出）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        def main():
            if not data_ok:
                sys.exit(1)  # 非 except 内，不检查

        if __name__ == "__main__":
            main()  # 无 except 包裹
            sys.exit(0)  # 非 except 内，不检查
        """,
    )
    assert _check_file(fp) == []


def test_syntax_error_reports(tmp_path: Path) -> None:
    """语法错误应单独报告，不阻塞其他文件检查。"""
    fp = tmp_path / "broken.py"
    fp.write_text("def main(\n")  # 不完整语法
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "语法错误" in violations[0]
