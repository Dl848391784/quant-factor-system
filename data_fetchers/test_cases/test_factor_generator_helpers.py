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
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_generator import (
    _calc_pct,
    _nan_to_null,
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


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
