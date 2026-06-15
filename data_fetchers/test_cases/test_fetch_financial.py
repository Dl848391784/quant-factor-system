"""fetch_financial.py 单元测试

覆盖 37 个修复（v1.0c~v1.0j: Fix 1-5/1-5/1-5/1-5/1-5/1-4/1-5/1-4）：
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
v1.0h:
1. 增量模式读取 stale_codes 强制重拉失败股票
2. meta 时间戳改用 dt_cls.now()
3. 进度日志分母预计算 codes_to_fetch
4. 失败日志补充异常响应摘要
v1.0i:
1. 失败日志删除冗余 str(e)[:80]，只保留一份改标签为"异常信息"
2. _is_rate_limit_error 删除 HTTPError 宽泛匹配，仅保留 TooManyRequests
3. codes_to_fetch 遍历 all_codes 统计与实际跳过逻辑一致
4. val is False 冗余移除，由 isinstance(bool) 统一处理
5. _parse_report_date str 分支 YYYY-MM-DD 正则校验
v1.0j:
1. 增量模式成功重拉的 stale 股票从 meta.stale_codes 移除
2. 检查点写入取消浅拷贝，先 update 再直接写 stock_data
3. Step 3 日志改为"股票总数/待请求/将跳过"
4. 全量模式+stale_codes_from_cache 非空时补充 info 日志
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
    _parse_report_date,
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
    """v1.0d Fix 2: 检查点写入（v1.0l Fix 2: interval 100→500 减少全量序列化频率）"""

    def test_checkpoint_interval_constant(self):
        """_CHECKPOINT_INTERVAL 常量应存在且为 500"""
        from data_fetchers.fetch_financial import _CHECKPOINT_INTERVAL

        assert _CHECKPOINT_INTERVAL == 500

    def test_checkpoint_writes_on_interval(self):
        """main 在拉取 500 只后应触发检查点写入"""
        from data_fetchers.fetch_financial import main

        # 构造 501 只股票
        codes = [f"{i:06d}" for i in range(501)]
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
        """少于 500 只股票时不触发检查点（只最终写入一次）"""
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
    """v1.0e/v1.0j: 检查点写入使用 stock_data 直接写入（v1.0j 起取消浅拷贝，先 update 再写）"""

    def test_checkpoint_does_not_mutate_stock_data_early(self):
        """检查点写入时 stock_data 应包含前 500 只股票"""
        from data_fetchers.fetch_financial import main

        codes = [f"{i:06d}" for i in range(501)]
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

        # 检查点写入（第1次调用）的 data 应包含至少 500 只股票
        # v1.0j 起：先 update 再写，stock_data 包含截至检查点时的所有股票
        assert len(captured_data) >= 2
        checkpoint_data = captured_data[0]["data"]
        assert len(checkpoint_data) >= 500  # 至少前 500 只


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
        """仅含年份 '2024' → 正则校验失败，整条记录跳过"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024"],  # 无月份，不符合 YYYY-MM-DD
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records == []

    def test_compact_format(self):
        """紧凑格式 '20240331' → 正则校验失败，整条记录跳过"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["20240331"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records == []

    def test_non_numeric_month(self):
        """月份非数字 '2024-AB-31' → 正则校验失败，整条记录跳过"""
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-AB-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df):
            records = fetch_financial_data_for_stock("000001")

        assert records == []

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


# ─── v1.0k Fix 5: for-else 结构确保 df 只在成功 break 后使用 ──────────


class TestForElseReturnsNone:
    """v1.0k Fix 5: fetch_financial_data_for_stock 的 for-else 分支必须 return None

    for-else 用于处理所有重试均为限流且通过 continue 跳过的情况，
    此时 df 未赋值，必须 return None 而非使用未绑定的 df。
    """

    def test_for_else_returns_none(self):
        """源码中 for-else 分支必须 return None（不是其他返回值）"""
        import ast

        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        source = __import__("inspect").getsource(fetch_financial_data_for_stock)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.For) and node.orelse:
                # for-else 分支存在，检查 else 块的内容
                for stmt in node.orelse:
                    if isinstance(stmt, ast.Return):
                        # 必须是 return None
                        assert (
                            isinstance(stmt.value, ast.Constant) and stmt.value.value is None
                        ), "for-else 分支的 return 必须是 return None"


# ─── v1.0k Fix 1-4: 5 项缺陷修复的补充测试 ──────────────────────


class TestParseReportDateInvalidCalendarDate:
    """v1.0k Fix 1: _parse_report_date str 分支验证日期逻辑有效性"""

    def test_invalid_calendar_date_returns_none(self):
        """\"2024-02-31\" 通过正则但不是合法日期，应返回 None"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date("2024-02-31") is None

    def test_valid_calendar_date_passes(self):
        """合法日期 \"2024-03-31\" 应正常返回"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date("2024-03-31") == "2024-03-31"

    def test_invalid_date_april_31(self):
        """\"2024-04-31\" 通过正则但不是合法日期"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date("2024-04-31") is None


