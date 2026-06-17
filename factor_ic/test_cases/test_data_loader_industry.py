#!/usr/bin/env python3
"""
data_loader.merge_industry_column 单元测试

验证行业列合并函数（R8 新增）符合 design.md §5.1 Step 2 + §8.2 协议：
- 已知 asset → 申万一级行业名
- 未知 asset → pandas NaN
- '其他' 行业不做特殊处理（透传）
- 不修改入参 DataFrame（返回新对象）

作者: 云瑶
日期: 2026-06-18
关联: design.md §5.1 / §8.2
"""

from __future__ import annotations

import pandas as pd
import pytest

from factor_ic.common.data_loader import merge_industry_column


@pytest.fixture
def fake_industry_map(monkeypatch):
    """patch get_industry_map 返回固定 mock 数据，避免依赖真实 stock_industry.json。"""
    mock_map = {
        "002309": {"name": "中利集团", "industry": "电力设备", "industry_code": "220301"},
        "000001": {"name": "平安银行", "industry": "银行", "industry_code": "480101"},
        "300999": {"name": "测试其他", "industry": "其他", "industry_code": "999999"},
    }

    def _fake():
        return mock_map

    # 函数内部用的是延迟导入 `from data_fetchers.fetch_industry import get_industry_map`，
    # 因此 patch 目标是 fetch_industry 模块本身的属性。
    import data_fetchers.fetch_industry as fi

    monkeypatch.setattr(fi, "get_industry_map", _fake)
    return mock_map


class TestMergeIndustryHappyPath:
    """3.1 已知 asset → 行业名正确合并"""

    def test_known_assets_get_industry_name(self, fake_industry_map):
        df = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 2,
                "asset": ["002309", "000001"],
                "factor_x": [0.5, 0.7],
            }
        )
        out = merge_industry_column(df)

        assert "industry" in out.columns
        assert out.loc[out["asset"] == "002309", "industry"].iloc[0] == "电力设备"
        assert out.loc[out["asset"] == "000001", "industry"].iloc[0] == "银行"

    def test_other_industry_passthrough(self, fake_industry_map):
        """'其他' 不做特殊处理，按原值透传（剔除由 runner 负责，design.md §3.3）"""
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["300999"]})
        out = merge_industry_column(df)
        assert out["industry"].iloc[0] == "其他"


class TestMergeIndustryUnknownAsset:
    """3.2 未知 asset → NaN（design.md §8.2 协议）"""

    def test_unknown_asset_becomes_nan(self, fake_industry_map):
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["999999"]})
        out = merge_industry_column(df)
        assert pd.isna(out["industry"].iloc[0])

    def test_mixed_known_and_unknown(self, fake_industry_map):
        df = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 3,
                "asset": ["002309", "999999", "000001"],
            }
        )
        out = merge_industry_column(df)
        assert out["industry"].iloc[0] == "电力设备"
        assert pd.isna(out["industry"].iloc[1])
        assert out["industry"].iloc[2] == "银行"


class TestMergeIndustryNoPollution:
    """3.3 入参不被修改，原有列保留"""

    def test_input_df_unchanged(self, fake_industry_map):
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["002309"], "factor_x": [0.5]})
        df_before = df.copy()
        _ = merge_industry_column(df)
        pd.testing.assert_frame_equal(df, df_before)
        assert "industry" not in df.columns  # 入参不应被加列

    def test_existing_columns_preserved(self, fake_industry_map):
        df = pd.DataFrame(
            {
                "date": ["2026-01-01"] * 2,
                "asset": ["002309", "000001"],
                "rsi_6": [40.0, 60.0],
                "volume": [1e6, 2e6],
            }
        )
        out = merge_industry_column(df)
        assert list(out.columns) == ["date", "asset", "rsi_6", "volume", "industry"]
        assert out["rsi_6"].tolist() == [40.0, 60.0]


class TestMergeIndustryErrorPath:
    """3.4 异常路径"""

    def test_missing_asset_column_raises(self, fake_industry_map):
        df = pd.DataFrame({"date": ["2026-01-01"], "code": ["002309"]})
        with pytest.raises(KeyError, match="asset"):
            merge_industry_column(df)

    def test_custom_asset_col(self, fake_industry_map):
        df = pd.DataFrame({"date": ["2026-01-01"], "stock_code": ["002309"]})
        out = merge_industry_column(df, asset_col="stock_code")
        assert out["industry"].iloc[0] == "电力设备"

    def test_custom_out_col(self, fake_industry_map):
        df = pd.DataFrame({"date": ["2026-01-01"], "asset": ["002309"]})
        out = merge_industry_column(df, out_col="sw_l1")
        assert "sw_l1" in out.columns
        assert "industry" not in out.columns
        assert out["sw_l1"].iloc[0] == "电力设备"
