"""freshness_check 期望日期计算测试 (v1.10 report_date 参数).

核心 invariant (对齐 PROJECT.md §核心数据契约):
  报告日 R 清晨拉 prev_td(R) 数据计算。各数据源应有最新日期:
    - 基础源 (master 等):   prev_td(R)      (T-1 数据日)
    - ic_results (衍生):     prev_td(prev_td(R))  (T-2, 需次日收益)

  report_date 参数 = 报告日 R (不是数据日)。
  report_date=None → 回退 date (v1.9 旧行为, 向后兼容)。

背景 (2026-07-19 freshness「△延迟」误报):
  web_ui 旧调用 check_data_freshness(selection_date=07-17 数据日) 作位置参数 date,
  函数内部 prev_td(07-17)=07-16 → 期望比契约(07-17)早一天 → 5 基础源+ic_results 全误报。
  修复: web_ui 改传 report_date=date(报告日 07-18) → prev_td(07-18)=07-17 ✓。
"""

import logging

import pytest
from summary.report.freshness_check import (
    get_expected_t_minus_1,
    get_expected_t_minus_2,
)


@pytest.fixture
def logger():
    return logging.getLogger("test_freshness")


# ---------------------------------------------------------------------------
# 日期工具语义 (契约基础: prev_td 跳周末不跳节假日)
# ---------------------------------------------------------------------------


def test_prev_trading_day_skips_weekend():
    """2026-07-18 周六 → prev_td=07-17 周五; T-2=07-16 周四."""
    assert get_expected_t_minus_1("2026-07-18") == "2026-07-17"
    assert get_expected_t_minus_2("2026-07-18") == "2026-07-16"


def test_prev_trading_day_weekday():
    """2026-07-17 周五 → prev_td=07-16 周四."""
    assert get_expected_t_minus_1("2026-07-17") == "2026-07-16"


# ---------------------------------------------------------------------------
# 核心契约不变量: report_date=报告日 R 时, 期望日期 = 契约应有值
# ---------------------------------------------------------------------------


def test_contract_expected_dates_R_is_saturday():
    """R=2026-07-18(周六): 基础源期望 07-17, ic_results 期望 07-16.

    这是 web_ui 修复后的真实场景: report_date=date='2026-07-18'.
    """
    R = "2026-07-18"
    assert get_expected_t_minus_1(R) == "2026-07-17"  # 基础源应有最新
    assert get_expected_t_minus_2(R) == "2026-07-16"  # ic_results 应有最新


def test_contract_expected_dates_R_is_weekday():
    """R=2026-07-20(周一): 基础源期望 07-17, ic_results 期望 07-16."""
    R = "2026-07-20"
    assert get_expected_t_minus_1(R) == "2026-07-17"
    assert get_expected_t_minus_2(R) == "2026-07-16"


# ---------------------------------------------------------------------------
# 误报根因回归: 数据日当 report_date 会早一天 (锁定"不要这么传")
# ---------------------------------------------------------------------------


def test_data_date_as_report_date_is_off_by_one():
    """把数据日(07-17)当 report_date → 期望 07-16, 比契约(07-17)早一天.

    这是 v1.10 之前的 bug 形态, 锁定为反例: report_date 必须传报告日非数据日。
    """
    data_date = "2026-07-17"  # selection_date (T-1 数据日)
    wrong = get_expected_t_minus_1(data_date)  # = 07-16
    contract_correct = "2026-07-17"  # 契约应有最新
    assert wrong != contract_correct, "数据日当 report_date 会产生早一天误报 (回归锁定)"
    assert wrong == "2026-07-16"