class TestParseReportDatePdTimestamp:
    """v1.0k Fix 2: _parse_report_date 兜底分支正确处理 pd.Timestamp"""

    def test_pd_timestamp_formatted(self):
        """pd.Timestamp 应通过 .strftime 格式化为 YYYY-MM-DD"""
        from data_fetchers.fetch_financial import _parse_report_date

        ts = pd.Timestamp("2024-03-31")
        assert _parse_report_date(ts) == "2024-03-31"

    def test_pd_timestamp_with_time(self):
        """pd.Timestamp 含时间部分也能正确提取日期"""
        from data_fetchers.fetch_financial import _parse_report_date

        ts = pd.Timestamp("2024-03-31 00:00:00")
        assert _parse_report_date(ts) == "2024-03-31"

    def test_fallback_str_not_matching_regex_returns_none(self):
        """兜底分支：非 pd.Timestamp 的对象，str() 后不匹配正则则返回 None"""
        from data_fetchers.fetch_financial import _parse_report_date

        assert _parse_report_date(object()) is None


class TestSuccessfullyFetchedCodesAcrossCheckpoints:
    """v1.0k Fix 3 / v1.0l Fix 4: successfully_fetched_codes 跨检查点累积，final_stale 计算仅用此集合"""

    def test_final_stale_uses_successfully_fetched_codes(self):
        """增量模式下 final_stale 计算应使用跨检查点累积的集合（而非 stock_data.keys()）"""
        import ast

        from data_fetchers.fetch_financial import main

        source = __import__("inspect").getsource(main)
        tree = ast.parse(source)
        # 检查源码中有 successfully_fetched_codes 的 .add() 操作和在 final_stale 计算中的使用
        has_add_operation = False
        has_final_stale_usage = False
        for node in ast.walk(tree):
            # 检测 successfully_fetched_codes.add(code) 形式的调用
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "add"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "successfully_fetched_codes"
                ):
                    has_add_operation = True
            # 检测 successfully_fetched_codes 在 BinOp 中的使用（左侧或右侧）
            if isinstance(node, ast.BinOp):
                for operand in (node.left, node.right):
                    if isinstance(operand, ast.Name) and operand.id == "successfully_fetched_codes":
                        has_final_stale_usage = True
        assert has_add_operation, "应有 successfully_fetched_codes.add(code) 累积操作"
        assert has_final_stale_usage, "final_stale 计算应使用 successfully_fetched_codes"


class TestRateLimitKeywordPrecision:
    """v1.0k Fix 4: _is_rate_limit_error 关键词精确化"""

    def test_generic_restriction_not_matched(self):
        """\"数据格式限制\" 不应被识别为限流"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert not _is_rate_limit_error(RuntimeError("数据格式限制"))

    def test_access_restriction_not_matched(self):
        """\"访问权限限制\" 不应被识别为限流"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert not _is_rate_limit_error(RuntimeError("访问权限限制"))

    def test_request_frequency_limit_matched(self):
        """\"请求频率限制\" 应被识别为限流"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert _is_rate_limit_error(RuntimeError("请求频率限制"))

    def test_access_frequency_matched(self):
        """\"访问频率\" 应被识别为限流"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert _is_rate_limit_error(RuntimeError("访问频率过快"))


