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
    _BASE_COLS,
    _FACTOR_PIPELINE_STEPS,
    _OHLCV_INDEX_COLS,
    _atomic_write_json,
    _calc_pct,
    _json_safe_value,
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
# _json_safe_value: 单值 JSON 安全转换
# ============================================================================


class TestJsonSafeValue:
    """_json_safe_value 单值转换测试"""

    def test_float_nan_to_none(self) -> None:
        """float NaN → None。"""
        assert _json_safe_value(float("nan")) is None

    def test_numpy_scalar_to_python_scalar(self) -> None:
        """numpy 标量转换为 json.dump 可处理的 Python 标量。"""
        assert _json_safe_value(np.float64(1.25)) == 1.25
        assert type(_json_safe_value(np.float64(1.25))) is float
        assert _json_safe_value(np.int64(3)) == 3
        assert type(_json_safe_value(np.int64(3))) is int
        assert _json_safe_value(np.bool_(True)) is True

    def test_normal_values_unchanged(self) -> None:
        """普通 Python 值保持原样。"""
        assert _json_safe_value("000001") == "000001"
        assert _json_safe_value(1.5) == 1.5


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

    # ------------------------------------------------------------------ #
    # R3 兜底：np.integer / np.bool_ / tuple 转换（json.dump TypeError 防御）
    # ------------------------------------------------------------------ #

    def test_numpy_int64_to_python_int(self) -> None:
        """np.int64 → Python int（json.dump 不支持 np.int64）"""
        result = _nan_to_null(np.int64(42))
        assert result == 42
        assert type(result) is int  # 必须是原生 int 而非 np.int64

    def test_numpy_int32_to_python_int(self) -> None:
        """np.int32 同样降级为 Python int"""
        result = _nan_to_null(np.int32(7))
        assert result == 7
        assert type(result) is int

    def test_numpy_uint8_to_python_int(self) -> None:
        """np.uint8（无符号）也走 np.integer 分支降级"""
        result = _nan_to_null(np.uint8(255))
        assert result == 255
        assert type(result) is int

    def test_numpy_bool_true_to_python_bool(self) -> None:
        """np.bool_(True) → Python True，必须保留布尔语义而非 1"""
        result = _nan_to_null(np.bool_(True))
        assert result is True
        assert type(result) is bool  # 不是 int(1)

    def test_numpy_bool_false_to_python_bool(self) -> None:
        """np.bool_(False) → Python False，必须保留布尔语义而非 0"""
        result = _nan_to_null(np.bool_(False))
        assert result is False
        assert type(result) is bool

    def test_tuple_recursive_returns_list(self) -> None:
        """tuple 容器递归并返回 list（JSON 没有 tuple 类型）"""
        result = _nan_to_null((1.0, float("nan"), np.int64(3)))
        assert result == [1.0, None, 3]
        assert type(result) is list

    def test_mixed_numpy_scalars_in_records(self) -> None:
        """复合场景：records 含 NaN + np.int64 + np.bool_，确保 json.dump 可序列化"""
        import json

        records = [
            {
                "asset": "000001",
                "rank": np.int64(1),
                "selected": np.bool_(True),
                "factor": np.float64("nan"),
            },
            {
                "asset": "000002",
                "rank": np.int32(2),
                "selected": np.bool_(False),
                "factor": 0.5,
            },
        ]
        result = _nan_to_null(records)
        # json.dump 必须不抛 TypeError
        serialized = json.dumps(result, allow_nan=False)
        assert "NaN" not in serialized  # 严格 JSON：不允许 NaN 字面量
        # 反序列化后字段值与类型语义正确
        deserialized = json.loads(serialized)
        assert deserialized[0]["rank"] == 1 and deserialized[0]["selected"] is True
        assert deserialized[0]["factor"] is None
        assert deserialized[1]["rank"] == 2 and deserialized[1]["selected"] is False


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

    def test_streaming_writer_does_not_call_to_dict(
        self,
        tmp_path: Path,
        sample_df: pd.DataFrame,
        silent_logger: logging.Logger,
    ) -> None:
        """写出路径禁止回退到 DataFrame.to_dict('records') 批量对象图。"""
        output_path = tmp_path / "out.json.gz"

        with patch.object(pd.DataFrame, "to_dict", side_effect=AssertionError("to_dict forbidden")):
            _write_factor_json_gz(sample_df, output_path, silent_logger)

        with gzip.open(output_path, "rt", encoding="utf-8") as f:
            payload: dict[str, Any] = json.load(f)
        assert len(payload["data"]) == 2

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
# _FACTOR_PIPELINE_STEPS: emit_valid_log 取值规格守护（bug 4）
# ============================================================================


