#!/usr/bin/env python
"""
factor_generator.py 内部 helper 函数单元测试

位置: data_fetchers/test_cases/test_factor_generator_helpers.py
创建时间: 2026-06-16
用途: 隔离测试 _calc_pct / _nan_to_null / _write_factor_json_gz 等
      纯函数 helper，不依赖真实数据文件，可在 CI 快速运行。

覆盖范围：
- _calc_pct: 正常场景 + 除零保护 + inf/NaN 保护
- _nan_to_null: float/numpy 标量 NaN/inf 转 None + 嵌套递归
- _write_factor_json_gz: 原子写入 + 异常时临时文件清理
"""

from __future__ import annotations

import gzip
import json
import logging
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_generator import (
    _atomic_write_json,
    _calc_pct,
    _load_json_gz_data,
    _nan_to_null,
    _run_pipeline_step,
    _write_factor_json_gz,
)


# ============================================================================
# _calc_pct: 百分比计算 + 除零保护 + 非有限值保护
# ============================================================================


class TestCalcPct:
    """_calc_pct 单元测试"""

    def test_normal_case(self) -> None:
        """正常场景：80/100 = 80.0"""
        assert _calc_pct(80, 100) == 80.0

    def test_partial_case(self) -> None:
        """部分场景：20/100 = 20.0"""
        assert _calc_pct(20, 100) == 20.0

    def test_zero_total(self) -> None:
        """除零保护：total=0 返回 0.0"""
        assert _calc_pct(50, 0) == 0.0

    def test_negative_total(self) -> None:
        """负数 total 返回 0.0（防御性）"""
        assert _calc_pct(50, -10) == 0.0

    def test_inf_total(self) -> None:
        """total=inf 返回 0.0（避免伪装成有效计算）"""
        assert _calc_pct(50, float("inf")) == 0.0  # type: ignore[arg-type]

    def test_neg_inf_total(self) -> None:
        """total=-inf 返回 0.0"""
        assert _calc_pct(50, float("-inf")) == 0.0  # type: ignore[arg-type]

    def test_nan_total(self) -> None:
        """total=NaN 返回 0.0"""
        assert _calc_pct(50, float("nan")) == 0.0  # type: ignore[arg-type]

    def test_inf_count(self) -> None:
        """count=inf 时结果非有限，返回 0.0（避免返回 inf）"""
        assert _calc_pct(float("inf"), 100) == 0.0  # type: ignore[arg-type]

    def test_rounding(self) -> None:
        """保留两位小数"""
        assert _calc_pct(1, 3) == 33.33


# ============================================================================
# _nan_to_null: 递归 NaN/inf → None
# ============================================================================


class TestNanToNull:
    """_nan_to_null 单元测试"""

    def test_float_nan(self) -> None:
        """Python float NaN → None"""
        assert _nan_to_null(float("nan")) is None

    def test_float_inf(self) -> None:
        """Python float inf → None"""
        assert _nan_to_null(float("inf")) is None

    def test_float_neg_inf(self) -> None:
        """Python float -inf → None"""
        assert _nan_to_null(float("-inf")) is None

    def test_numpy_float64_nan(self) -> None:
        """numpy.float64 NaN → None（pandas to_dict 输出场景）"""
        assert _nan_to_null(np.float64("nan")) is None

    def test_numpy_float32_nan(self) -> None:
        """numpy.float32 NaN → None（不是 float 子类，需 np.floating 兜底）"""
        assert _nan_to_null(np.float32("nan")) is None

    def test_numpy_float64_inf(self) -> None:
        """numpy.float64 inf → None"""
        assert _nan_to_null(np.float64("inf")) is None

    def test_numpy_float32_inf(self) -> None:
        """numpy.float32 inf → None"""
        assert _nan_to_null(np.float32("inf")) is None

    def test_normal_float_unchanged(self) -> None:
        """普通 float 不退化"""
        assert _nan_to_null(1.5) == 1.5

    def test_int_unchanged(self) -> None:
        """int 不受影响"""
        assert _nan_to_null(42) == 42

    def test_string_unchanged(self) -> None:
        """字符串不受影响"""
        assert _nan_to_null("hello") == "hello"

    def test_none_unchanged(self) -> None:
        """None 保持 None"""
        assert _nan_to_null(None) is None

    def test_bool_unchanged(self) -> None:
        """bool 不被误判（bool 不是 float 子类）"""
        assert _nan_to_null(True) is True
        assert _nan_to_null(False) is False

    def test_dict_recursive(self) -> None:
        """dict 递归"""
        result = _nan_to_null({"a": float("nan"), "b": 1.0, "c": "x"})
        assert result == {"a": None, "b": 1.0, "c": "x"}

    def test_list_recursive(self) -> None:
        """list 递归"""
        result = _nan_to_null([1.0, float("nan"), float("inf"), "x"])
        assert result == [1.0, None, None, "x"]

    def test_nested_structure(self) -> None:
        """嵌套结构（pandas to_dict('records') 输出形态）"""
        records = [
            {"date": "2026-01-01", "asset": "000001", "factor": np.float64("nan")},
            {"date": "2026-01-02", "asset": "000002", "factor": np.float32("inf")},
            {"date": "2026-01-03", "asset": "000003", "factor": 0.5},
        ]
        result = _nan_to_null(records)
        assert result == [
            {"date": "2026-01-01", "asset": "000001", "factor": None},
            {"date": "2026-01-02", "asset": "000002", "factor": None},
            {"date": "2026-01-03", "asset": "000003", "factor": 0.5},
        ]


