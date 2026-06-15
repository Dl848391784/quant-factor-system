"""factor_ic_runner 启动横幅 extra_log_params 单元测试。

覆盖场景(参考设计文档 §6 Step 1 + §9 风险预案):
  1. 不传 extra_log_params: 横幅含 4 行（=、因子名、入口参数、=），无"扩展参数"行
  2. 传空 dict: 视同 None,不打印"扩展参数"行
  3. 传单参数 (int): "扩展参数: n=9"
  4. 传多参数 (mixed types): 顺序保留,各类型正确转字符串
  5. 传含 None 值: %s 安全转换为 "None" 字符串,不抛 TypeError
  6. 传 bool / float: 正确格式化为 "True" / "1.5"

设计文档: factor_ic/docs/plans/factor_ic_startup_log_dedup_design.md §6 Step 1
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: 直接调用横幅打印逻辑,绕过 IC 计算（不依赖数据缓存/真实 pipeline）
# ---------------------------------------------------------------------------


def _capture_startup_banner(extra_log_params, *, min_stocks=10, force_full=False):
    """构造 mock logger 调用 run_factor_ic_analysis 横幅段,返回 logger.info 调用日志。

    使用 patch 拦截 check_data_completeness 抛 SystemExit 提前退出,避免触达数据加载。
    """
    from factor_ic.common import factor_ic_runner

    mock_logger = MagicMock(spec=logging.Logger)

    # 让横幅之后第一个外部函数 get_ic_output_path 抛异常,提前退出避免触达数据加载
    # （选择 get_ic_output_path 而非 check_data_completeness 是因为 force_full=True
    #   会跳过 check_data_completeness,需要选一个两条路径都会调用的提前退出锚点）
    with (
        patch.object(factor_ic_runner, "get_ic_output_path", side_effect=RuntimeError("stop after banner")),
        pytest.raises(RuntimeError, match="stop after banner"),
    ):
        factor_ic_runner.run_factor_ic_analysis(
            factor_name="test_factor",
            factor_col="test_col",
            return_period="1d",
            min_stocks=min_stocks,
            force_full=force_full,
            extra_log_params=extra_log_params,
            _logger=mock_logger,
        )

    # 提取所有 logger.info 调用的渲染字符串（仿 logging 实际行为）
    info_messages = []
    for call in mock_logger.info.call_args_list:
        args, _kwargs = call
        if len(args) == 1:
            info_messages.append(args[0])
        else:
            # % 惰性格式化: args[0] 是模板, args[1:] 是参数
            info_messages.append(args[0] % args[1:])
    return info_messages


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_no_extra_log_params_no_extension_line():
    """场景 1: 不传 extra_log_params,横幅不含"扩展参数"行。"""
    messages = _capture_startup_banner(extra_log_params=None)

    # 横幅前 4 行（force_full=False 时模式判断会进 check_data_completeness 触发 RuntimeError）
    assert messages[0] == "=" * 60
    assert messages[1] == "因子 IC 分析: test_factor_1d"
    assert messages[2] == "入口参数: min_stocks=10, force_full=False"
    assert messages[3] == "=" * 60

    # 检查没有任何"扩展参数:"开头的消息
    assert not any(m.startswith("扩展参数:") for m in messages)


def test_empty_dict_no_extension_line():
    """场景 2: 空 dict 视同 None,不打印"扩展参数"行。"""
    messages = _capture_startup_banner(extra_log_params={})
    assert not any(m.startswith("扩展参数:") for m in messages)


def test_single_int_param():
    """场景 3: 单参数 (int)。"""
    messages = _capture_startup_banner(extra_log_params={"n": 9})
    extra_lines = [m for m in messages if m.startswith("扩展参数:")]
    assert len(extra_lines) == 1
    assert extra_lines[0] == "扩展参数: n=9"


def test_multi_params_mixed_types():
    """场景 4: 多参数 mixed types,顺序保留。"""
    messages = _capture_startup_banner(
        extra_log_params={"n": 9, "m1": 3, "m2": 3},
    )
    extra_lines = [m for m in messages if m.startswith("扩展参数:")]
    assert len(extra_lines) == 1
    assert extra_lines[0] == "扩展参数: n=9, m1=3, m2=3"


def test_param_with_none_value():
    """场景 5: 含 None 值,%s 安全转换为 "None"。"""
    messages = _capture_startup_banner(extra_log_params={"version": None, "k": 2})
    extra_lines = [m for m in messages if m.startswith("扩展参数:")]
    assert len(extra_lines) == 1
    assert extra_lines[0] == "扩展参数: version=None, k=2"


def test_param_with_bool_and_float():
    """场景 6: bool / float 类型正确格式化。"""
    messages = _capture_startup_banner(
        extra_log_params={"enable": True, "threshold": 1.5},
    )
    extra_lines = [m for m in messages if m.startswith("扩展参数:")]
    assert len(extra_lines) == 1
    assert extra_lines[0] == "扩展参数: enable=True, threshold=1.5"


def test_force_full_true_in_entry_params():
    """force_full=True 应正确反映在入口参数行。"""
    messages = _capture_startup_banner(extra_log_params=None, force_full=True)
    assert "入口参数: min_stocks=10, force_full=True" in messages


def test_min_stocks_custom_in_entry_params():
    """min_stocks 自定义值应正确反映在入口参数行。"""
    messages = _capture_startup_banner(extra_log_params=None, min_stocks=20)
    assert "入口参数: min_stocks=20, force_full=False" in messages