class TestPipelineEmitValidLogSpec:
    """_FACTOR_PIPELINE_STEPS 的 emit_valid_log 取值规格守护。

    bug 4 修复：Step 11.6~11.9 段头因子改为 emit_valid_log=True，
    同段后续因子保持 False。本测试守护该规格不被意外回退。
    """

    # 必须 emit_valid_log=True 的段头因子（bug 4 修复后）
    SECTION_HEAD_FACTORS_TRUE = {
        "volume_price_strength",  # Step 11.6 段头
        "industry_momentum_5d",  # Step 11.7 段头
        "industry_roe_trend",  # Step 11.8 行业财务三因子 block 段头
        "capital_flow_ratio_trend",  # Step 11.9 资金流双因子 block 段头
    }

    # 必须 emit_valid_log=False 的同段后续因子（避免刷屏）
    SECTION_FOLLOW_FACTORS_FALSE = {
        "positive_day_ratio_5",
        "ma5_deviation",
        "near_high_ratio_5",
        "industry_turnover_trend",
        "industry_amplitude_trend",
    }

    def test_step_11_6_to_11_9_section_heads_emit_true(self) -> None:
        """段头因子（共 4 个）必须 emit_valid_log=True"""
        actual_true_factors = {
            step["output_cols"][0]
            for step in _FACTOR_PIPELINE_STEPS
            if step["emit_valid_log"] and step["output_cols"][0] in self.SECTION_HEAD_FACTORS_TRUE
        }
        assert actual_true_factors == self.SECTION_HEAD_FACTORS_TRUE, (
            f"Step 11.6~11.9 段头因子应全部 emit=True, 缺失: {self.SECTION_HEAD_FACTORS_TRUE - actual_true_factors}"
        )

    def test_step_11_6_to_11_9_followers_emit_false(self) -> None:
        """同段后续因子（共 5 个）必须 emit_valid_log=False（避免日志刷屏）"""
        actual_false_factors = {
            step["output_cols"][0]
            for step in _FACTOR_PIPELINE_STEPS
            if not step["emit_valid_log"] and step["output_cols"][0] in self.SECTION_FOLLOW_FACTORS_FALSE
        }
        assert actual_false_factors == self.SECTION_FOLLOW_FACTORS_FALSE, (
            f"Step 11.6~11.9 同段后续因子应全部 emit=False, "
            f"误置 True: {self.SECTION_FOLLOW_FACTORS_FALSE - actual_false_factors}"
        )

    def test_emit_false_count_matches_spec(self) -> None:
        """emit_valid_log=False 的因子数应 = 5（同段后续）。

        Step 11.8 行业财务与 Step 11.9 资金流均为单 step block；
        block 内部负责输出多列有效率，不再把第二/第三列建成独立 follower step。
        """
        false_count = sum(1 for step in _FACTOR_PIPELINE_STEPS if not step["emit_valid_log"])
        assert false_count == 5, (
            f"emit_valid_log=False 数量异常: {false_count}, 应为 5（Step 11.8/11.9 均为单 step block）"
        )