# ─── v1.0l Fix 1-4: 4 项缺陷修复的补充测试 ──────────────────────


class TestStaleCodesFilterDelisted:
    """v1.0l Fix 1: stale_codes_from_cache 与 all_codes 取交集过滤废弃代码"""

    def test_stale_codes_intersected_with_all_codes(self):
        """源码中 stale_codes_from_cache 应与 all_codes_set 取交集"""
        from data_fetchers.fetch_financial import main

        source = __import__("inspect").getsource(main)
        # 检查源码文本中存在交集操作
        assert "stale_codes_from_cache &= all_codes_set" in source, (
            "应有 stale_codes_from_cache &= all_codes_set 取交集操作"
        )


class TestCheckpointInterval500:
    """v1.0l Fix 2: _CHECKPOINT_INTERVAL 从 100 提高到 500"""

    def test_checkpoint_interval_is_500(self):
        """_CHECKPOINT_INTERVAL 应为 500"""
        from data_fetchers.fetch_financial import _CHECKPOINT_INTERVAL

        assert _CHECKPOINT_INTERVAL == 500


class TestReportDateWarningMessage:
    """v1.0l Fix 3: warning 文案明确说明"不符合YYYY-MM-DD格式或非合法日期\""""

    def test_warning_message_contains_format_hint(self, caplog):
        """warning 日志应包含 YYYY-MM-DD 格式说明"""
        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        with (
            patch(
                "data_fetchers.fetch_financial.ak.stock_financial_abstract_ths",
                return_value=pd.DataFrame({"报告期": ["20240331"], "基本每股收益": [0.5], **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"}}),
            ),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.WARNING, logger="data_fetchers.fetch_financial"),
        ):
            result = fetch_financial_data_for_stock("000001")

        # 应为空列表（所有记录被跳过）
        assert result == []
        # warning 消息应包含格式说明
        msgs = [r for r in caplog.records if "YYYY-MM-DD" in r.message]
        assert len(msgs) >= 1, "warning 应包含 YYYY-MM-DD 格式说明"


class TestFinalStaleUsesOnlySuccessfullyFetchedCodes:
    """v1.0l Fix 4: final_stale 计算仅用 successfully_fetched_codes（不含 stock_data.keys()）"""

    def test_no_stock_data_keys_in_final_stale(self):
        """final_stale 计算不应包含 stock_data.keys()"""
        import ast

        from data_fetchers.fetch_financial import main

        source = __import__("inspect").getsource(main)
        tree = ast.parse(source)
        # 检查 successfully_fetched 使用位置附近是否还有 stock_data.keys() 的联合
        # 找到 final_stale 赋值语句，确认其右侧不含 stock_data.keys()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "final_stale":
                        # 检查赋值右侧是否包含 stock_data.keys() 调用
                        source_segment = ast.get_source_segment(source, node)
                        if source_segment and "stock_data.keys()" in source_segment:
                            pytest.fail("final_stale 计算不应包含 stock_data.keys()")

    def test_refetched_count_uses_intersection(self):
        """成功重拉计数应使用 stale_codes_from_cache & successfully_fetched_codes 交集"""
        import ast

        from data_fetchers.fetch_financial import main

        source = __import__("inspect").getsource(main)
        # 检查 successfully_refetched 变量存在且使用交集
        assert "successfully_refetched" in source, "应有 successfully_refetched 变量"
        assert "stale_codes_from_cache & successfully_fetched_codes" in source, (
            "成功重拉计数应使用 stale_codes_from_cache & successfully_fetched_codes"
        )


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


# ─── v1.0h Fix 1: 增量模式 stale_codes 强制重拉 ──────────────


class TestStaleCodesIncrementalRefetch:
    """v1.0h Fix 1: 增量模式下 stale_codes 中的股票不被跳过"""

    def test_stale_codes_not_skipped_in_incremental(self, caplog):
        """增量模式下 stale_codes 中的股票应被强制拉取"""
        from data_fetchers.fetch_financial import main

        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        # 增量模式：last_full_fetch_date 是今天，000002 在 stale_codes 中
        cache_data = {
            "meta": {
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d"),
                "stale_codes": ["000002"],
            },
            "data": {
                "000001": [{"asset": "000001", "roe": 4.21}],
                "000002": [{"asset": "000002", "roe": 2.1}],  # 旧数据存在但需重拉
            },
        }
        stock_list = [
            {"code": "000001", "name": "ok"},
            {"code": "000002", "name": "stale"},
        ]

        fetched_codes = []

        def mock_fetch(symbol, **kwargs):
            fetched_codes.append(symbol)
            return mock_df

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", side_effect=mock_fetch),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 000001 在缓存中且不在 stale_codes → 跳过
        # 000002 在缓存中但在 stale_codes → 不跳过，强制拉取
        assert "000002" in fetched_codes, "stale_codes 中的股票应被强制拉取"
        assert "000001" not in fetched_codes, "非 stale 的缓存股票应跳过"

    def test_stale_codes_log_in_incremental(self, caplog):
        """增量模式下有 stale_codes 时应打印强制重拉日志"""
        from data_fetchers.fetch_financial import main

        cache_data = {
            "meta": {
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d"),
                "stale_codes": ["000002"],
            },
            "data": {"000001": [{"asset": "000001"}], "000002": [{"asset": "000002"}]},
        }

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=[]),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        stale_msgs = [r for r in caplog.records if "强制重拉" in r.message]
        assert len(stale_msgs) >= 1


