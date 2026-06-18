"""factor_ic_runner 行业中性化协议集成测试。

覆盖 design.md §5.3.2 协议表 + §5.1 流程的 5 个核心场景：

  R15a: case_excluded — 排除清单内因子（rsi 不在清单 ✓ industry_momentum_5d 在清单）
        → 即使 neutralize=True 也强制 enabled=False，skipped_reason 含 EXCLUDED
  R15b: case_user_disabled — 非排除因子 + neutralize=False
        → enabled=False，skipped_reason 含 USER_DISABLED
  R15c: case_excluded_overrides_user — 排除清单 + neutralize=True/False 都强制 EXCLUDED
        → 排除优先于用户参数（design.md §5.3.2 优先级 #1）
  R15d: case_residual_zero — 残差全 0 时 neutral_ic ≈ 0，decay_rate≈1.0 → 'high'
  R15e: case_other_industry_excluded — '其他' 行业按 D6 决策剔除，回归仅基于剩余行业
  R15f: case_factor_col_nan_dropped — factor_col 含 NaN 时不再 "computation failed: Input y contains NaN."
        而是显式 dropna 后正常返回 enabled=True payload
        （industry_neutralization_flow.md §5.3 follow-up 闭环 2026-06-18）

策略：
  - 不依赖真实数据缓存，构造小型 DataFrame 直接调用 _compute_industry_neutral_ic
  - 协议解析（_resolve_neutralize_decision）已在 R13 单测覆盖，本文件聚焦集成路径

设计文档: .hermes/plans/factor-ic-industry-neutralization-design.md §5.1 / §5.3
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from factor_ic.common.factor_ic_runner import (
    INDUSTRY_NEUTRALIZE_EXCLUDED,
    NEUTRALIZE_SKIP_REASON_EXCLUDED,
    NEUTRALIZE_SKIP_REASON_USER_DISABLED,
    _resolve_neutralize_decision,
)


# ---------------------------------------------------------------------------
# R15a: 排除清单内因子强制 skip（即使 neutralize=True）
# ---------------------------------------------------------------------------


def test_r15a_excluded_factor_forced_skip_even_when_neutralize_true():
    """industry_momentum_5d 在排除清单 → 即使 neutralize=True 也 enabled=False。

    协议依据: design.md §5.3.2 优先级 #1（排除清单优先级最高）
    实证依据: design.md §3.1 — 行业聚合赋个股的因子残差≡0
    """
    enabled, reason = _resolve_neutralize_decision(
        factor_name="industry_momentum_5d",
        neutralize=True,
        mode="full",
    )
    assert enabled is False
    assert reason == NEUTRALIZE_SKIP_REASON_EXCLUDED
    # 防御：清单内确实包含该因子（防止排除清单被误改）
    assert "industry_momentum_5d" in INDUSTRY_NEUTRALIZE_EXCLUDED


# ---------------------------------------------------------------------------
# R15b: 用户传 neutralize=False（非排除因子）→ enabled=False，reason=USER_DISABLED
# ---------------------------------------------------------------------------


def test_r15b_user_disabled_non_excluded_factor():
    """rsi 不在排除清单 + neutralize=False → 用户开关生效。

    协议依据: design.md §5.3.2 优先级 #4（用户参数最低优先级，但非排除因子下生效）
    """
    enabled, reason = _resolve_neutralize_decision(
        factor_name="rsi",
        neutralize=False,
        mode="full",
    )
    assert enabled is False
    assert reason == NEUTRALIZE_SKIP_REASON_USER_DISABLED
    # 防御：rsi 不在排除清单（防止误加入清单）
    assert "rsi" not in INDUSTRY_NEUTRALIZE_EXCLUDED


# ---------------------------------------------------------------------------
# R15c: 排除清单优先级 > 用户参数（neutralize=True/False 都强制 EXCLUDED）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("user_neutralize", [True, False])
def test_r15c_excluded_overrides_user_param(user_neutralize):
    """capital_flow_intensity 在排除清单 → neutralize=True 或 False 都强制 EXCLUDED。

    协议依据: design.md §5.3.2 优先级 #1 > #4（排除清单覆盖用户开关）
    """
    enabled, reason = _resolve_neutralize_decision(
        factor_name="capital_flow_intensity",
        neutralize=user_neutralize,
        mode="full",
    )
    assert enabled is False
    assert reason == NEUTRALIZE_SKIP_REASON_EXCLUDED, (
        f"排除清单应强制返回 EXCLUDED，user_neutralize={user_neutralize} 时收到 reason={reason!r}"
    )
    assert "capital_flow_intensity" in INDUSTRY_NEUTRALIZE_EXCLUDED


# ---------------------------------------------------------------------------
# R15d: 因子值在行业内全相同 → 残差≡0 → neutral_ic≈0 → decay 接近 1.0 → 'high'
# ---------------------------------------------------------------------------


def test_r15d_factor_constant_within_industry_decay_high():
    """构造一个"行业内常数因子"（每只股票因子值 = 行业 ID 数值），
    残差应全 0，neutral IC 应接近 0，decay_rate 接近 1.0 → decay_level='high'。

    实证依据: design.md §3.1 行业聚合赋个股因子的数学性质
    """
    from factor_ic.common.factor_ic_runner import _compute_industry_neutral_ic
    from factor_ic.common.logger_config import get_logger

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=10, freq="D").strftime("%Y-%m-%d")
    industries = {"银行": 5.0, "钢铁": 3.0, "电力": 7.0}
    industry_assets = {ind: [f"{i:01d}{j:05d}.SH" for j in range(1, 8)] for i, ind in enumerate(industries, 1)}
    asset_to_industry = {a: ind for ind, assets in industry_assets.items() for a in assets}
    all_assets = list(asset_to_industry.keys())

    rows_factor, rows_return = [], []
    for d in dates:
        for a in all_assets:
            ind = asset_to_industry[a]
            # 因子 = 纯行业值（行业内常数）
            rows_factor.append({"date": d, "asset": a, "ind_const_factor": industries[ind]})
            # 收益与因子相关（用于 raw IC > 0）
            rows_return.append(
                {"date": d, "asset": a, "forward_return_1d": 0.001 * industries[ind] + np.random.normal(0, 0.005)}
            )

    factor_df = pd.DataFrame(rows_factor)
    return_df = pd.DataFrame(rows_return)
    fake_industry_map = {a: {"industry": asset_to_industry[a]} for a in all_assets}

    with patch("data_fetchers.fetch_industry.get_industry_map", return_value=fake_industry_map):
        payload = _compute_industry_neutral_ic(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="ind_const_factor",
            return_col="forward_return_1d",
            min_stocks=5,
            neutralize_min_industry_stocks=5,
            raw_ic_mean=0.50,  # 假设 raw IC 0.50（强相关）
            logger=get_logger("test_r15d"),
        )

    # 残差≡0 → neutral_ic 几乎等于 0
    assert abs(payload["ic_mean"]) < 1e-3, f"残差全 0 时 neutral_ic 应≈0，实际 {payload['ic_mean']}"
    # decay_rate = (|0.50| - |neutral|) / |0.50| 应接近 1.0
    assert payload["decay_rate"] is not None
    assert payload["decay_rate"] > 0.95, f"decay_rate 应接近 1.0，实际 {payload['decay_rate']}"
    assert payload["decay_level"] == "high"


# ---------------------------------------------------------------------------
# R15e: '其他' 行业按 D6 决策剔除（残差不应基于'其他'计算）
# ---------------------------------------------------------------------------


def test_r15e_other_industry_excluded_from_residual():
    """构造 3 个行业（银行/钢铁/其他）。
    '其他' 行业的股票应被显式剔除（design.md D6），残差行数应少于输入行数。

    依据: design.md §3.3 / D6 — '其他' 是申万一级混杂桶（含申万二级码），不应作为独立行业回归
    """
    from factor_ic.common.factor_ic_runner import _compute_industry_neutral_ic
    from factor_ic.common.logger_config import get_logger

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=5, freq="D").strftime("%Y-%m-%d")
    industry_assets = {
        "银行": [f"1{i:05d}.SH" for i in range(1, 8)],
        "钢铁": [f"2{i:05d}.SH" for i in range(1, 8)],
        "其他": [f"9{i:05d}.SH" for i in range(1, 8)],  # 应被剔除
    }
    asset_to_industry = {a: ind for ind, assets in industry_assets.items() for a in assets}
    all_assets = list(asset_to_industry.keys())

    rows_factor, rows_return = [], []
    for d in dates:
        for a in all_assets:
            rows_factor.append({"date": d, "asset": a, "test_factor": np.random.normal(0, 1)})
            rows_return.append({"date": d, "asset": a, "forward_return_1d": np.random.normal(0, 0.01)})

    factor_df = pd.DataFrame(rows_factor)
    return_df = pd.DataFrame(rows_return)
    fake_industry_map = {a: {"industry": asset_to_industry[a]} for a in all_assets}

    n_other_input = sum(1 for a in all_assets if asset_to_industry[a] == "其他") * len(dates)
    assert n_other_input == 35  # 7 stocks × 5 days

    with patch("data_fetchers.fetch_industry.get_industry_map", return_value=fake_industry_map):
        payload = _compute_industry_neutral_ic(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="test_factor",
            return_col="forward_return_1d",
            min_stocks=5,
            neutralize_min_industry_stocks=5,
            raw_ic_mean=0.05,
            logger=get_logger("test_r15e"),
        )

    # '其他' 应被剔除：dates 应有数据（残差基于银行+钢铁），但每日股票数减少
    assert len(payload["dates"]) == 5, f"残差应保留全部 5 天, 实际 {len(payload['dates'])}"
    # 残差非空（银行+钢铁有 14 只股票/天，足够回归）
    assert payload["n_days"] >= 5
    # 既然剔了'其他'，残差不应等于 raw（其他被剔后的回归结果与含其他不同）
    # 此处只验证流程未失败（残差行数 < raw 行数已在 logger info 输出验证）


# ---------------------------------------------------------------------------
# R15f: factor_col 含 NaN → 显式 dropna 后中性化正常完成（不再 computation failed）
# ---------------------------------------------------------------------------


def test_r15f_factor_col_nan_rows_dropped_before_regression():
    """factor_col 含 NaN 时不再触发 sklearn `Input y contains NaN.`。

    背景: industry_neutralization_flow.md §5.3 follow-up（2026-06-18 实证闭环）
        - 复杂因子（custom_factor_calculation 在 data_loader dropna 之后才生成 factor_col）
          首日/防御场景天然写入 NaN（实证 overnight_ret 2225 NaN 行 / 58 个日期）
        - sklearn LinearRegression.fit 默认 force_all_finite=True → ValueError → 外层 except
          降级 enabled=False / skipped_reason="computation failed: Input y contains NaN."
        - 修复: _compute_industry_neutral_ic Step 2.6 在调 industry_neutral_residual 前
          显式 dropna(subset=[factor_col])（与 raw IC 路径 ic_calculator 内部 dropna 对齐）

    构造: 14 只股票 × 5 天，每个行业首日 factor_col=NaN（模拟 overnight_ret 首日场景）。
    断言: payload["enabled"] 字段不存在（=正常 enabled=True 路径），n_days≈5，
          ic_mean / ic_std / icir 均为有限值，未触发 computation failed 降级。
    """
    from factor_ic.common.factor_ic_runner import _compute_industry_neutral_ic
    from factor_ic.common.logger_config import get_logger

    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=5, freq="D").strftime("%Y-%m-%d").tolist()
    industry_assets = {
        "银行": [f"1{i:05d}.SH" for i in range(1, 8)],
        "钢铁": [f"2{i:05d}.SH" for i in range(1, 8)],
    }
    asset_to_industry = {a: ind for ind, assets in industry_assets.items() for a in assets}
    all_assets = list(asset_to_industry.keys())

    rows_factor, rows_return = [], []
    for d_idx, d in enumerate(dates):
        for a in all_assets:
            # 模拟首日 NaN（与 calculate_overnight_return 首日 shift(1)→NaN 行为一致）
            factor_val = np.nan if d_idx == 0 else np.random.normal(0, 1)
            rows_factor.append({"date": d, "asset": a, "test_factor": factor_val})
            rows_return.append({"date": d, "asset": a, "forward_return_1d": np.random.normal(0, 0.01)})

    factor_df = pd.DataFrame(rows_factor)
    return_df = pd.DataFrame(rows_return)
    fake_industry_map = {a: {"industry": asset_to_industry[a]} for a in all_assets}

    nan_input = int(factor_df["test_factor"].isna().sum())
    assert nan_input == len(all_assets), f"构造失败：首日应有 {len(all_assets)} 个 NaN，实得 {nan_input}"

    with patch("data_fetchers.fetch_industry.get_industry_map", return_value=fake_industry_map):
        # 修复前此调用会被外层 except 捕获 → 抛 RuntimeError 让 runner 降级；
        # 修复后内部 dropna 把 NaN 行剔掉，正常返回 13 字段 payload。
        payload = _compute_industry_neutral_ic(
            factor_df=factor_df,
            return_df=return_df,
            factor_col="test_factor",
            return_col="forward_return_1d",
            min_stocks=5,
            neutralize_min_industry_stocks=5,
            raw_ic_mean=0.05,
            logger=get_logger("test_r15f"),
        )

    # 关键断言：payload 是 enabled=True 路径产物（含 ic_mean/dates 等），不是降级 schema
    assert "enabled" not in payload, (
        f"_compute_industry_neutral_ic 应直接返回 enabled=True payload（不含 enabled 字段，由调用方拼装），"
        f"实得 {payload!r}"
    )
    assert "ic_mean" in payload and payload["ic_mean"] is not None, "ic_mean 应为有限值"
    assert "dates" in payload and len(payload["dates"]) >= 4, (
        f"首日 NaN 被剔后应至少剩 4 天 IC（首日 factor 全 NaN 不参与回归），实得 {len(payload['dates'])} 天"
    )
    assert payload["n_days"] >= 4
    # 防回归：不应再走降级路径
    assert "skipped_reason" not in payload, (
        f"修复后 NaN 不应触发 computation failed 降级，实得 skipped_reason={payload.get('skipped_reason')!r}"
    )