# ============================================================================
# _write_factor_json_gz: 原子写入 + 异常清理
# ============================================================================


@pytest.fixture
def silent_logger() -> logging.Logger:
    """静默 logger（避免污染 pytest 输出）"""
    logger = logging.getLogger("test_factor_generator_helpers")
    logger.handlers.clear()
    logger.addHandler(logging.NullHandler())
    return logger


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """最小样例 DataFrame（包含 NaN，验证 _nan_to_null 集成）"""
    return pd.DataFrame(
        [
            {"date": "2026-01-01", "asset": "000001", "factor": 0.5},
            {"date": "2026-01-02", "asset": "000001", "factor": float("nan")},
        ]
    )


class TestWriteFactorJsonGz:
    """_write_factor_json_gz 单元测试"""

    def test_success_no_temp_left(
        self,
        tmp_path: Path,
        sample_df: pd.DataFrame,
        silent_logger: logging.Logger,
    ) -> None:
        """成功写入：目标文件存在，临时文件不存在"""
        output_path = tmp_path / "out.json.gz"
        _write_factor_json_gz(sample_df, output_path, silent_logger)

        assert output_path.exists(), "目标文件应存在"
        temp_path = output_path.parent / (output_path.name + ".tmp")
        assert not temp_path.exists(), "临时文件应已被原子替换"

        # 验证内容（含 NaN→null 转换）
        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            payload: dict[str, Any] = json.load(f)
        assert payload["dates"] == ["2026-01-01", "2026-01-02"]
        assert payload["data"][1]["factor"] is None  # NaN → null

    def test_gzip_write_failure_cleans_temp(
        self,
        tmp_path: Path,
        sample_df: pd.DataFrame,
        silent_logger: logging.Logger,
    ) -> None:
        """gzip 写入过程抛 OSError：临时文件被清理，无目标文件"""
        output_path = tmp_path / "out.json.gz"

        # 模拟 json.dump 第一次调用（写 dates_list）抛 OSError
        with (
            patch("data_fetchers.factor_generator.json.dump", side_effect=OSError("disk full")),
            pytest.raises(RuntimeError, match="文件系统错误"),
        ):
            _write_factor_json_gz(sample_df, output_path, silent_logger)

        temp_path = output_path.parent / (output_path.name + ".tmp")
        assert not temp_path.exists(), "失败时临时文件必须清理"
        assert not output_path.exists(), "失败时目标文件不应被创建"

    def test_replace_succeeds_target_not_deleted(
        self,
        tmp_path: Path,
        sample_df: pd.DataFrame,
        silent_logger: logging.Logger,
    ) -> None:
        """边界场景：os.replace 成功后即使后续抛异常（理论上不会发生），
        目标文件也不应被 finally 清理。

        通过 mock os.replace 副作用：先正常 replace，再人为抛 RuntimeError。
        """
        output_path = tmp_path / "out.json.gz"

        import os as _os

        real_replace = _os.replace

        def replace_then_raise(src: Any, dst: Any) -> None:
            real_replace(src, dst)
            raise RuntimeError("post-replace failure")

        with (
            patch("data_fetchers.factor_generator.os.replace", side_effect=replace_then_raise),
            pytest.raises(RuntimeError, match="未知错误保存失败"),
        ):
            _write_factor_json_gz(sample_df, output_path, silent_logger)

        # 关键断言：os.replace 已成功，目标文件存在且未被 finally 清理
        assert output_path.exists(), "os.replace 成功后目标文件不应被清理"
        temp_path = output_path.parent / (output_path.name + ".tmp")
        assert not temp_path.exists(), "临时文件已被 replace 移走"


