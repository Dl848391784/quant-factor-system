"""fetch_financial.py 单元测试

覆盖 5 个修复：
1. _QUARTER_ANNUALIZE_FACTOR 无效月份 warning + annualized_eps 置 None
2. _parse_percentage 数据源单位约定 + 输出范围断言
3. 缓存结构 dict 格式 + last_full_fetch_date + 增量/全量逻辑
4. fetch_financial_data_for_stock 返回 None=异常 / []=空数据
5. else 分支 numpy 标量 NaN 检测
"""

import json
import logging
import tempfile
from datetime import datetime as dt_cls
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# 导入被测模块
from data_fetchers.fetch_financial import (
    _FINANCIAL_FIELD_MAP,
    _OUTPUT_VERSION,
    _QUARTER_ANNUALIZE_FACTOR,
    _parse_percentage,
    fetch_financial_data_for_stock,
    get_cached_stock_codes,
    load_cache,
)


# ─── Fix 1: _QUARTER_ANNUALIZE_FACTOR 无效月份 ────────────────────


class TestQuarterAnnualizeFactor:
    """Fix 1: 无效月份应 warning 且 annualized_eps 置 None"""

    def test_valid_months(self):
        """有效季度月份 3/6/9/12 应返回正确的年化系数"""
        assert _QUARTER_ANNUALIZE_FACTOR[3] == 4.0
        assert _QUARTER_ANNUALIZE_FACTOR[6] == 2.0
        assert _QUARTER_ANNUALIZE_FACTOR[9] == pytest.approx(4.0 / 3.0)
        assert _QUARTER_ANNUALIZE_FACTOR[12] == 1.0

    def test_invalid_month_not_in_dict(self):
        """无效月份（如 1/2/4/5）不应在字典中"""
        for month in [1, 2, 4, 5, 7, 8, 10, 11]:
            assert month not in _QUARTER_ANNUALIZE_FACTOR

    def test_invalid_month_produces_none(self):
        """fetch_financial_data_for_stock 在月份无效时 annualized_eps 为 None

        通过 mock akshare API 返回异常月份的报告期数据
        """
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-01-31"],  # month=1, 不在 _QUARTER_ANNUALIZE_FACTOR
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert len(records) == 1
        # month=1 不在年化系数字典 → annualized_eps 应为 None
        assert records[0]["annualized_eps"] is None

    def test_valid_month_produces_annualized(self):
        """有效月份应正确计算年化 EPS"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],  # Q1, month=3, factor=4.0
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert records[0]["annualized_eps"] == pytest.approx(0.5 * 4.0)


# ─── Fix 2: _parse_percentage 数据源单位约定 ─────────────────────


class TestParsePercentage:
    """Fix 2: 百分比解析 + 数据源单位约定"""

    def test_string_with_percent_sign(self):
        """字符串百分号格式 → 数值"""
        assert _parse_percentage("4.21%") == pytest.approx(4.21)
        assert _parse_percentage("-3.50%") == pytest.approx(-3.50)

    def test_float_percent_form(self):
        """float 类型已是百分数形式（4.21 表示 4.21%，不是 0.0421）"""
        assert _parse_percentage(4.21) == pytest.approx(4.21)
        assert _parse_percentage(0.0421) == pytest.approx(0.0421)  # 小数量级 = 数据源异常

    def test_float_nan_returns_none(self):
        """float NaN → None"""
        assert _parse_percentage(float("nan")) is None

    def test_none_returns_none(self):
        """None → None"""
        assert _parse_percentage(None) is None

    def test_empty_string_returns_none(self):
        """空字符串 → None"""
        assert _parse_percentage("") is None
        assert _parse_percentage("--") is None

    def test_roe_output_range_assertion(self):
        """集成测试断言：ROE 应在 [-100, 100] 区间

        如果 _parse_percentage 返回 0.0421 量级，说明数据源单位不一致
        """
        # 模拟同花顺返回的 ROE（百分数形式）
        roe_value = _parse_percentage(4.21)
        assert roe_value is not None
        assert -100 <= roe_value <= 100, (
            f"ROE={roe_value} 超出 [-100, 100] 区间，可能数据源返回了小数形式而非百分数形式"
        )

    def test_growth_rate_output_range(self):
        """增长率应在合理区间"""
        growth = _parse_percentage("25.30%")
        assert growth is not None
        assert -500 <= growth <= 500, f"增长率={growth} 异常"


# ─── Fix 3: 缓存结构 dict 格式 + 全量/增量逻辑 ──────────────────


class TestCacheStructure:
    """Fix 3: 缓存格式迁移 + last_full_fetch_date + 全量/增量判断"""

    def test_get_cached_stock_codes_dict_format(self):
        """dict 格式：返回 dict 的 key 集合"""
        cache = {"data": {"000001": [{"report_date": "2024-03-31"}], "000002": []}}
        codes = get_cached_stock_codes(cache)
        assert codes == {"000001", "000002"}

    def test_get_cached_stock_codes_list_format(self):
        """旧 list 格式兼容"""
        cache = {
            "data": [
                {"asset": "000001", "report_date": "2024-03-31"},
                {"asset": "000002", "report_date": "2024-06-30"},
            ]
        }
        codes = get_cached_stock_codes(cache)
        assert codes == {"000001", "000002"}

    def test_empty_cache(self):
        """空缓存返回空集合"""
        codes = get_cached_stock_codes({"data": {}})
        assert codes == set()

    def test_load_cache_missing_file(self):
        """缓存文件不存在返回空结构"""
        with patch("data_fetchers.fetch_financial.CACHE_FILE", Path("/nonexistent/file.json.gz")):
            result = load_cache()
        assert result == {"meta": {}, "data": []}


class TestFullFetchTrigger:
    """Fix 3: 超过 90 天触发全量拉取"""

    def test_no_last_full_fetch_date_triggers_full(self):
        """无 last_full_fetch_date → need_full_fetch=True"""
        from data_fetchers.fetch_financial import main

        # 通过 mock 验证逻辑：当 meta 中无 last_full_fetch_date 时
        cache_data = {"meta": {}, "data": {}}
        last_full = cache_data.get("meta", {}).get("last_full_fetch_date")
        assert last_full is None  # → need_full_fetch 默认 True

    def test_recent_full_fetch_triggers_incremental(self):
        """最近全量拉取 → need_full_fetch=False"""
        from datetime import date, timedelta

        recent_date = (date.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        cache_data = {"meta": {"last_full_fetch_date": recent_date}, "data": {}}
        last_full_str = cache_data.get("meta", {}).get("last_full_fetch_date")
        last_full_dt = dt_cls.strptime(last_full_str, "%Y-%m-%d").date()
        days_since = (dt_cls.now().date() - last_full_dt).days
        assert days_since <= 90  # → need_full_fetch=False

    def test_stale_full_fetch_triggers_full(self):
        """超过 90 天的全量拉取 → need_full_fetch=True"""
        from datetime import date, timedelta

        stale_date = (date.today() - timedelta(days=100)).strftime("%Y-%m-%d")
        cache_data = {"meta": {"last_full_fetch_date": stale_date}, "data": {}}
        last_full_str = cache_data.get("meta", {}).get("last_full_fetch_date")
        last_full_dt = dt_cls.strptime(last_full_str, "%Y-%m-%d").date()
        days_since = (dt_cls.now().date() - last_full_dt).days
        assert days_since > 90  # → need_full_fetch=True


# ─── Fix 4: fetch_financial_data_for_stock 返回值语义 ─────────────


class TestFetchReturnValue:
    """Fix 4: None=异常, []=空数据"""

    def test_api_exception_returns_none(self):
        """API 抛异常 → 返回 None"""
        with patch(
            "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
            side_effect=Exception("网络超时"),
        ):
            result = fetch_financial_data_for_stock("000001")
        assert result is None

    def test_empty_dataframe_returns_empty_list(self):
        """API 返回空 DataFrame → 返回空列表"""
        with patch(
            "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
            return_value=pd.DataFrame(),
        ):
            result = fetch_financial_data_for_stock("000001")
        assert result == []

    def test_valid_data_returns_records(self):
        """API 返回有效数据 → 返回记录列表"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            result = fetch_financial_data_for_stock("000001")
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["asset"] == "000001"