# ============================================================================
# 模块常量一致性：_OHLCV_INDEX_COLS 与 _BASE_COLS 关系（bug 3 守护）
# ============================================================================


class TestOhlcvIndexColsConsistency:
    """_OHLCV_INDEX_COLS 用于 Step 1 日志识别基础因子列，
    必须是 _BASE_COLS 的真子集（_BASE_COLS - _OHLCV_INDEX_COLS = 基础因子列）"""

    def test_ohlcv_index_cols_is_strict_subset_of_base_cols(self) -> None:
        """所有 OHLCV + 索引列必须都在 _BASE_COLS 中（否则 Step 1 日志错误）"""
        base_set = set(_BASE_COLS)
        assert _OHLCV_INDEX_COLS.issubset(base_set), (
            f"_OHLCV_INDEX_COLS 含 _BASE_COLS 之外的列: {_OHLCV_INDEX_COLS - base_set}"
        )

    def test_ohlcv_index_cols_excludes_base_factors(self) -> None:
        """_OHLCV_INDEX_COLS 必须不含基础因子（否则 Step 1 日志会过滤掉它们）"""
        # 当前已知的基础因子列（fetch_factor_cache 输出）
        known_base_factors = {"rsi_6", "volume_ratio_5", "turnover_rate"}
        leaked = known_base_factors & _OHLCV_INDEX_COLS
        assert not leaked, f"基础因子被误列入 _OHLCV_INDEX_COLS: {leaked}"

    def test_diff_yields_known_base_factors(self) -> None:
        """_BASE_COLS - _OHLCV_INDEX_COLS 应给出当前基础因子集合
        （此测试在新增/删除基础因子时会失败，提示同步更新 Step 1 日志或常量）"""
        diff = set(_BASE_COLS) - _OHLCV_INDEX_COLS
        # 当前基础因子：rsi_6 / volume_ratio_5 / turnover_rate
        assert diff == {"rsi_6", "volume_ratio_5", "turnover_rate"}, (
            f"_BASE_COLS 与 _OHLCV_INDEX_COLS 差集不符合预期: {diff}, 如新增/删除基础因子，请同步更新本测试与相关常量"
        )


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
# R1 段首校验回归：_FACTOR_PIPELINE_STEPS[0]['step_label'] 不得为 None
# ============================================================================


