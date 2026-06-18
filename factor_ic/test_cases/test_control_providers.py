"""ControlProvider 协议与 IndustryProvider 单元测试（P1.1+P1.2）。

测试范围:
    - 协议契约：runtime_checkable / 必备属性 / 五个方法签名
    - 注册表：build_providers 正常+异常路径
    - IndustryProvider 各方法独立行为（与 industry_neutral_residual 关键步骤一致）

参考: designs/feat_neutralization_framework.md §4.1, §12（测试金字塔单元层）
"""

from __future__ import annotations

import pandas as pd
import pytest

from factor_ic.common.control_providers import (
    PROVIDER_REGISTRY,
    ControlProvider,
    IndustryProvider,
    LogMarketCapProvider,
    build_providers,
)


# ============================================================
# 协议契约测试
# ============================================================


class TestControlProviderProtocol:
    def test_industry_provider_satisfies_protocol(self):
        """IndustryProvider 实例必须满足 ControlProvider 协议（runtime_checkable）。"""
        provider = IndustryProvider()
        assert isinstance(provider, ControlProvider)

    def test_protocol_required_attributes(self):
        """协议要求的三个属性 name / column_type / join_keys 必须存在。"""
        provider = IndustryProvider()
        assert provider.name == "industry"
        assert provider.column_type == "categorical"
        assert provider.join_keys == ["asset"]

    def test_protocol_methods_callable(self):
        """五个方法必须存在且可调用（签名校验交给类型检查器）。"""
        provider = IndustryProvider()
        for method_name in ("load", "preprocess", "to_design_columns", "filter_invalid_rows", "get_meta"):
            assert callable(getattr(provider, method_name)), f"{method_name} 应可调用"


# ============================================================
# 注册表测试
# ============================================================


class TestProviderRegistry:
    def test_registry_contains_industry(self):
        assert "industry" in PROVIDER_REGISTRY

    def test_registry_contains_log_market_cap(self):
        assert "log_market_cap" in PROVIDER_REGISTRY

    def test_build_providers_single(self):
        providers = build_providers(["industry"])
        assert len(providers) == 1
        assert isinstance(providers[0], IndustryProvider)

    def test_build_providers_log_market_cap(self):
        providers = build_providers(["log_market_cap"])
        assert len(providers) == 1
        assert isinstance(providers[0], LogMarketCapProvider)

    def test_build_providers_combined_preserves_order(self):
        providers = build_providers(["industry", "log_market_cap"])
        assert [p.name for p in providers] == ["industry", "log_market_cap"]
        assert isinstance(providers[0], IndustryProvider)
        assert isinstance(providers[1], LogMarketCapProvider)

    def test_build_providers_empty(self):
        """空 specs 返回空列表（design.md §4.1：表示裸 IC，不做中性化）。"""
        assert build_providers([]) == []

    def test_build_providers_unknown_spec_raises(self):
        with pytest.raises(KeyError) as exc_info:
            build_providers(["industry", "unknown_provider"])
        # 错误消息含已注册 key 列表
        assert "unknown_provider" in str(exc_info.value)
        assert "industry" in str(exc_info.value)

    def test_build_providers_duplicate_specs_raises(self):
        """重复 spec name 必须报错（design.md §4.1 唯一性约束）。"""
        with pytest.raises(ValueError) as exc_info:
            build_providers(["industry", "industry"])
        assert "重复" in str(exc_info.value) or "duplicate" in str(exc_info.value).lower()


# ============================================================
# IndustryProvider 各方法测试
# ============================================================


class TestIndustryProviderPreprocess:
    def test_preprocess_drops_other(self):
        """preprocess 必须剔除 industry == '其他' 的行（design.md §3.3 / D6）。"""
        df = pd.DataFrame(
            {
                "asset": ["000001", "000002", "000003", "000004"],
                "industry": ["银行", "其他", "电力设备", "其他"],
            }
        )
        provider = IndustryProvider()
        result = provider.preprocess(df)

        assert len(result) == 2
        assert "其他" not in result["industry"].values
        assert provider.get_meta()["other_dropped"] == 2

    def test_preprocess_no_other_keeps_all(self):
        df = pd.DataFrame({"asset": ["000001", "000002"], "industry": ["银行", "电力设备"]})
        provider = IndustryProvider()
        result = provider.preprocess(df)
        assert len(result) == 2
        assert provider.get_meta()["other_dropped"] == 0


class TestIndustryProviderFilterInvalidRows:
    def test_filter_drops_small_industries(self):
        """股票数 < min_count 的行业整批剔除（与 industry_neutral_residual 一致）。"""
        df = pd.DataFrame(
            {
                "asset": [f"{i:06d}" for i in range(8)],
                "industry": ["银行"] * 5 + ["小行业"] * 2 + ["医药"] * 1,
                "factor": list(range(8)),
            }
        )
        provider = IndustryProvider()
        result = provider.filter_invalid_rows(df, min_count=5)
        # 仅保留 '银行' 5 行
        assert len(result) == 5
        assert (result["industry"] == "银行").all()

    def test_filter_keeps_all_when_all_industries_large(self):
        df = pd.DataFrame(
            {
                "asset": [f"{i:06d}" for i in range(10)],
                "industry": ["银行"] * 5 + ["医药"] * 5,
                "factor": list(range(10)),
            }
        )
        provider = IndustryProvider()
        result = provider.filter_invalid_rows(df, min_count=5)
        assert len(result) == 10


class TestIndustryProviderDesignColumns:
    def test_to_design_columns_drop_first_false(self):
        """drop_first=False 时哑变量列数 == 行业数（保留 P0 行为）。"""
        df = pd.DataFrame({"industry": ["银行", "银行", "医药", "电力设备"]})
        provider = IndustryProvider()
        result = provider.to_design_columns(df, drop_first=False)
        assert result.shape == (4, 3)
        assert set(result.columns) == {"银行", "医药", "电力设备"}

    def test_to_design_columns_drop_first_true(self):
        """drop_first=True 时哑变量列数 == N-1（多元回归共线性护栏）。"""
        df = pd.DataFrame({"industry": ["银行", "银行", "医药", "电力设备"]})
        provider = IndustryProvider()
        result = provider.to_design_columns(df, drop_first=True)
        assert result.shape == (4, 2)


class TestIndustryProviderGetMeta:
    def test_meta_initial_zero(self):
        provider = IndustryProvider()
        meta = provider.get_meta()
        assert meta["other_dropped"] == 0
        assert meta["nan_dropped"] == 0

    def test_meta_returns_copy(self):
        """get_meta 必须返回 copy，避免外部修改污染内部状态。"""
        provider = IndustryProvider()
        meta = provider.get_meta()
        meta["other_dropped"] = 999
        assert provider.get_meta()["other_dropped"] == 0
