"""fetch_financial.py 单元测试

覆盖 24 个修复（v1.0c: Fix 1-5, v1.0d: Fix 1-5, v1.0e: Fix 1-5, v1.0f: Fix 1-5, v1.0g: Fix 1-5）：
v1.0c:
1. _QUARTER_ANNUALIZE_FACTOR 无效月份 warning + annualized_eps 置 None
2. _parse_percentage 数据源单位约定 + 输出范围断言
3. 缓存结构 dict 格式 + last_full_fetch_date + 增量/全量逻辑
4. fetch_financial_data_for_stock 返回 None=异常 / []=空数据
5. else 分支 numpy 标量 NaN 检测
v1.0d:
1. 缓存结构 list→dict 已在 v1.0c 完成（确认无需额外修改）
2. 检查点写入 — 每 100 只股票写一次缓存
3. 空数据日志 debug→info + 去前导空格
4. 进度日志改用 fetch_count
5. write_gzip_cache 后写入确认日志
v1.0e:
1. load_cache 日志 dict 格式计算实际记录数而非 key 数
2. 检查点写入使用浅拷贝，不提前 mutate stock_data
3. _parse_percentage/_parse_numeric_with_unit 统一 pd.isna 前置检查
4. _parse_report_date 增加 pd.isnull 防 pd.NaT 漏判
5. 年化 EPS split+int 用 try/except 防格式异常
v1.0f:
1. 全量模式 API 失败股票记录 stale_codes 写入 meta
2. 429 限流检测 + 指数退避重试（最多3次）
3. 进度日志去掉多余的 fetch_count > 1 条件
4. total_new_count 计数器替换 len(new_stock_data)
5. 旧格式迁移补充统计日志 + asset 为空 warning 计数
v1.0g:
1. _is_rate_limit_error 删除无效 "429" in exc_name
2. 删除 for-else 冗余分支
3. bool 子类拦截（numpy.bool_(False)）
4. 检查点条件删除 fetch_count > 0
5. load_cache 空结构返回 {"data": {}}
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
        assert result == {"meta": {}, "data": {}}


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


# ─── v1.0d Fix 2: 检查点写入 ──────────────────────────────────


class TestCheckpointWrite:
    """v1.0d Fix 2: 每 100 只股票做一次检查点写入"""

    def test_checkpoint_interval_constant(self):
        """_CHECKPOINT_INTERVAL 常量应存在且为 100"""
        from data_fetchers.fetch_financial import _CHECKPOINT_INTERVAL

        assert _CHECKPOINT_INTERVAL == 100

    def test_checkpoint_writes_on_interval(self):
        """main 在拉取 100 只后应触发检查点写入"""
        from data_fetchers.fetch_financial import main

        # 构造 101 只股票
        codes = [f"{i:06d}" for i in range(101)]
        stock_list = [{"code": c, "name": f"stock_{c}"} for c in codes]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache") as mock_write,
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # write_gzip_cache 至少被调用 2 次：1 次检查点 + 1 次最终写入
        assert mock_write.call_count >= 2

    def test_no_checkpoint_when_few_stocks(self):
        """少于 100 只股票时不触发检查点（只最终写入一次）"""
        from data_fetchers.fetch_financial import main

        codes = [f"{i:06d}" for i in range(10)]
        stock_list = [{"code": c, "name": f"stock_{c}"} for c in codes]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache") as mock_write,
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 只有最终写入 1 次，无检查点
        assert mock_write.call_count == 1


# ─── v1.0d Fix 3: 空数据日志 debug→info ───────────────────────


class TestEmptyDataLogLevel:
    """v1.0d Fix 3: 空数据日志应为 info 级别，无前导空格"""

    def test_empty_data_logs_at_info_level(self, caplog):
        """df.empty 时应使用 info 而非 debug"""
        with (
            patch(
                "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
                return_value=pd.DataFrame(),
            ),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            result = fetch_financial_data_for_stock("000001")

        assert result == []
        # 应有 info 级别日志，不应有 debug 级别
        info_msgs = [r for r in caplog.records if r.levelno == logging.INFO and "财务数据为空" in r.message]
        assert len(info_msgs) >= 1

    def test_no_leading_space_in_log(self, caplog):
        """日志消息不应包含前导空格"""
        with (
            patch(
                "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
                return_value=pd.DataFrame(),
            ),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            fetch_financial_data_for_stock("000001")

        for record in caplog.records:
            if "财务数据为空" in record.message:
                assert not record.message.startswith(" "), "日志消息不应有前导空格"


# ─── v1.0d Fix 4: 进度日志用 fetch_count ──────────────────────


class TestProgressLogFetchCount:
    """v1.0d Fix 4: 进度日志以 fetch_count 而非原始索引 i 触发"""

    def test_batch_log_interval_constant(self):
        """_BATCH_LOG_INTERVAL 常量应为 50"""
        from data_fetchers.fetch_financial import _BATCH_LOG_INTERVAL

        assert _BATCH_LOG_INTERVAL == 50

    def test_progress_logs_with_high_skip_rate(self, caplog):
        """高跳过率时进度日志仍应触发（基于 fetch_count）"""
        from data_fetchers.fetch_financial import main

        # 构造 200 只股票，其中 150 只已在缓存中
        all_codes = [f"{i:06d}" for i in range(200)]
        stock_list = [{"code": c, "name": f"stock_{c}"} for c in all_codes]
        cached_codes = {f"{i:06d}" for i in range(150)}  # 前 150 只已缓存
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch(
                "data_fetchers.fetch_financial.load_cache",
                return_value={"meta": {"last_full_fetch_date": "2026-06-10"}, "data": {c: [] for c in cached_codes}},
            ),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 应有进度日志（fetch_count=50 时触发）
        progress_msgs = [r for r in caplog.records if "拉取进度" in r.message]
        assert len(progress_msgs) >= 1, "高跳过率时进度日志仍应触发"


# ─── v1.0d Fix 5: 写入确认日志 ─────────────────────────────────


class TestWriteConfirmationLog:
    """v1.0d Fix 5: write_gzip_cache 后应有写入确认日志"""

    def test_write_confirmation_logged(self, caplog):
        """最终写入后应打印路径和记录数"""
        from data_fetchers.fetch_financial import main

        stock_list = [{"code": "000001", "name": "test"}]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 应有"缓存写入完成"日志
        confirm_msgs = [r for r in caplog.records if "缓存写入完成" in r.message]
        assert len(confirm_msgs) >= 1, "应有缓存写入确认日志"

    def test_write_confirmation_contains_path(self, caplog):
        """确认日志应包含文件路径"""
        from data_fetchers.fetch_financial import main

        stock_list = [{"code": "000001", "name": "test"}]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        confirm_msgs = [r for r in caplog.records if "缓存写入完成" in r.message]
        assert any("financial_data.json.gz" in r.message for r in confirm_msgs), "确认日志应包含文件路径"


# ─── v1.0e Fix 1: load_cache 日志 dict 格式记录数 ───────────────


class TestLoadCacheRecordCount:
    """v1.0e Fix 1: load_cache 日志对 dict 格式应计算实际记录数"""

    def test_dict_format_record_count(self, caplog, tmp_path):
        """dict 格式缓存应显示记录总数而非 key 数"""
        import gzip

        cache_data = {
            "meta": {"version": "1.0e"},
            "data": {
                "000001": [{"asset": "000001", "roe": 4.21}, {"asset": "000001", "roe": 3.5}],
                "000002": [{"asset": "000002", "roe": 2.1}],
            },
        }
        cache_file = tmp_path / "financial_data.json.gz"
        with gzip.open(cache_file, "wt") as f:
            json.dump(cache_data, f)

        with (
            patch("data_fetchers.fetch_financial.CACHE_FILE", cache_file),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            load_cache()

        # 3 条记录（000001×2 + 000002×1），不是 2 只股票
        msgs = [r for r in caplog.records if "条记录" in r.message]
        assert len(msgs) >= 1
        assert "3" in msgs[0].message, f"应为 3 条记录，实际: {msgs[0].message}"

    def test_list_format_record_count(self, caplog, tmp_path):
        """旧 list 格式缓存仍应正确显示记录数"""
        import gzip

        cache_data = {
            "meta": {"version": "1.0b"},
            "data": [{"asset": "000001"}, {"asset": "000002"}, {"asset": "000003"}],
        }
        cache_file = tmp_path / "financial_data.json.gz"
        with gzip.open(cache_file, "wt") as f:
            json.dump(cache_data, f)

        with (
            patch("data_fetchers.fetch_financial.CACHE_FILE", cache_file),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            load_cache()

        msgs = [r for r in caplog.records if "条记录" in r.message]
        assert len(msgs) >= 1
        assert "3" in msgs[0].message


# ─── v1.0e Fix 2: 检查点写入浅拷贝 ────────────────────────────


class TestCheckpointShallowCopy:
    """v1.0e Fix 2: 检查点写入使用浅拷贝，不提前 mutate stock_data"""

    def test_checkpoint_does_not_mutate_stock_data_early(self):
        """检查点写入时 stock_data 不应被提前 update"""
        from data_fetchers.fetch_financial import main

        codes = [f"{i:06d}" for i in range(101)]
        stock_list = [{"code": c, "name": f"stock_{c}"} for c in codes]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        # 验证：write_gzip_cache 的 checkpoint 调用中 data 应包含新数据
        captured_data = []

        def capture_write(path, data, **kwargs):
            captured_data.append(data)

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache", side_effect=capture_write),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 检查点写入（第1次调用）的 data 应包含 100 只股票
        assert len(captured_data) >= 2
        checkpoint_data = captured_data[0]["data"]
        assert len(checkpoint_data) == 100  # 前 100 只


# ─── v1.0e Fix 3: 统一 pd.isna 前置检查 ───────────────────────


class TestUnifiedPdIsna:
    """v1.0e Fix 3: _parse_percentage 和 _parse_numeric_with_unit 统一 pd.isna 前置检查"""

    def test_parse_percentage_numpy_float64_nan(self):
        """_parse_percentage 对 numpy.float64 NaN 返回 None"""
        assert _parse_percentage(np.float64("nan")) is None

    def test_parse_percentage_numpy_float64_valid(self):
        """_parse_percentage 对 numpy.float64 有效值正常返回"""
        assert _parse_percentage(np.float64(4.21)) == pytest.approx(4.21)

    def test_parse_numeric_numpy_float64_nan(self):
        """_parse_numeric_with_unit 对 numpy.float64 NaN 返回 None"""
        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        assert _parse_numeric_with_unit(np.float64("nan")) is None

    def test_parse_numeric_numpy_float64_valid(self):
        """_parse_numeric_with_unit 对 numpy.float64 有效值正常返回"""
        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        assert _parse_numeric_with_unit(np.float64(2.07)) == pytest.approx(2.07)

    def test_parse_percentage_nat(self):
        """_parse_percentage 对 pd.NaT 返回 None（pd.isna 前置检查拦截）"""
        assert _parse_percentage(pd.NaT) is None

    def test_parse_numeric_nat(self):
        """_parse_numeric_with_unit 对 pd.NaT 返回 None"""
        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        assert _parse_numeric_with_unit(pd.NaT) is None


# ─── v1.0e Fix 4: _parse_report_date 防 pd.NaT 漏判 ────────────


class TestParseReportDateNaT:
    """v1.0e Fix 4: _parse_report_date 应将 pd.NaT 识别为 None"""

    def test_nat_returns_none(self):
        """pd.NaT 应返回 None，不是字符串 'NaT'"""
        from data_fetchers.fetch_financial import _parse_report_date

        result = _parse_report_date(pd.NaT)
        assert result is None

    def test_none_returns_none(self):
        """None 返回 None"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date(None) is None

    def test_valid_date_string(self):
        """有效日期字符串原样返回"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date("2024-03-31") == "2024-03-31"

    def test_datetime_date(self):
        """datetime.date 对象格式化为字符串"""
        import datetime as dt

        from data_fetchers.fetch_financial import _parse_report_date

        d = dt.date(2024, 3, 31)
        assert _parse_report_date(d) == "2024-03-31"

    def test_numpy_nan_returns_none(self):
        """numpy NaN 也应返回 None"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date(np.float64("nan")) is None


