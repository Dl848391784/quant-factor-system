"""factor_summary_logger 公共模块单元测试。

覆盖场景(参考设计文档 §7.1):
  1. 正常路径(4 字段均为数值): 1 条 INFO,0 条 WARNING
  2. 错误路径(4 字段全 None,模拟 build_error_result): 1 条 INFO + 1 条 WARNING
  3. 扩展行注入: extra_summary_lines 正确追加到 INFO 摘要末尾
  4. 部分 None(理论不可达): 仅含 None 字段名出现在 WARNING

设计文档: factor_ic/docs/plans/factor_ic_warning_unification_design.md
"""

from __future__ import annotations

import logging

import pytest

from factor_ic.common.factor_summary_logger import log_factor_summary


def _normal_result() -> dict:
    """构造正常路径 result fixture(4 字段均为数值)。"""
    return {
        "factor_name": "amplitude_delta",
        "update_mode": "full",
        "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "sample_stats": {"valid_days": 240},
        "ic_metrics": {"ic_mean": 0.05, "ic_std": 0.12, "icir": 0.42},
        "ic_distribution_consistency": {"positive_ratio": 0.55},
    }


def _error_result() -> dict:
    """构造错误路径 result fixture(模拟 build_error_result,4 字段均为 None)。"""
    return {
        "factor_name": "amplitude_delta",
        "update_mode": "full",
        "period": {"start": "", "end": ""},
        "sample_stats": {"valid_days": 0},
        "ic_metrics": {"ic_mean": None, "ic_std": None, "icir": None},
        "ic_distribution_consistency": {"positive_ratio": None},
    }


class TestNormalPath:
    """正常路径: 4 字段均为数值。"""

    def test_only_one_info_no_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """应输出 1 条 INFO 摘要,0 条 WARNING。"""
        logger = logging.getLogger("test_normal_path")
        with caplog.at_level(logging.INFO, logger="test_normal_path"):
            log_factor_summary(_normal_result(), "振幅差分因子", logger)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(info_records) == 1
        assert len(warning_records) == 0

    def test_info_contains_formatted_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """INFO 摘要应含格式化数值(IC 均值: 0.0500 等)。"""
        logger = logging.getLogger("test_normal_path_fmt")
        with caplog.at_level(logging.INFO, logger="test_normal_path_fmt"):
            log_factor_summary(_normal_result(), "振幅差分因子", logger)

        text = caplog.text
        assert "IC 均值: 0.0500" in text
        assert "IC 标准差: 0.1200" in text
        assert "ICIR: 0.42" in text
        assert "IC>0 占比: 55.00%" in text


class TestErrorPath:
    """错误路径: 4 字段全 None(模拟 build_error_result)。"""

    def test_one_info_one_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """应输出 1 条 INFO(字段 N/A)+ 1 条 WARNING(整合告警)。"""
        logger = logging.getLogger("test_error_path")
        with caplog.at_level(logging.INFO, logger="test_error_path"):
            log_factor_summary(_error_result(), "振幅差分因子", logger)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(info_records) == 1
        assert len(warning_records) == 1

    def test_info_shows_na(self, caplog: pytest.LogCaptureFixture) -> None:
        """错误路径下 IC 字段应显示 N/A,与现状一致。"""
        logger = logging.getLogger("test_error_path_na")
        with caplog.at_level(logging.INFO, logger="test_error_path_na"):
            log_factor_summary(_error_result(), "振幅差分因子", logger)

        text = caplog.text
        assert "IC 均值: N/A" in text
        assert "IC 标准差: N/A" in text
        assert "ICIR: N/A" in text
        assert "IC>0 占比: N/A" in text

    def test_warning_contains_factor_name_and_all_fields(self, caplog: pytest.LogCaptureFixture) -> None:
        """WARNING 必须含因子中文名 + 4 字段名 + 运维提示(§2.3 信息密度契约)。"""
        logger = logging.getLogger("test_error_path_w")
        with caplog.at_level(logging.WARNING, logger="test_error_path_w"):
            log_factor_summary(_error_result(), "振幅差分因子", logger)

        warning_text = next(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
        assert "振幅差分因子" in warning_text
        assert "ic_mean" in warning_text
        assert "ic_std" in warning_text
        assert "icir" in warning_text
        assert "positive_ratio" in warning_text
        # 运维提示
        assert "数据加载可能失败" in warning_text
        assert "build_error_result" in warning_text


class TestExtraSummaryLines:
    """扩展行注入: ic_past_return_1d_1d 等例外脚本场景。"""

    def test_extra_lines_appended(self, caplog: pytest.LogCaptureFixture) -> None:
        """extra_summary_lines 应追加到 INFO 摘要末尾。"""
        logger = logging.getLogger("test_extra_lines")
        with caplog.at_level(logging.INFO, logger="test_extra_lines"):
            log_factor_summary(
                _normal_result(),
                "过去 1 日涨幅因子",
                logger,
                extra_summary_lines=["因子方向: positive"],
            )

        text = caplog.text
        assert "因子方向: positive" in text
        # 扩展行不影响 WARNING(正常路径不该有 WARNING)
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 0

    def test_none_extra_lines_no_extension(self, caplog: pytest.LogCaptureFixture) -> None:
        """extra_summary_lines=None 时摘要无追加,与不传等价。"""
        logger = logging.getLogger("test_extra_none")
        with caplog.at_level(logging.INFO, logger="test_extra_none"):
            log_factor_summary(_normal_result(), "振幅差分因子", logger, extra_summary_lines=None)

        # 摘要应止于 IC>0 占比行
        text = caplog.text
        assert "IC>0 占比: 55.00%" in text
        # 不应出现误注入字符串
        assert "因子方向" not in text


class TestPartialNone:
    """部分 None(理论不可达,但兜底覆盖避免未来逻辑变化遗漏)。"""

    def test_only_ic_std_none(self, caplog: pytest.LogCaptureFixture) -> None:
        """ic_std 单独为 None 时,WARNING 仅含 ic_std 字段名。"""
        result = _normal_result()
        result["ic_metrics"]["ic_std"] = None

        logger = logging.getLogger("test_partial_none")
        with caplog.at_level(logging.WARNING, logger="test_partial_none"):
            log_factor_summary(result, "振幅差分因子", logger)

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_records) == 1
        warning_text = warning_records[0].getMessage()
        assert "ic_std" in warning_text
        # 其他三字段不应出现
        assert "ic_mean," not in warning_text
        assert "icir" not in warning_text
        assert "positive_ratio" not in warning_text


class TestLoggerRouting:
    """logger 传递: 验证日志写到调用方 logger,符合 M3 规范。"""

    def test_uses_passed_logger(self, caplog: pytest.LogCaptureFixture) -> None:
        """日志记录的 name 必须是调用方传入的 logger,而非公共模块内部 logger。"""
        custom_logger = logging.getLogger("custom.factor.entry_script")
        with caplog.at_level(logging.INFO, logger="custom.factor.entry_script"):
            log_factor_summary(_normal_result(), "振幅差分因子", custom_logger)

        info_records = [r for r in caplog.records if r.levelno == logging.INFO]
        assert len(info_records) == 1
        assert info_records[0].name == "custom.factor.entry_script"