# ============================================================================
# _load_json_gz_data: gzip + JSON 加载 + 日志策略
# ============================================================================


class TestLoadJsonGzData:
    """_load_json_gz_data 单元测试（重点验证两个 except 分支均打 logger.error）"""

    def test_success(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """正常加载：返回 'data' 字段内容"""
        path = tmp_path / "ok.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"data": [{"a": 1}, {"a": 2}]}, f)

        result = _load_json_gz_data(path, "测试", silent_logger)
        assert result == [{"a": 1}, {"a": 2}]

    def test_file_not_found(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """文件不存在 → FileNotFoundError（无日志，调用栈足够清晰）"""
        path = tmp_path / "missing.json.gz"
        with pytest.raises(FileNotFoundError, match="测试数据文件不存在"):
            _load_json_gz_data(path, "测试", silent_logger)

    def test_bad_gzip_logs_error(
        self,
        tmp_path: Path,
    ) -> None:
        """gzip 损坏 → logger.error 被调用 + ValueError 抛出"""
        path = tmp_path / "broken.json.gz"
        # 非 gzip 内容
        path.write_bytes(b"not a gzip file")

        logger = logging.getLogger("test_bad_gzip")
        logger.handlers.clear()
        with patch.object(logger, "error") as mock_error, pytest.raises(ValueError, match="gzip 文件损坏"):
            _load_json_gz_data(path, "测试", logger)

        mock_error.assert_called_once()
        # 验证日志参数包含 path（第一个 % 占位符）
        args = mock_error.call_args.args
        assert "gzip 文件损坏" in args[0]
        assert path in args  # path 是其中一个位置参数

    def test_json_decode_error_logs_error(
        self,
        tmp_path: Path,
    ) -> None:
        """JSON 解析失败 → logger.error 被调用（与 BadGzipFile 一致策略）+ ValueError 抛出"""
        path = tmp_path / "bad_json.json.gz"
        # 合法 gzip 包装非法 JSON
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write("{not valid json")

        logger = logging.getLogger("test_bad_json")
        logger.handlers.clear()
        with patch.object(logger, "error") as mock_error, pytest.raises(ValueError, match="JSON解析失败"):
            _load_json_gz_data(path, "测试", logger)

        # 关键断言：JSONDecodeError 分支必须打 logger.error（修复前缺失）
        mock_error.assert_called_once()
        args = mock_error.call_args.args
        assert "JSON解析失败" in args[0]
        # 验证不引用 e.doc（避免内存翻倍）：参数中不应含完整 JSON 文本
        assert "{not valid json" not in str(args)

    def test_missing_data_field(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """缺 'data' 字段 → ValueError"""
        path = tmp_path / "no_data.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"other_field": []}, f)

        with pytest.raises(ValueError, match="测试数据缺少 'data' 字段"):
            _load_json_gz_data(path, "测试", silent_logger)


# ============================================================================
# _atomic_write_json: 小型 JSON 原子写出（Step 15 列名清单等场景）
# ============================================================================


class TestAtomicWriteJson:
    """_atomic_write_json 单元测试（写入 → 原子替换 → finally 清理）"""

    def test_success_creates_file(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """正常写入：目标文件存在，临时文件不存在"""
        path = tmp_path / "manifest.json"
        payload = {"all_cols": ["a", "b", "c"], "generated_at": "2026-06-16 10:00:00"}

        _atomic_write_json(payload, path, silent_logger)

        # 目标文件存在 + 内容匹配
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == payload
        # 临时文件已被 os.replace 移走
        assert not (tmp_path / "manifest.json.tmp").exists()

    def test_chinese_content_no_escape(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """ensure_ascii=False：中文 / 因子名直接可读"""
        path = tmp_path / "zh.json"
        payload = {"因子": ["振幅", "换手率"]}

        _atomic_write_json(payload, path, silent_logger)

        text = path.read_text(encoding="utf-8")
        # 直接含中文（未被 \uXXXX 转义）
        assert "振幅" in text
        assert "换手率" in text

    def test_overwrite_existing_atomically(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """覆盖已存在文件：os.replace 原子替换"""
        path = tmp_path / "existing.json"
        path.write_text('{"old": "data"}', encoding="utf-8")

        _atomic_write_json({"new": "data"}, path, silent_logger)

        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"new": "data"}

    def test_write_failure_cleans_temp_file(
        self,
        tmp_path: Path,
    ) -> None:
        """json.dump 失败时（不可序列化对象）：临时文件被 finally 清理"""
        path = tmp_path / "bad.json"
        # set 不可 json.dump → TypeError → 临时文件已写部分内容但 os.replace 未执行
        unserializable: Any = {"k": {1, 2, 3}}

        logger = logging.getLogger("test_atomic_write_fail")
        logger.handlers.clear()

        with pytest.raises(TypeError):
            _atomic_write_json(unserializable, path, logger)

        # 关键断言：临时文件被 finally 清理（避免目录残留）
        assert not (tmp_path / "bad.json.tmp").exists()
        # 目标文件未生成（os.replace 未执行）
        assert not path.exists()

    def test_replace_success_does_not_unlink_target(
        self,
        tmp_path: Path,
        silent_logger: logging.Logger,
    ) -> None:
        """关键回归：os.replace 成功后 finally 不应误删目标文件

        与 _write_factor_json_gz 的 replaced 标志同源问题。"""
        path = tmp_path / "target.json"
        _atomic_write_json({"a": 1}, path, silent_logger)

        # 目标文件依然存在（finally 因 replaced=True 未删）
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"a": 1}


# ============================================================================
# _run_pipeline_step: factor_func 漏写列时的精确错误归因（bug 2）
# ============================================================================


class TestRunPipelineStepMissingCols:
    """_run_pipeline_step 提前校验 output_cols 缺失（bug 2 回归）"""

    def test_factor_func_missing_one_col_raises_keyerror(
        self,
        silent_logger: logging.Logger,
    ) -> None:
        """factor_func 漏写一列：抛 KeyError，消息含函数名 + 缺失列名 + 实际列"""

        def buggy_factor_func(df: pd.DataFrame, *, logger_arg: logging.Logger) -> pd.DataFrame:
            df = df.copy()
            df["partial_col_a"] = 1.0
            # 故意漏写 partial_col_b
            return df

        step = {
            "step_label": "Test step",
            "factor_func": buggy_factor_func,
            "output_cols": ("partial_col_a", "partial_col_b"),
            "emit_valid_log": False,
        }
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["A"]})

        with pytest.raises(KeyError) as exc_info:
            _run_pipeline_step(df, step, silent_logger)

        msg = str(exc_info.value)
        # 关键断言：错误消息必须含归因信息
        assert "buggy_factor_func" in msg
        assert "partial_col_b" in msg
        # 且不应误报已写入的列
        assert "['partial_col_a', 'partial_col_b']" in msg or "'partial_col_b'" in msg

    def test_factor_func_writes_all_cols_no_error(
        self,
        silent_logger: logging.Logger,
    ) -> None:
        """factor_func 全部写入：正常返回"""

        def good_factor_func(df: pd.DataFrame, *, logger_arg: logging.Logger) -> pd.DataFrame:
            df = df.copy()
            df["col_a"] = 1.0
            df["col_b"] = 2.0
            return df

        step = {
            "step_label": "Test step",
            "factor_func": good_factor_func,
            "output_cols": ("col_a", "col_b"),
            "emit_valid_log": False,
        }
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["A"]})

        result_df, valid_counts = _run_pipeline_step(df, step, silent_logger)
        assert valid_counts == {"col_a": 1, "col_b": 1}
        assert "col_a" in result_df.columns
        assert "col_b" in result_df.columns

    def test_tail_factor_missing_3_of_5_cols(
        self,
        silent_logger: logging.Logger,
    ) -> None:
        """模拟用户报告场景：tail 因子返回 5 列但 factor_func 只写 2 列"""

        def partial_tail_func(df: pd.DataFrame, *, logger_arg: logging.Logger) -> pd.DataFrame:
            df = df.copy()
            df["tail_col_1"] = 1.0
            df["tail_col_2"] = 2.0
            # 漏写 tail_col_3 / 4 / 5
            return df

        step = {
            "step_label": "Step 11: 计算尾盘因子...",
            "factor_func": partial_tail_func,
            "output_cols": ("tail_col_1", "tail_col_2", "tail_col_3", "tail_col_4", "tail_col_5"),
            "emit_valid_log": True,
        }
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["A"]})

        with pytest.raises(KeyError, match="partial_tail_func"):
            _run_pipeline_step(df, step, silent_logger)