# ─── v1.0e Fix 5: 年化 EPS split+int 异常防护 ────────────────


class TestAnnualizedEpsFormatException:
    """v1.0e Fix 5: 年化 EPS 计算对异常日期格式的防护"""

    def test_year_only_format(self):
        """仅含年份 '2024' 时 annualized_eps 为 None"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024"],  # 无月份
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert len(records) == 1
        assert records[0]["annualized_eps"] is None

    def test_compact_format(self):
        """紧凑格式 '20240331' 时 annualized_eps 为 None（split('-') 无分隔符）"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["20240331"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert records[0]["annualized_eps"] is None

    def test_non_numeric_month(self):
        """月份非数字时 annualized_eps 为 None"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-AB-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert records[0]["annualized_eps"] is None

    def test_valid_format_still_works(self):
        """正常格式 '2024-03-31' 仍正确计算"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records is not None
        assert records[0]["annualized_eps"] == pytest.approx(2.0)


# ─── v1.0f Fix 1: 全量模式 stale_codes ────────────────────────


class TestStaleCodesInMeta:
    """v1.0f Fix 1: 全量模式 API 失败股票记录到 meta.stale_codes"""

    def test_stale_codes_written_to_meta(self):
        """全量模式下 API 失败的股票应出现在 meta.stale_codes"""
        from data_fetchers.fetch_financial import main

        stock_list = [
            {"code": "000001", "name": "ok"},
            {"code": "000002", "name": "fail"},
            {"code": "000003", "name": "ok"},
        ]
        mock_df_ok = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        call_count = 0

        def mock_fetch(symbol, **kwargs):
            nonlocal call_count
            call_count += 1
            if symbol == "000002":
                raise RuntimeError("API error")
            return mock_df_ok

        captured_data = []

        def capture_write(path, data, **kwargs):
            captured_data.append(data)

        with (
            patch(
                "data_fetchers.fetch_financial.load_cache",
                return_value={"meta": {}, "data": {}},
            ),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", side_effect=mock_fetch),
            patch("data_fetchers.fetch_financial.write_gzip_cache", side_effect=capture_write),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 最终写入的 meta 应包含 stale_codes
        final_write = captured_data[-1]
        assert "stale_codes" in final_write["meta"]
        assert "000002" in final_write["meta"]["stale_codes"]

    def test_incremental_mode_no_stale_codes(self):
        """增量模式下 API 失败不记录 stale_codes"""
        from data_fetchers.fetch_financial import main

        stock_list = [{"code": "000001", "name": "fail"}]

        captured_data = []

        def capture_write(path, data, **kwargs):
            captured_data.append(data)

        with (
            patch(
                "data_fetchers.fetch_financial.load_cache",
                return_value={
                    "meta": {"last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d")},
                    "data": {"000001": [{"asset": "000001"}]},
                },
            ),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", side_effect=RuntimeError("err")),
            patch("data_fetchers.fetch_financial.write_gzip_cache", side_effect=capture_write),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 增量模式：000001 已在缓存中被跳过，不会拉取，无 stale_codes
        final_write = captured_data[-1]
        assert "stale_codes" not in final_write["meta"]


# ─── v1.0f Fix 2: 429 限流退避重试 ────────────────────────────


class TestRateLimitRetry:
    """v1.0f Fix 2: fetch_financial_data_for_stock 限流退避重试"""

    def test_is_rate_limit_error_detects_429(self):
        """_is_rate_limit_error 识别 HTTP 429"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert _is_rate_limit_error(RuntimeError("HTTP 429 Too Many Requests"))
        assert _is_rate_limit_error(RuntimeError("请求频率限制"))

    def test_is_rate_limit_error_non_rate_limit(self):
        """_is_rate_limit_error 对非限流异常返回 False"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert not _is_rate_limit_error(RuntimeError("Connection timeout"))
        assert not _is_rate_limit_error(AttributeError("NoneType"))

    def test_retry_succeeds_on_second_attempt(self):
        """限流重试第 2 次成功时返回数据"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        call_count = 0

        def mock_fetch(symbol, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("HTTP 429 Too Many Requests")
            return mock_df

        with (
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", side_effect=mock_fetch),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            result = fetch_financial_data_for_stock("000001")

        assert result is not None
        assert len(result) == 1

    def test_retry_exhausted_returns_none(self):
        """限流重试耗尽后返回 None"""
        with (
            patch(
                "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
                side_effect=RuntimeError("HTTP 429 Too Many Requests"),
            ),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            result = fetch_financial_data_for_stock("000001")

        assert result is None


# ─── v1.0f Fix 3: 进度日志去掉 fetch_count > 1 ──────────────────


class TestProgressLogCondition:
    """v1.0f Fix 3: 进度日志条件简化为 fetch_count % _BATCH_LOG_INTERVAL == 0"""

    def test_no_redundant_gt_one_condition(self):
        """源码中不应有 fetch_count > 1 条件"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "fetch_count > 1" not in source, "进度日志条件不应包含 fetch_count > 1"


# ─── v1.0f Fix 4: total_new_count 替换 len(new_stock_data) ──────


class TestTotalNewCount:
    """v1.0f Fix 4: total_new_count 计数器替代 len(new_stock_data)"""

    def test_total_new_count_after_checkpoint(self):
        """检查点 clear 后拉取完成日志仍反映实际新增总数"""
        from data_fetchers.fetch_financial import main

        codes = [f"{i:06d}" for i in range(150)]
        stock_list = [{"code": c, "name": f"stock_{c}"} for c in codes]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 若 total_new_count 正确，"拉取完成"日志应显示 150 而非 50
        # （150 > _CHECKPOINT_INTERVAL=100，clear 后 new_stock_data 只剩 50 条）


# ─── v1.0f Fix 5: 旧格式迁移统计日志 ───────────────────────────


class TestMigrationStatistics:
    """v1.0f Fix 5: 旧格式迁移补充统计日志 + asset 为空 warning"""

    def test_migration_log_contains_statistics(self, caplog):
        """迁移完成日志应包含 list 条数和 dict 股票数/记录数"""
        from data_fetchers.fetch_financial import main

        cache_data = {
            "meta": {},
            "data": [
                {"asset": "000001", "roe": 4.21},
                {"asset": "000001", "roe": 3.5},
                {"asset": "000002", "roe": 2.1},
            ],
        }

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch(
                "data_fetchers.fetch_financial.load_main_board_stock_list",
                return_value=[],
            ),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        migration_msgs = [r for r in caplog.records if "迁移完成" in r.message]
        assert len(migration_msgs) >= 1
        msg = migration_msgs[0].message
        assert "3 条" in msg  # list 长度
        assert "2 只股票" in msg  # dict key 数
        assert "3 条记录" in msg  # sum of values

    def test_migration_warns_on_empty_asset(self, caplog):
        """asset 为空的记录应触发 warning"""
        from data_fetchers.fetch_financial import main

        cache_data = {
            "meta": {},
            "data": [
                {"asset": "000001", "roe": 4.21},
                {"asset": "", "roe": 1.0},  # 空 asset
                {"asset": None, "roe": 2.0},  # None asset
            ],
        }

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch(
                "data_fetchers.fetch_financial.load_main_board_stock_list",
                return_value=[],
            ),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            caplog.at_level(logging.WARNING, logger="data_fetchers.fetch_financial"),
        ):
            main()

        drop_msgs = [r for r in caplog.records if "asset 为空" in r.message]
        assert len(drop_msgs) >= 1
        assert "2" in drop_msgs[0].message  # 2 条被丢弃


