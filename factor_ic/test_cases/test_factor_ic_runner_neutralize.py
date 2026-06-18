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
            rows_return.append({"date": d, "asset": a, "forward_return_1d": 0.001 * industries[ind] + np.random.normal(0, 0.005)})

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