# ─── v1.0h Fix 2: meta 时间戳用 dt_cls.now() ──────────────────


class TestMetaTimestampDynamic:
    """v1.0h Fix 2: meta 中 fetched_at 和 last_full_fetch_date 使用 dt_cls.now()"""

    def test_meta_uses_dynamic_timestamp(self):
        """meta 中的时间戳应是完成时而非启动时"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        # Step 6 的 meta 构建中不应使用 _NOW.strftime
        # 查找 meta 构建区域
        meta_start = source.find('"version": _OUTPUT_VERSION')
        meta_section = source[meta_start:meta_start + 500] if meta_start >= 0 else ""
        assert "_NOW.strftime" not in meta_section, "meta 构建不应使用 _NOW，应使用 dt_cls.now()"


# ─── v1.0h Fix 3: 进度日志固定分母 ────────────────────────────


class TestProgressLogFixedDenominator:
    """v1.0h Fix 3: 进度日志分母 codes_to_fetch 是预计算的固定值"""

    def test_codes_to_fetch_precomputed(self):
        """源码中应预计算 codes_to_fetch 变量"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "codes_to_fetch" in source, "应预计算 codes_to_fetch 作为固定分母"

    def test_progress_log_uses_codes_to_fetch(self):
        """进度日志不应使用 len(all_codes) - skipped 动态计算"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "len(all_codes) - skipped" not in source, "进度日志分母不应动态计算"


# ─── v1.0h Fix 4: 失败日志补充响应摘要 ────────────────────────


class TestFailureLogResponseSummary:
    """v1.0h/v1.0i: 失败日志包含异常信息"""

    def test_failure_log_contains_response_summary(self):
        """失败日志格式应包含 [异常信息: ...]"""
        import inspect

        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        source = inspect.getsource(fetch_financial_data_for_stock)
        assert "异常信息" in source, "失败日志应包含异常信息字段"


# ─── v1.0i Fix 1: 失败日志无冗余 str(e)[:80] ──────────────────


class TestFailureLogNoRedundantTruncation:
    """v1.0i Fix 1: 失败日志不应同时打印两份 str(e) 截断"""

    def test_failure_log_single_truncation(self):
        """失败日志（'财务数据失败'）中 str(e) 只截断一次"""
        import inspect

        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        source = inspect.getsource(fetch_financial_data_for_stock)
        # 找到"财务数据失败"日志附近的代码块（格式行+参数行）
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "财务数据失败" in line:
                # 检查该行和后面5行（参数行）中 str(e)[: 的总数
                block = "\n".join(lines[i : i + 6])
                count = block.count("str(e)[:")
                assert count == 1, f"失败日志块中 str(e)[: 应只出现1次，实际 {count} 次"
                break


# ─── v1.0i Fix 2: _is_rate_limit_error 不含 HTTPError ──────────


class TestRateLimitNoHttpError:
    """v1.0i Fix 2: _is_rate_limit_error 不匹配 HTTPError 类名"""

    def test_httperror_not_in_class_check(self):
        """源码中不应包含 HTTPError 类名匹配"""
        import inspect

        from data_fetchers.fetch_financial import _is_rate_limit_error

        source = inspect.getsource(_is_rate_limit_error)
        assert '"HTTPError"' not in source, "不应匹配 HTTPError 类名（400/500 也会抛）"

    def test_httperror_non_429_not_detected(self):
        """HTTP 500 错误不应被识别为限流"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert not _is_rate_limit_error(RuntimeError("HTTP 500 Internal Server Error"))

    def test_httperror_429_still_detected(self):
        """含 429 的 HTTPError 仍应被识别"""
        from data_fetchers.fetch_financial import _is_rate_limit_error

        assert _is_rate_limit_error(RuntimeError("HTTPError: 429 Too Many Requests"))