# ============================================================================
# main CLI 入口：quiet 模式下成功反馈走 print(stdout)
# ============================================================================


class TestMainQuietMode:
    """main() 函数 quiet / 非 quiet 模式下的成功反馈渠道（bug 1 回归）"""

    @pytest.fixture
    def fake_metadata(self) -> dict[str, Any]:
        return {
            "generated_at": "2026-06-16 17:30:00",
            "elapsed_seconds": 1.23,
            "total_records": 9876,
            "valid_records": {},
            "valid_records_percent": {},
            "factor_columns": [],
            "return_columns": [],
            "input_sources": {},
            "output_path": "/tmp/fake_factor_ic_data.json.gz",
        }

    def test_quiet_mode_prints_summary_to_stdout(
        self,
        fake_metadata: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quiet 模式：成功反馈必须走 print（绕过 ERROR 级别过滤）"""
        from data_fetchers import factor_generator as fg

        monkeypatch.setattr(sys, "argv", ["factor_generator.py", "--quiet"])
        with patch.object(fg, "generate_all_factors", return_value=fake_metadata):
            rc = fg.main()

        assert rc == 0
        captured = capsys.readouterr()
        # 关键断言：摘要 + 退出码必须出现在 stdout
        assert "执行摘要" in captured.out
        assert "总记录数=9876" in captured.out
        assert "耗时=1.23秒" in captured.out
        assert "执行成功，退出码: 0" in captured.out

    def test_default_mode_uses_logger_info(
        self,
        fake_metadata: dict[str, Any],
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """默认模式：成功反馈走 logger.info（不走 print，避免日志重复）"""
        from data_fetchers import factor_generator as fg

        monkeypatch.setattr(sys, "argv", ["factor_generator.py"])
        with patch.object(fg, "generate_all_factors", return_value=fake_metadata):
            rc = fg.main()

        assert rc == 0
        captured = capsys.readouterr()
        # 关键断言：默认模式下 stdout 不应有 print 出来的摘要（避免重复）
        # 注：logger 输出去 stderr，不影响 stdout
        assert "执行摘要" not in captured.out
        assert "执行成功，退出码: 0" not in captured.out

    def test_quiet_mode_failure_returns_1(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quiet 模式失败路径不受影响：仍返回 1，logger.exception 走 ERROR 级别"""
        from data_fetchers import factor_generator as fg

        monkeypatch.setattr(sys, "argv", ["factor_generator.py", "--quiet"])
        with patch.object(fg, "generate_all_factors", side_effect=RuntimeError("boom")):
            rc = fg.main()

        assert rc == 1
        captured = capsys.readouterr()
        # 失败路径不应打成功消息
        assert "执行成功" not in captured.out


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