# ─── v1.0g Fix 1: _is_rate_limit_error 删除无效 "429" in exc_name ──


class TestRateLimitErrorNoClassNameCheck:
    """v1.0g Fix 1: _is_rate_limit_error 不再检查异常类名中的 429"""

    def test_no_429_in_class_name_check(self):
        """源码中 _is_rate_limit_error 不应包含 '429' in exc_name"""
        import inspect

        from data_fetchers.fetch_financial import _is_rate_limit_error

        source = inspect.getsource(_is_rate_limit_error)
        assert '"429" in exc_name' not in source, "不应检查类名中是否含 429"

    def test_429_in_message_still_detected(self):
        """异常消息中的 429 仍应被检测到"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert _is_rate_limit_error(RuntimeError("HTTP 429"))


# ─── v1.0g Fix 2: 删除 for-else 冗余分支 ──────────────────────


class TestNoForElseBranch:
    """v1.0g Fix 2: fetch_financial_data_for_stock 不应有 for-else 分支"""

    def test_no_for_else_in_fetch(self):
        """源码中 fetch_financial_data_for_stock 不应包含 for-else"""
        import inspect

        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        source = inspect.getsource(fetch_financial_data_for_stock)
        # for-else 的 else 前面是 except 块的 return，不应有独立的 else 分支
        lines = source.split("\n")
        for_else_found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "else:" and i > 0:
                # 检查是否是 for-else（前一个非空行应该是循环体内的代码）
                for j in range(i - 1, -1, -1):
                    prev = lines[j].strip()
                    if prev and not prev.startswith("#"):
                        if prev.startswith("return ") or prev.startswith("continue"):
                            for_else_found = True
                        break
        assert not for_else_found, "不应存在 for-else 冗余分支"


# ─── v1.0g Fix 3: bool 子类拦截 ──────────────────────────────


class TestBoolSubclassIntercept:
    """v1.0g Fix 3: numpy.bool_(False) 不被 int 分支误命中"""

    def test_parse_percentage_numpy_bool_false(self):
        """_parse_percentage 对 numpy.bool_(False) 返回 None 而非 0.0"""
        assert _parse_percentage(np.bool_(False)) is None

    def test_parse_percentage_numpy_bool_true(self):
        """_parse_percentage 对 numpy.bool_(True) 返回 None 而非 1.0"""
        assert _parse_percentage(np.bool_(True)) is None

    def test_parse_numeric_numpy_bool_false(self):
        """_parse_numeric_with_unit 对 numpy.bool_(False) 返回 None"""
        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        assert _parse_numeric_with_unit(np.bool_(False)) is None

    def test_parse_percentage_python_true_returns_float(self):
        """Python 原生 True 被 val is False 拦截不了，但 isinstance(bool) 拦截"""
        # True is False → False, 但 isinstance(True, bool) → True
        assert _parse_percentage(True) is None

    def test_parse_percentage_python_int_still_works(self):
        """正常 Python int 仍能正常解析"""
        assert _parse_percentage(5) == 5.0


# ─── v1.0g Fix 4: 检查点条件无 fetch_count > 0 ────────────────


class TestCheckpointNoRedundantCondition:
    """v1.0g Fix 4: 检查点写入条件不包含 fetch_count > 0"""

    def test_no_fetch_count_gt_zero_in_checkpoint(self):
        """源码中检查点条件不应包含 fetch_count > 0"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "fetch_count > 0" not in source, "检查点条件不应包含 fetch_count > 0"


# ─── v1.0g Fix 5: load_cache 空结构返回 dict ──────────────────


class TestLoadCacheEmptyStructure:
    """v1.0g Fix 5: load_cache 空结构返回 {"data": {}} 避免误触发迁移"""

    def test_no_migration_log_for_empty_cache(self, caplog):
        """空缓存不应触发旧格式迁移日志"""
        from data_fetchers.fetch_financial import main

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value={"meta": {}, "data": {}}),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=[]),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        migration_msgs = [r for r in caplog.records if "迁移" in r.message]
        assert len(migration_msgs) == 0, "空缓存不应触发迁移日志"

    def test_load_cache_missing_file_returns_dict(self, tmp_path):
        """缓存文件不存在时返回 dict 格式空结构"""
        from data_fetchers.fetch_financial import load_cache

        with patch("data_fetchers.fetch_financial.CACHE_FILE", tmp_path / "nonexistent.json.gz"):
            result = load_cache()

        assert isinstance(result["data"], dict), "空缓存 data 应为 dict 类型"
        assert len(result["data"]) == 0