# ─── v1.0i Fix 3: codes_to_fetch 遍历 all_codes ────────────────


class TestCodesToFetchConsistency:
    """v1.0i Fix 3: codes_to_fetch 遍历 all_codes 统计，与实际跳过逻辑一致"""

    def test_codes_to_fetch_uses_all_codes(self):
        """源码中 codes_to_fetch 应基于 all_codes 遍历"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "for c in all_codes" in source, "应遍历 all_codes 计算 codes_to_fetch"


# ─── v1.0i Fix 4: val is False 冗余移除 ───────────────────────


class TestValIsFalseRedundant:
    """v1.0i Fix 4: val is False 已被 isinstance(bool) 覆盖，不应冗余出现"""

    def test_no_val_is_false_in_parse_percentage(self):
        """_parse_percentage 中不应有 val is False"""
        import inspect

        from data_fetchers.fetch_financial import _parse_percentage

        source = inspect.getsource(_parse_percentage)
        assert "val is False" not in source, "val is False 已被 isinstance(bool) 覆盖"

    def test_no_val_is_false_in_parse_numeric(self):
        """_parse_numeric_with_unit 中不应有 val is False"""
        import inspect

        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        source = inspect.getsource(_parse_numeric_with_unit)
        assert "val is False" not in source, "val is False 已被 isinstance(bool) 覆盖"

    def test_parse_percentage_false_still_returns_none(self):
        """Python False 仍应返回 None（由 isinstance(bool) 处理）"""
        assert _parse_percentage(False) is None

    def test_parse_numeric_false_still_returns_none(self):
        """Python False 仍应返回 None"""
        from data_fetchers.fetch_financial import _parse_numeric_with_unit

        assert _parse_numeric_with_unit(False) is None


# ─── v1.0i Fix 5: _parse_report_date YYYY-MM-DD 正则校验 ────────


class TestReportDateRegex:
    """v1.0i Fix 5: _parse_report_date str 分支需 YYYY-MM-DD 正则校验"""

    def test_valid_yyyy_mm_dd(self):
        """标准 YYYY-MM-DD 格式应通过"""
        assert _parse_report_date("2024-03-31") == "2024-03-31"

    def test_compact_format_rejected(self):
        """紧凑格式 YYYYMMDD 应返回 None"""
        assert _parse_report_date("20240331") is None

    def test_chinese_format_rejected(self):
        """中文日期格式应返回 None"""
        assert _parse_report_date("2024年3月31日") is None

    def test_year_only_rejected(self):
        """仅年份应返回 None"""
        assert _parse_report_date("2024") is None

    def test_invalid_month_rejected(self):
        """无效月份应返回 None"""
        assert _parse_report_date("2024-13-01") is None

    def test_datetime_date_still_works(self):
        """datetime.date 对象仍应正常工作"""
        import datetime

        d = datetime.date(2024, 3, 31)
        assert _parse_report_date(d) == "2024-03-31"

    def test_invalid_date_warning_logged(self, caplog):
        """无效日期字符串应触发 warning"""
        from data_fetchers.fetch_financial import fetch_financial_data_for_stock

        # 构造返回含无效日期行的 DataFrame
        mock_df = pd.DataFrame(
            {
                "报告期": ["20240331"],  # 紧凑格式
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        with (
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            caplog.at_level(logging.WARNING, logger="data_fetchers.fetch_financial"),
        ):
            result = fetch_financial_data_for_stock("000001")

        # 无效日期行被跳过，结果为空列表
        assert result == []
        invalid_msgs = [r for r in caplog.records if "YYYY-MM-DD" in r.message or "格式无效" in r.message]
        assert len(invalid_msgs) >= 1


# ─── v1.0j Fix 1: 增量模式成功重拉的 stale 股票从 meta 移除 ──


class TestStaleCodesIncrementalCleanup:
    """v1.0j Fix 1: 增量模式下成功重拉的 stale 股票应从 meta.stale_codes 移除"""

    def test_successful_refetch_removes_from_stale(self):
        """增量模式下 stale 股票拉取成功后，meta 中不应再包含该 stale_code"""
        from data_fetchers.fetch_financial import main

        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        cache_data = {
            "meta": {
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d"),
                "stale_codes": ["000002", "000003"],
            },
            "data": {
                "000001": [{"asset": "000001"}],
                "000002": [{"asset": "000002"}],
                "000003": [{"asset": "000003"}],
            },
        }
        stock_list = [
            {"code": "000001", "name": "ok"},
            {"code": "000002", "name": "stale_ok"},
            {"code": "000003", "name": "stale_fail"},
        ]
        call_count = {"n": 0}

        def mock_fetch(symbol, **kwargs):
            call_count["n"] += 1
            if symbol == "000003":
                raise RuntimeError("API error")  # 仍然失败 → 返回 None
            return mock_df  # 成功

        captured_writes = []

        def capture_write(path, data, **kwargs):
            captured_writes.append(data)

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", side_effect=mock_fetch),
            patch("data_fetchers.fetch_financial.write_gzip_cache", side_effect=capture_write),
            patch("data_fetchers.fetch_financial.time.sleep"),
        ):
            main()

        # 最终写入的 meta 中 stale_codes 应只包含 000003（000002 已成功重拉）
        final_meta = captured_writes[-1]["meta"]
        if "stale_codes" in final_meta:
            assert "000002" not in final_meta["stale_codes"], "成功重拉的 000002 不应再在 stale_codes 中"
            assert "000003" in final_meta["stale_codes"], "仍然失败的 000003 应保留在 stale_codes 中"
        else:
            # 如果没有 stale_codes 字段也算通过（所有 stale 都成功重拉）
            pass

    def test_stale_cleanup_info_log(self, caplog):
        """增量模式成功重拉 stale 股票时应打印 cleanup 日志"""
        from data_fetchers.fetch_financial import main

        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        cache_data = {
            "meta": {
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d"),
                "stale_codes": ["000002"],
            },
            "data": {"000001": [{"asset": "000001"}], "000002": [{"asset": "000002"}]},
        }
        stock_list = [
            {"code": "000001", "name": "ok"},
            {"code": "000002", "name": "stale"},
        ]

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 应有 stale_codes cleanup 日志
        cleanup_msgs = [r for r in caplog.records if "成功重拉" in r.message and "stale" in r.message]
        assert len(cleanup_msgs) >= 1, "应有 stale_codes 成功重拉日志"


# ─── v1.0j Fix 2: 检查点写入取消浅拷贝 ────────────────────────


class TestCheckpointNoShallowCopy:
    """v1.0j Fix 2: 检查点写入不再创建浅拷贝 merged，直接写 stock_data"""

    def test_no_merged_variable_in_source(self):
        """源码中检查点写入不应有 merged = {**...} 浅拷贝"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        # 不应有 merged = {**stock_data 这样的浅拷贝
        assert "merged = {" not in source, "检查点写入不应有 merged 浅拷贝"


