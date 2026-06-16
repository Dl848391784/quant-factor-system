"""
scripts/check_exit_codes.py 的单元测试

覆盖 H12 退出码检查的正反例（R16 修正后语义）：
- 合规：模块顶层 try/except register → logger.critical + raise（禁止 sys.exit）；
        __main__ except → sys.exit(1)
- 违规：顶层 except → sys.exit(任意)；__main__ except → sys.exit(0)；
        __main__ except → sys.exit(2)；顶层 except 既无 sys.exit 也无 raise（吞异常）

对应 PROJECT.md 规则 H12 / AGENTS.md 规则 #6。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.check_exit_codes import _check_file


def _write(tmp_path: Path, content: str) -> Path:
    """写入临时文件并返回路径。"""
    filepath = tmp_path / "ic_factor.py"
    filepath.write_text(textwrap.dedent(content).lstrip())
    return filepath


# ─────────────────────────── 合规样本 ───────────────────────────


def test_import_time_raise_pass(tmp_path: Path) -> None:
    """模块顶层 try/except register_factor → logger.critical + raise 应通过（R16）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError as e:
            logger.critical("注册失败: %s", e)
            raise
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
    """import-time raise + runtime exit 1 同时存在应通过（R16 新模式）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError as e:
            logger.critical("注册失败: %s", e)
            raise

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


def test_import_time_raise_new_exception_pass(tmp_path: Path) -> None:
    """顶层 except 中 raise NewError(...) 也应通过（不限于裸 raise）。"""
    fp = _write(
        tmp_path,
        """
        try:
            SPEC = register_factor(name="x")
        except ValueError as e:
            raise RuntimeError("wrap") from e
        """,
    )
    assert _check_file(fp) == []


# ─────────────────────────── 违规样本 ───────────────────────────


def test_import_time_exit_2_fail(tmp_path: Path) -> None:
    """R16：模块顶层 except 用 sys.exit(2) 应违规（杀 importlib 宿主）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        try:
            SPEC = register_factor(name="x")
        except ValueError:
            sys.exit(2)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "禁止 sys.exit" in violations[0]
    assert "logger.critical + raise" in violations[0]


def test_import_time_exit_1_fail(tmp_path: Path) -> None:
    """R16：模块顶层 except 用 sys.exit(1) 也违规（任何 sys.exit 都禁止）。"""
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
    assert "禁止 sys.exit" in violations[0]


def test_import_time_swallow_exception_fail(tmp_path: Path) -> None:
    """R16：顶层 except 既无 sys.exit 也无 raise → 吞异常违规。"""
    fp = _write(
        tmp_path,
        """
        try:
            SPEC = register_factor(name="x")
        except ValueError:
            pass  # 吞异常
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "必须以 raise 收尾" in violations[0]


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
    """__main__ except Exception 用 sys.exit(2) 应违规（兜底仅允许 exit 1）。"""
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
    assert "exit ∈ [1]" in violations[0]
    assert "sys.exit(2)" in violations[0]


def test_runtime_exit_no_arg_fail(tmp_path: Path) -> None:
    """__main__ except 中 sys.exit() 无参数应违规。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except Exception:
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
            sys.exit(1)  # R16: 顶层禁止 sys.exit

        if __name__ == "__main__":
            try:
                main()
            except DataSchemaError:
                sys.exit(0)  # 隐藏失败
            except Exception:
                sys.exit(2)  # 应为 exit 1
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


# ─────────────────── R17/R18/R19/R20 差异化退出码 ───────────────────


def test_r18_data_schema_exit_4_pass(tmp_path: Path) -> None:
    """R18: __main__ except DataSchemaError 用 sys.exit(4) 应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except DataSchemaError:
                sys.exit(4)
            except Exception:
                sys.exit(1)
        """,
    )
    assert _check_file(fp) == []


def test_r18_data_schema_exit_1_legacy_pass(tmp_path: Path) -> None:
    """R18 旧兼容：DataSchemaError → sys.exit(1) 仍通过（多值允许集合 {1, 4}）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except DataSchemaError:
                sys.exit(1)
        """,
    )
    assert _check_file(fp) == []


def test_r19_factor_calc_exit_5_pass(tmp_path: Path) -> None:
    """R19: __main__ except FactorCalcError 用 sys.exit(5) 应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except FactorCalcError:
                sys.exit(5)
        """,
    )
    assert _check_file(fp) == []


def test_r19_factor_calc_exit_3_fail(tmp_path: Path) -> None:
    """R19: FactorCalcError 用 sys.exit(3) 应违规（{1, 5} 不含 3）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except FactorCalcError:
                sys.exit(3)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "FactorCalcError" in violations[0]
    assert "exit ∈ [1, 5]" in violations[0]


def test_r17_summary_log_exit_3_pass(tmp_path: Path) -> None:
    """R17: __main__ except SummaryLogError 用 sys.exit(3) 应通过。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except SummaryLogError:
                sys.exit(3)
        """,
    )
    assert _check_file(fp) == []


def test_r17_summary_log_exit_1_fail(tmp_path: Path) -> None:
    """R17: SummaryLogError 用 sys.exit(1) 应违规（强制 exit 3，不允许旧兼容）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        if __name__ == "__main__":
            try:
                main()
            except SummaryLogError:
                sys.exit(1)
        """,
    )
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "SummaryLogError" in violations[0]
    assert "exit ∈ [3]" in violations[0]


def test_r20_main_body_sys_exit_fail_when_migrated(tmp_path: Path, monkeypatch) -> None:
    """R20: 已迁移文件的 main() 函数体内 sys.exit 应违规。"""
    import scripts.check_exit_codes as mod

    fp = _write(
        tmp_path,
        """
        import sys

        def main(args):
            if not args:
                sys.exit(1)  # R20 违规
            return 0

        if __name__ == "__main__":
            try:
                main(parse_args())
            except Exception:
                sys.exit(1)
        """,
    )
    # 把临时文件名加入白名单
    monkeypatch.setattr(mod, "R20_MIGRATED_FILES", frozenset({fp.name}))
    violations = _check_file(fp)
    assert len(violations) == 1
    assert "R20 违规" in violations[0]
    assert "main() 函数体内禁 sys.exit" in violations[0]


def test_r20_main_body_sys_exit_pass_when_not_migrated(tmp_path: Path) -> None:
    """R20 旧兼容：未迁移文件 main() 函数体内的 sys.exit(3) 应保持通过（白名单豁免）。"""
    fp = _write(
        tmp_path,
        """
        import sys

        def main():
            try:
                log_factor_summary()
            except Exception:
                sys.exit(3)  # R17 旧实现，未迁移到 R20

        if __name__ == "__main__":
            try:
                main()
            except Exception:
                sys.exit(1)
        """,
    )
    assert _check_file(fp) == []