class TestPipelineStepLabelValidation:
    """模块加载期段首校验（R1 初始化 + R3 扩展为全表遍历）

    约束：每个 step_label=None 的 step 之前必须已有非 None step_label，
    否则该段整段无段头日志且无报错。原 [0] 校验无法防中间段首误写 None。
    """

    def test_first_step_has_non_none_label(self) -> None:
        """_FACTOR_PIPELINE_STEPS[0]['step_label'] 不得为 None / 空字符串。"""
        from data_fetchers.factor_generator import _FACTOR_PIPELINE_STEPS

        assert _FACTOR_PIPELINE_STEPS, "_FACTOR_PIPELINE_STEPS 不应为空"
        first_label = _FACTOR_PIPELINE_STEPS[0]["step_label"]
        assert first_label is not None and first_label != "", (
            f"_FACTOR_PIPELINE_STEPS[0]['step_label'] 不得为 None / 空字符串，实际: {first_label!r}"
        )

    def test_no_empty_string_step_labels(self) -> None:
        """R1 修复后，所有 step_label 应为 str（非空）或 None，不再有空字符串 ''。"""
        from data_fetchers.factor_generator import _FACTOR_PIPELINE_STEPS

        for i, step in enumerate(_FACTOR_PIPELINE_STEPS):
            label = step["step_label"]
            assert label != "", (
                f"_FACTOR_PIPELINE_STEPS[{i}]['step_label'] 为空字符串 ''，"
                f"应改为 None（R1 新约定：续表用 None，不再用 ''）"
            )

    def test_no_none_before_any_non_none_label(self) -> None:
        """R3 全表遍历：每个 None 的 step 之前必须已有非 None step_label。

        若中间某段首误写 None（前段有 label，但本段新段首也写 None），
        该段将无段头日志。校验覆盖 [0] 无法发现的中间段首问题。
        """
        from data_fetchers.factor_generator import _FACTOR_PIPELINE_STEPS

        seen_non_none = False
        for i, step in enumerate(_FACTOR_PIPELINE_STEPS):
            if step["step_label"] is not None:
                seen_non_none = True
            elif not seen_non_none:
                pytest.fail(
                    f"_FACTOR_PIPELINE_STEPS[{i}]['step_label'] 为 None 但此前无任何非 None step_label，段首缺失"
                )


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

    def test_quiet_mode_failure_prints_to_stderr(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """quiet 模式失败时必须 print 到 stderr（与成功 print 到 stdout 对称，bug 4 回归）。

        修复前问题：成功走 print(stdout)，失败仅走 logger（混合 stdout/stderr 输出渠道），
        quiet 用户无法在统一 stream 上判断结果。
        """
        from data_fetchers import factor_generator as fg

        monkeypatch.setattr(sys, "argv", ["factor_generator.py", "--quiet"])
        with patch.object(fg, "generate_all_factors", side_effect=RuntimeError("disk full")):
            rc = fg.main()

        assert rc == 1
        captured = capsys.readouterr()
        # 关键断言：quiet 失败必须 print 到 stderr，包含异常类型与消息
        assert "执行失败" in captured.err
        assert "RuntimeError" in captured.err
        assert "disk full" in captured.err
        # stdout 不应被失败消息污染（成功消息走 stdout，失败走 stderr，渠道分离）
        assert "执行失败" not in captured.out

    def test_default_mode_failure_no_print(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """默认模式失败不走 print（仅 logger.exception，避免日志重复）。"""
        from data_fetchers import factor_generator as fg

        monkeypatch.setattr(sys, "argv", ["factor_generator.py"])
        with patch.object(fg, "generate_all_factors", side_effect=RuntimeError("boom")):
            rc = fg.main()

        assert rc == 1
        captured = capsys.readouterr()
        # 默认模式不应有 print 到 stderr 的失败消息（logger 已处理）
        # 注：logger 也可能输出到 stderr，但 print 的格式 "执行失败: RuntimeError: boom" 不应被 print 走
        # 用 stdout 反向验证（默认模式 print 任何消息都为异常）
        assert "执行失败:" not in captured.out


class TestOutputDfNoneSentinel:
    """generate_all_factors output_df 生命周期约定（bug 1 回归 + R2 内存修复回归）

    历史：
    - bug 1（None sentinel 时代）：output_df 在 try 前 = None，try 内 copy，
      finally 用 `if output_df is not None` 守卫。禁止 `"output_df" in locals()`
      因 locals() 在 CPython 中不可靠且有性能开销。
    - R2 修复：del factor_df 从 try 内移到 try 之前。为此 output_df 切片也必须
      上提到 try 之前（missing_cols 检查通过后立即执行），try 进入时 output_df
      一定存在。None sentinel 失去意义，finally 改为无守卫 `del output_df`。
    - R3 拆分：output_df 相关逻辑从 generate_all_factors 移入
      _format_and_write_output，测试搜索目标同步更新。

    本测试组保留两条核心防御：
    1. output_df 在 try 之前已赋值（避免回退到 try 内首次赋值 → 再次出现
       del factor_df 跳过的内存泄漏路径）
    2. finally 永不使用 `"output_df" in locals()` 守卫（locals 反模式）
    """

    def test_output_df_assigned_before_try(self) -> None:
        """源码约定：output_df 首次赋值在 try 块之前（R2 内存修复关键约束）。

        通过 AST 静态解析验证：
        1. 在 _format_and_write_output 函数体顶层找到首个 output_df 赋值
        2. 该赋值在所有 ast.Try 节点之前（行号严格小于）

        若首次赋值落到 try 内，意味着 del factor_df 也回到 try 内，
        copy 抛 KeyError 时 factor_df 大对象将随异常持续驻留外层栈帧。
        """
        import ast
        from pathlib import Path

        from data_fetchers import factor_generator as fg

        source = Path(fg.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # R3: output_df 从 generate_all_factors 移入 _format_and_write_output
        func = next(
            (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_format_and_write_output"),
            None,
        )
        assert func is not None, "_format_and_write_output 函数未找到"

        # 在函数体直接子节点中查找首个 output_df 赋值（不深入子作用域）
        first_assign_node: ast.AST | None = None
        for node in func.body:
            # AnnAssign: output_df: ... = ...
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "output_df":
                first_assign_node = node
                break
            # Assign: output_df = ...
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "output_df" for t in node.targets
            ):
                first_assign_node = node
                break

        assert first_assign_node is not None, "未在 _format_and_write_output 函数体顶层找到 output_df 赋值"

        # 找到函数体顶层的 ast.Try（包裹 Step 13~15 的那个），验证 output_df 赋值在其之前
        try_nodes = [n for n in func.body if isinstance(n, ast.Try)]
        assert try_nodes, "_format_and_write_output 顶层未找到 try/finally 块（Step 13~15 包裹）"
        first_try = try_nodes[0]

        assert first_assign_node.lineno < first_try.lineno, (
            f"output_df 首次赋值（行 {first_assign_node.lineno}）必须在 try 块（行 {first_try.lineno}）之前。"
            f"若回退到 try 内首次赋值，del factor_df 将再次受到 KeyError 影响（R2 修复回归）。"
        )

    def test_finally_does_not_use_locals_guard(self) -> None:
        """源码约定：finally 块禁止使用 `"output_df" in locals()` 守卫（bug 1 回归）。

        locals() 在 CPython 异常退出帧时不可靠且每次构造新 dict，是已知反模式。
        R2 修复后 output_df 使用 None sentinel + `if output_df is not None` 守卫，
        finally 安全释放。本测试只防御 locals() 反模式重新出现。
        """
        from pathlib import Path

        from data_fetchers import factor_generator as fg

        source = Path(fg.__file__).read_text(encoding="utf-8")
        assert '"output_df" in locals()' not in source, (
            'finally 中不得使用 `"output_df" in locals()`：locals() 在 CPython 中不可靠且有性能开销'
        )


class TestAllColsCountsConsistency:
    """_ALL_COLS_COUNTS 与各源元组长度一致（bug 2 回归）"""

    def test_all_cols_counts_matches_source_tuples(self) -> None:
        """_ALL_COLS_COUNTS 字段值必须等于对应元组的 len()，不允许手动数字硬编码偏离。"""
        from data_fetchers.factor_generator import (
            _ALL_COLS_COUNTS,
            _BASE_COLS,
            _EXTENDED_FACTOR_COLS,
            _FLAG_COLS,
            _OUTPUT_COLS,
            _RETURN_COLS,
        )

        assert _ALL_COLS_COUNTS["base_cols"] == len(_BASE_COLS)
        assert _ALL_COLS_COUNTS["extended_factor_cols"] == len(_EXTENDED_FACTOR_COLS)
        assert _ALL_COLS_COUNTS["return_cols"] == len(_RETURN_COLS)
        assert _ALL_COLS_COUNTS["flag_cols"] == len(_FLAG_COLS)
        assert _ALL_COLS_COUNTS["total"] == len(_OUTPUT_COLS)
        # 求和也必须等于 total（防止有人在元组以外加列）
        assert (
            _ALL_COLS_COUNTS["base_cols"]
            + _ALL_COLS_COUNTS["extended_factor_cols"]
            + _ALL_COLS_COUNTS["return_cols"]
            + _ALL_COLS_COUNTS["flag_cols"]
            == _ALL_COLS_COUNTS["total"]
        )

    def test_output_cols_definition_has_no_stale_count(self) -> None:
        """_OUTPUT_COLS 定义上方的注释禁止出现过时的硬编码数字（如 (15)）。

        反面案例：曾经写 `_EXTENDED_FACTOR_COLS(15)` 但实际是 31，导致维护者误判。
        """
        import re
        from pathlib import Path

        from data_fetchers import factor_generator as fg

        source = Path(fg.__file__).read_text(encoding="utf-8")
        # 定位 _OUTPUT_COLS 定义所在行的前 5 行注释（注释区域）
        lines = source.split("\n")
        out_idx = next((i for i, line in enumerate(lines) if line.startswith("_OUTPUT_COLS:")), -1)
        assert out_idx > 0, "_OUTPUT_COLS 定义未找到"
        comment_block = "\n".join(lines[max(0, out_idx - 5) : out_idx])

        # 反例：禁止 _BASE_COLS(数字) / _EXTENDED_FACTOR_COLS(数字) / _RETURN_COLS(数字)
        # 形式的硬编码数字注释（容易过时）
        stale_pattern = re.compile(r"_(BASE|EXTENDED_FACTOR|RETURN)_COLS\(\d+\)")
        match = stale_pattern.search(comment_block)
        assert match is None, (
            f"_OUTPUT_COLS 注释禁止硬编码列数 `{match.group(0) if match else ''}`，列数已迁移至 _ALL_COLS_COUNTS 运行时计算"
        )


class TestPipelineStepsAndColsConsistency:
    """_FACTOR_PIPELINE_STEPS 表注释中 step 数与列数一致（bug 3 回归）"""

    def test_pipeline_step_count_matches_table_length(self) -> None:
        """注释中的 step 数必须等于 _FACTOR_PIPELINE_STEPS 实际长度。"""
        from data_fetchers.factor_generator import _FACTOR_PIPELINE_STEPS

        assert len(_FACTOR_PIPELINE_STEPS) == 24, "_FACTOR_PIPELINE_STEPS 当前为 24 个 step"

    def test_pipeline_output_cols_count_matches_extended_factor_cols(self) -> None:
        """所有 step 的 output_cols 总数必须等于 _EXTENDED_FACTOR_COLS 长度。"""
        from data_fetchers.factor_generator import _EXTENDED_FACTOR_COLS, _FACTOR_PIPELINE_STEPS

        total_output_cols = sum(len(step["output_cols"]) for step in _FACTOR_PIPELINE_STEPS)
        assert total_output_cols == len(_EXTENDED_FACTOR_COLS), (
            f"pipeline 输出列总数 {total_output_cols} 应等于 _EXTENDED_FACTOR_COLS 长度 {len(_EXTENDED_FACTOR_COLS)}"
        )

    def test_pipeline_comment_distinguishes_step_and_col_counts(self) -> None:
        """generate_all_factors 中 Step 3.5~11.9 段注释必须明确区分 step 数与列数。

        反例：曾经写 \"_FACTOR_PIPELINE_STEPS 表（24 项）\"，
        \"项\" 既可指 step 也可指 col 造成歧义。
        """
        from pathlib import Path

        from data_fetchers import factor_generator as fg

        source = Path(fg.__file__).read_text(encoding="utf-8")
        # 反例：禁止仅写 "（N 项）" 的模糊计数
        assert "_FACTOR_PIPELINE_STEPS 表（24 项）" not in source, (
            '_FACTOR_PIPELINE_STEPS 表注释禁用模糊 "项" 字，必须区分 step 数与列数'
        )
        # 正例：必须明确包含 \"step\" 与 \"输出列\" 字段
        assert "_FACTOR_PIPELINE_STEPS 表（24 个 step，31 个输出列）" in source, (
            '_FACTOR_PIPELINE_STEPS 表注释必须形如 "（24 个 step，31 个输出列）"'
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