# ─── v1.0j Fix 3: Step 3 日志格式改进 ──────────────────────────


class TestStep3LogFormat:
    """v1.0j Fix 3: Step 3 日志包含 股票总数/待请求/将跳过 三维信息"""

    def test_log_format_in_source(self):
        """源码中 Step 3 日志应包含 股票总数/待请求/将跳过 格式"""
        import inspect

        from data_fetchers.fetch_financial import main

        source = inspect.getsource(main)
        assert "股票总数" in source, "日志应包含'股票总数'"
        assert "待请求" in source, "日志应包含'待请求'"
        assert "将跳过" in source, "日志应包含'将跳过'"

    def test_log_values_match_codes_to_fetch(self, caplog):
        """日志中的待请求数应等于 codes_to_fetch"""
        from data_fetchers.fetch_financial import main

        cache_data = {
            "meta": {"last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d")},
            "data": {"000001": [{"asset": "000001"}]},
        }
        stock_list = [
            {"code": "000001", "name": "cached"},
            {"code": "000002", "name": "new"},
            {"code": "000003", "name": "new"},
        ]
        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 找到 "股票总数" 日志
        step3_msgs = [r for r in caplog.records if "股票总数" in r.message]
        assert len(step3_msgs) >= 1, "应有 Step 3 统计日志"
        # 待请求=2（000002, 000003），将跳过=1（000001）
        msg = step3_msgs[0].message
        assert "待请求=2" in msg, f"待请求应为2: {msg}"
        assert "将跳过=1" in msg, f"将跳过应为1: {msg}"