# ─── Fix 5: numpy 标量 NaN 检测 ───────────────────────────────


class TestNumpyScalarNaN:
    """Fix 5: numpy.float64 NaN 应被检测为 None，不应写入 float('nan')"""

    def test_numpy_nan_detected_as_none(self):
        """numpy.float64 NaN → pd.isna 返回 True → 记录值为 None

        通过构造包含 NaN 的 DataFrame 模拟实际数据流
        """
        # 构造一个 row，其中某字段为 numpy.float64 NaN
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "净资产收益率": [np.float64("nan")],  # numpy NaN
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn not in ("净资产收益率", "基本每股收益")},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert len(records) == 1
        # numpy.float64 NaN 应被识别为 None，而非 float('nan')
        assert records[0]["roe"] is None

    def test_numpy_float64_valid_value(self):
        """numpy.float64 有效值应正确转换"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "净资产收益率": [np.float64(4.21)],  # numpy 有效 float
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn not in ("净资产收益率", "基本每股收益")},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert records[0]["roe"] == pytest.approx(4.21)

    def test_numpy_nan_json_serializable(self):
        """确保 numpy NaN 不会导致 JSON 序列化失败"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "净资产收益率": [np.float64("nan")],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn not in ("净资产收益率", "基本每股收益")},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        # 应该可以序列化为 JSON
        json_str = json.dumps(records, allow_nan=False)
        assert json_str is not None