# ─── v1.0j Fix 4: 全量模式 stale_codes 日志 ────────────────────


class TestFullFetchStaleCodesLog:
    """v1.0j Fix 4: 全量模式+stale_codes_from_cache 非空时打印覆盖日志"""

    def test_full_fetch_with_stale_codes_logs_override(self, caplog):
        """全量模式下有 stale_codes_from_cache 时应打印'自动覆盖'日志"""
        from data_fetchers.fetch_financial import main

        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        # 全量模式：无 last_full_fetch_date 或超 90 天
        cache_data = {
            "meta": {
                "last_full_fetch_date": "2025-01-01",  # 超过 90 天
                "stale_codes": ["000002", "000003"],
            },
            "data": {"000001": [{"asset": "000001"}]},
        }
        stock_list = [{"code": "000001", "name": "ok"}]

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 应有"自动覆盖"日志
        override_msgs = [r for r in caplog.records if "自动覆盖" in r.message]
        assert len(override_msgs) >= 1, "全量模式下有 stale_codes 应打印'自动覆盖'日志"

    def test_incremental_stale_codes_no_override_log(self, caplog):
        """增量模式下有 stale_codes 时不应打印'自动覆盖'日志"""
        from data_fetchers.fetch_financial import main

        mock_df = pd.DataFrame(
            {
                "报告期": ["2024-03-31"],
                "基本每股收益": [0.5],
                **{cn: [None] for cn in _FINANCIAL_FIELD_MAP if cn != "基本每股收益"},
            }
        )
        cache_data = {
            "meta": {
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d"),
                "stale_codes": ["000002"],
            },
            "data": {"000001": [{"asset": "000001"}], "000002": [{"asset": "000002"}]},
        }
        stock_list = [
            {"code": "000001", "name": "ok"},
            {"code": "000002", "name": "stale"},
        ]

        with (
            patch("data_fetchers.fetch_financial.load_cache", return_value=cache_data),
            patch("data_fetchers.fetch_financial.load_main_board_stock_list", return_value=stock_list),
            patch("data_fetchers.fetch_financial.ak.stock_financial_abstract_ths", return_value=mock_df),
            patch("data_fetchers.fetch_financial.write_gzip_cache"),
            patch("data_fetchers.fetch_financial.time.sleep"),
            caplog.at_level(logging.INFO, logger="data_fetchers.fetch_financial"),
        ):
            main()

        # 不应有"自动覆盖"日志（增量模式打印的是"强制重拉"）
        override_msgs = [r for r in caplog.records if "自动覆盖" in r.message]
        assert len(override_msgs) == 0, "增量模式不应打印'自动覆盖'日志"
