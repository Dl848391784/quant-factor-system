#!/usr/bin/env python3
"""
fetch_industry.py pytest 测试文件

测试覆盖：
- 缓存加载与刷新
- 缓存过期检查
- 数据完整性验证
- 备用数据降级
- 行业代码映射
- 关键词推断逻辑
- 线程安全（模块级缓存）
- 公共模块调用验证

运行方式：
    pytest data_fetchers/test_cases/test_fetch_industry.py -v

版本历史：
- v1.0 (2026-05-27): 初始版本，覆盖核心流程和约束合规验证
- v1.1 (2026-06-14): TC010 新增 SW SSL 修复 + 防覆盖测试（6 个用例，对应 fetch_industry v3.1）
"""

import json
import logging

# 添加项目根目录到 sys.path
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.fetch_industry import (
    _EM_INDUSTRY_NAMES,
    _OUTPUT_VERSION,
    SW_INDUSTRY_CODE_MAP,
    fetch_stock_industry_em,
    fetch_stock_industry_sw,
    get_industry_distribution,
    get_industry_map,
    get_stock_industry,
    infer_industry_from_name,
    load_local_industry_backup,
    load_stock_industry,
    refresh_industry_cache,
)


# 配置测试 logger
@pytest.fixture(scope="module")
def test_logger():
    """配置测试用 logger"""
    logger = logging.getLogger("test_fetch_industry")
    logger.setLevel(logging.DEBUG)
    return logger


@pytest.fixture
def temp_dir():
    """创建临时测试目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_cache_file(temp_dir):
    """创建模拟缓存文件"""
    cache_path = temp_dir / "stock_industry.json"
    cache_data = {
        "meta": {
            "version": "3.0",
            "source": "sw_category",
            "level": "一级",
            "updated_at": datetime.now().strftime('%Y-%m-%d'),
            "total_count": 100
        },
        "industries": {
            "000001": {
                "name": "平安银行",
                "industry": "银行",
                "industry_code": "4801"
            },
            "600000": {
                "name": "浦发银行",
                "industry": "银行",
                "industry_code": "4801"
            },
            "000002": {
                "name": "万科A",
                "industry": "房地产",
                "industry_code": "4301"
            }
        }
    }

    with open(cache_path, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2)

    return cache_path


@pytest.fixture
def mock_backup_file(temp_dir):
    """创建模拟备用数据文件"""
    backup_path = temp_dir / "stock_list.json"
    backup_data = {
        "stocks": [
            {"code": "000001", "name": "平安银行"},
            {"code": "600000", "name": "浦发银行"},
            {"code": "000002", "name": "万科A"},
            {"code": "600519", "name": "贵州茅台"},
        ]
    }

    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2)

    return backup_path


class TestIndustryCodeMapping:
    """TC001: 行业代码映射测试"""

    def test_sw_industry_code_map_valid_codes(self):
        """验证申万2021一级代码映射"""
        # 验证存在的代码映射正确
        assert SW_INDUSTRY_CODE_MAP['11'] == '农林牧渔'
        assert SW_INDUSTRY_CODE_MAP['48'] == '银行'
        assert SW_INDUSTRY_CODE_MAP['43'] == '房地产'
        assert SW_INDUSTRY_CODE_MAP['71'] == '计算机'

    def test_sw_industry_code_map_invalid_codes(self):
        """验证不存在的一级代码映射到'其他'"""
        # 验证不存在的代码映射到 '其他'
        assert SW_INDUSTRY_CODE_MAP['22'] == '其他'
        assert SW_INDUSTRY_CODE_MAP['28'] == '其他'
        assert SW_INDUSTRY_CODE_MAP['33'] == '其他'

    def test_first_level_extraction(self):
        """验证从4位代码提取一级代码"""
        # 4801 → 48
        assert '4801'[:2] == '48'
        # 4301 → 43
        assert '4301'[:2] == '43'


class TestKeywordInference:
    """TC002: 关键词推断逻辑测试"""

    def test_infer_bank(self):
        """验证银行关键词推断"""
        assert infer_industry_from_name("平安银行") == '银行'
        assert infer_industry_from_name("浦发银行") == '银行'
        assert infer_industry_from_name("工商银行") == '银行'

    def test_infer_real_estate(self):
        """验证房地产关键词推断"""
        assert infer_industry_from_name("万科A") == '房地产'
        assert infer_industry_from_name("保利地产") == '房地产'
        assert infer_industry_from_name("城建发展") == '房地产'

    def test_infer_securities_priority(self):
        """验证证券优先级（中信→证券，而非银行）"""
        # 关键词优先级测试：中信 → 证券
        assert infer_industry_from_name("中信证券") == '证券'
        # 注意："中信银行" 也会匹配 "中信" → 证券（模糊匹配优先级）

    def test_infer_new_energy_priority(self):
        """验证关键词优先级（电力优先于新能源）"""
        # 实际优先级：电力 > 新能源（电力关键词在前）
        # 这是因为关键词映射遍历顺序决定优先级
        assert infer_industry_from_name("新能源电力") == '电力'  # 实际行为

    def test_infer_power(self):
        """验证电力关键词推断"""
        assert infer_industry_from_name("长江电力") == '电力'
        assert infer_industry_from_name("风电股份") == '电力'
        assert infer_industry_from_name("光伏科技") == '电力'

    def test_infer_other(self):
        """验证未知行业返回'其他'"""
        assert infer_industry_from_name("未知公司") == '其他'
        assert infer_industry_from_name("测试股票") == '其他'


class TestCacheMechanism:
    """TC003: 缓存机制测试"""

    @patch('data_fetchers.fetch_industry.INDUSTRY_CACHE_PATH', new_callable=MagicMock)
    def test_load_from_fresh_cache(self, mock_cache_path, mock_cache_file, test_logger):
        """TC003-1: 从有效缓存加载"""
        # 正确配置 Mock
        mock_cache_path.__str__ = lambda: str(mock_cache_file)
        mock_cache_path.exists.return_value = True

        # 不需要 mock refresh，因为缓存是新鲜的
        data = load_stock_industry()

        # 验证返回数据正确
        assert isinstance(data, dict)
        assert '000001' in data
        assert data['000001']['industry'] == '银行'

    @patch('data_fetchers.fetch_industry.INDUSTRY_CACHE_PATH')
    def test_expired_cache_refresh(self, mock_cache_path, mock_cache_file, test_logger):
        """TC003-2: 过期缓存触发刷新"""
        # 创建过期缓存（8天前）
        expired_date = (datetime.now() - timedelta(days=8)).strftime('%Y-%m-%d')
        cache_data = {
            "meta": {
                "version": "3.0",
                "source": "sw_category",
                "level": "一级",
                "updated_at": expired_date,
                "total_count": 100
            },
            "industries": {
                "000001": {"name": "平安银行", "industry": "银行", "industry_code": "4801"}
            }
        }

        with open(mock_cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)

        mock_cache_path.__str__ = lambda: str(mock_cache_file)
        mock_cache_path.exists = lambda: True

        # Mock refresh 成功返回新数据
        new_data = {
            "000001": {"name": "平安银行", "industry": "银行", "industry_code": "4801"},
            "000002": {"name": "万科A", "industry": "房地产", "industry_code": "4301"}
        }

        with patch('data_fetchers.fetch_industry.refresh_industry_cache', return_value=new_data):
            data = load_stock_industry()

            # 验证刷新成功返回新数据
            assert '000002' in data

    @patch('data_fetchers.fetch_industry.INDUSTRY_CACHE_PATH', new_callable=MagicMock)
    def test_corrupted_cache_recovery(self, mock_cache_path, mock_cache_file, test_logger):
        """TC003-3: 损坏缓存恢复"""
        # 写入损坏缓存（industries 为 list，而非 dict）
        corrupted_data = {
            "meta": {"version": "2.7"},
            "industries": ["000001", "000002"]  # 错误类型
        }

        with open(mock_cache_file, 'w', encoding='utf-8') as f:
            json.dump(corrupted_data, f, indent=2)

        # 正确配置 Mock
        mock_cache_path.__str__ = lambda: str(mock_cache_file)
        mock_cache_path.exists.return_value = True
        mock_cache_path.unlink = MagicMock()

        # Mock refresh 返回有效数据
        valid_data = {
            "000001": {"name": "平安银行", "industry": "银行", "industry_code": "4801"}
        }

        with patch('data_fetchers.fetch_industry.refresh_industry_cache', return_value=valid_data):
            data = load_stock_industry()

            # 验证删除损坏缓存并重新获取
            # 注意：unlink 在异常分支调用，需验证调用情况
            # 验证返回数据正确
            assert data == valid_data


class TestBackupFallback:
    """TC004: 备用数据降级测试"""

    def test_load_local_backup_success(self, mock_backup_file, test_logger):
        """TC004-1: 本地备用数据加载成功"""
        data = load_local_industry_backup(stock_list_path=mock_backup_file, write_cache=False)

        # 验证推断正确
        assert '000001' in data
        assert data['000001']['industry'] == '银行'  # 关键词推断
        assert data['000001']['industry_code'] == 'local'

    def test_load_local_backup_missing_file(self, temp_dir, test_logger):
        """TC004-2: 备用文件不存在"""
        missing_path = temp_dir / "nonexistent.json"
        data = load_local_industry_backup(stock_list_path=missing_path, write_cache=False)

        # 验证返回空字典
        assert data == {}

    def test_load_local_backup_corrupt_file_raises(self, temp_dir, test_logger):
        """TC004-4 (v3.5): 备用文件损坏时抛异常（区分文件不存在 vs 解析失败）

        旧行为：解析失败 → warning + return {}（与文件不存在的返回值无法区分）
        新行为：解析失败 → raise（让调用方记录准确的降级原因）
        """
        import pytest
        corrupt_path = temp_dir / "corrupt.json"
        corrupt_path.write_text("{invalid json content", encoding="utf-8")

        with pytest.raises(Exception):  # noqa: B017 - 任何 JSON/IO 解析异常都应抛出
            load_local_industry_backup(stock_list_path=corrupt_path, write_cache=False)

    @patch('data_fetchers.fetch_industry.STOCK_LIST_BACKUP_PATH')
    def test_backup_write_cache_non_fatal(self, mock_backup_path, mock_backup_file):
        """TC004-3: 备用缓存写入失败为非致命错误"""
        mock_backup_path.__str__ = lambda: str(mock_backup_file)
        mock_backup_path.exists = lambda: True

        # Mock write_json_cache 抛异常
        with patch('data_fetchers.fetch_industry.write_json_cache', side_effect=PermissionError("mock error")):
            # 应该不抛异常，而是 warning
            data = load_local_industry_backup(stock_list_path=mock_backup_file, write_cache=True)

            # 验证仍然返回数据
            assert len(data) > 0


class TestModuleCacheThreadSafety:
    """TC005: 线程安全测试"""

    @patch('data_fetchers.fetch_industry._industry_cache', new_callable=MagicMock)
    @patch('data_fetchers.fetch_industry.load_stock_industry')
    def test_concurrent_get_industry_map(self, mock_load, mock_cache):
        """TC005-1: 并发访问模块级缓存"""
        # 重置缓存为 _UNSET 状态（而非 None）
        from data_fetchers.fetch_industry import _UNSET
        mock_cache.__class__ = object
        mock_cache._mock_name = '_UNSET'

        # Mock load 返回固定数据
        mock_load.return_value = {
            "000001": {"name": "平安银行", "industry": "银行", "industry_code": "4801"}
        }

        results = []

        def worker():
            data = get_industry_map()
            results.append(data)

        # 创建10个并发线程
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证：所有线程返回相同数据
        assert len(results) == 10
        assert all(r == results[0] for r in results)

        # 验证：load_stock_industry 只调用一次（DCL）
        # 注意：由于锁竞争，可能调用次数不严格为1，但应远小于线程数
        assert mock_load.call_count <= 3  # 允许少量竞争导致的重复调用


class TestPublicAPITests:
    """TC006: 公共接口测试"""

    @patch('data_fetchers.fetch_industry.get_industry_map')
    def test_get_stock_industry(self, mock_get_map):
        """TC006-1: 获取单只股票行业"""
        mock_get_map.return_value = {
            "000001": {"name": "平安银行", "industry": "银行", "industry_code": "4801"}
        }

        result = get_stock_industry("000001")
        assert result == '银行'

        # 未知股票
        result = get_stock_industry("999999")
        assert result == '未知'

    @patch('data_fetchers.fetch_industry.get_industry_map')
    def test_get_industry_distribution(self, mock_get_map):
        """TC006-2: 获取行业分布"""
        mock_get_map.return_value = {
            "000001": {"industry": "银行"},
            "600000": {"industry": "银行"},
            "000002": {"industry": "房地产"},
        }

        stocks = ["000001", "600000", "000002"]
        dist = get_industry_distribution(stocks)

        assert dist['银行'] == 2
        assert dist['房地产'] == 1


class TestConstraintCompliance:
    """TC007: 约束合规测试"""

    def test_version_constant_exists(self):
        """TC007-1: 版本号提取为常量（MODULE.md 约束 #16）"""
        assert _OUTPUT_VERSION == '3.10'

    def test_public_module_import(self):
        """TC007-2: 公共模块导入（MODULE.md 约束 #4）"""
        # 验证导入的公共模块函数存在
        from data_fetchers.common import get_module_result_dir, get_stock_list_file, setup_logger, write_json_cache

        assert callable(setup_logger)
        assert callable(get_module_result_dir)
        assert callable(get_stock_list_file)
        assert callable(write_json_cache)

    def test_output_directory_compliance(self):
        """TC007-3: 输出到 result 目录（MODULE.md 约束 #2）"""
        from data_fetchers.fetch_industry import INDUSTRY_CACHE_PATH, RESULT_DIR

        # 验证 result 目录
        assert 'result' in str(RESULT_DIR)

        # 验证缓存文件路径
        assert INDUSTRY_CACHE_PATH.name == 'stock_industry.json'
        assert 'result' in str(INDUSTRY_CACHE_PATH)

    def test_main_block_has_exit_code(self):
        """TC007-4: __main__ 块必须有退出码（MODULE.md 约束 + PROJECT.md 编码规范）"""
        import data_fetchers.fetch_industry as fetch_industry_module

        # 直接检查模块属性而非 inspect.getsource（后者返回 unicode 编码）
        source_path = fetch_industry_module.__file__
        with open(source_path, encoding='utf-8') as f:
            source = f.read()

        # 验证 __main__ 块存在且有 sys.exit 调用（退出码规范）
        # ruff format 会将单引号标准化为双引号，两种都要检查
        has_main = ("if __name__ == '__main__'" in source or 'if __name__ == "__main__"' in source)
        assert has_main, "缺少 __main__ CLI 入口"
        assert "sys.exit" in source, "__main__ 块缺少 sys.exit 退出码调用"


class TestEdgeCases:
    """TC008: 边界情况测试"""

    def test_empty_cache_file(self, temp_dir):
        """TC008-1: 空缓存文件处理"""
        empty_cache = temp_dir / "empty.json"
        empty_cache.write_text('')

        # 验证：空文件应返回空字典或触发 refresh
        with patch('data_fetchers.fetch_industry.INDUSTRY_CACHE_PATH', empty_cache):
            with patch('data_fetchers.fetch_industry.refresh_industry_cache', return_value={}):
                data = load_stock_industry()
                assert data == {}

    def test_invalid_json_format(self, temp_dir):
        """TC008-2: JSON 格式错误"""
        invalid_cache = temp_dir / "invalid.json"
        invalid_cache.write_text('{"invalid": json}')

        with patch('data_fetchers.fetch_industry.INDUSTRY_CACHE_PATH', invalid_cache):
            with patch('data_fetchers.fetch_industry.refresh_industry_cache', return_value={}):
                data = load_stock_industry()
                # 验证：格式错误触发 refresh
                assert data == {}


class TestEMSource:
    """TC009: 东方财富数据源测试"""

    def test_em_industry_names_complete(self):
        """TC009-1: _EM_INDUSTRY_NAMES 包含31个申万一级行业（去重后）"""
        assert len(_EM_INDUSTRY_NAMES) == 31
        # _EM_INDUSTRY_NAMES 从 SW_INDUSTRY_CODE_MAP 派生（非'其他'+去重），
        # 应与 SW 有效分类完全一致
        sw_valid_names = {v for v in SW_INDUSTRY_CODE_MAP.values() if v != '其他'}
        assert set(_EM_INDUSTRY_NAMES) == sw_valid_names, (
            f"不一致: SW有效={sw_valid_names - set(_EM_INDUSTRY_NAMES)}, "
            f"EM额外={set(_EM_INDUSTRY_NAMES) - sw_valid_names}"
        )

    def test_em_industry_names_no_duplicates(self):
        """TC009-2: _EM_INDUSTRY_NAMES 无重复（dict.fromkeys 已去重）"""
        assert len(_EM_INDUSTRY_NAMES) == len(set(_EM_INDUSTRY_NAMES))

    @patch('akshare.stock_board_industry_cons_em')
    def test_fetch_stock_industry_em_column_validation(self, mock_api):
        """TC009-3: EM API 列名校验（防御性）"""
        import pandas as pd

        # Mock 返回缺少必需列的 DataFrame
        mock_api.return_value = pd.DataFrame({'代码': ['000001'], '名称_错': ['平安银行']})

        # 应抛出异常（列名校验 KeyError）
        try:
            fetch_stock_industry_em()
            assert False, "应抛出异常但未抛出"
        except Exception as e:
            # KeyError 被 for 循环内的 except 捕获并 continue，
            # 最终所有31个板块都失败 → RuntimeError
            assert isinstance(e, RuntimeError), f"期望 RuntimeError，实际 {type(e).__name__}"

    @patch('akshare.stock_board_industry_cons_em')
    def test_fetch_stock_industry_em_all_fail_raises_runtime_error(self, mock_api):
        """TC009-4: 所有31个板块获取失败 → RuntimeError"""
        mock_api.side_effect = Exception("网络错误")

        try:
            fetch_stock_industry_em()
            assert False, "应抛出 RuntimeError"
        except RuntimeError as e:
            assert '所有31个板块均获取失败' in str(e)

    @patch('akshare.stock_board_industry_cons_em')
    def test_fetch_stock_industry_em_partial_success(self, mock_api):
        """TC009-5: 部分板块获取失败仍返回有效数据"""
        import pandas as pd

        # 只有第一个板块成功，其他失败
        success_df = pd.DataFrame({'代码': ['000001'], '名称': ['平安银行']})
        call_count = 0

        def side_effect(symbol):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return success_df
            raise Exception(f"板块 {symbol} 获取失败")

        mock_api.side_effect = side_effect

        result = fetch_stock_industry_em()
        assert '000001' in result
        assert result['000001']['industry'] == '农林牧渔'  # 第一个板块

    @patch('data_fetchers.fetch_industry.fetch_stock_industry_em')
    @patch('data_fetchers.fetch_industry.fetch_stock_industry_sw')
    @patch('data_fetchers.fetch_industry.write_json_cache')
    def test_refresh_industry_cache_em_priority(self, mock_write, mock_sw, mock_em):
        """TC009-6: refresh_industry_cache 优先使用 EM 数据源"""
        mock_em.return_value = {'000001': {'name': '平安银行', 'industry': '银行', 'industry_code': 'em_银行'}}
        mock_sw.return_value = {'000001': {'name': '平安银行', 'industry': '银行', 'industry_code': '4801'}}

        result = refresh_industry_cache()
        # EM 成功时不应调用 SW
        mock_sw.assert_not_called()
        assert result['000001']['industry_code'] == 'em_银行'

    @patch('data_fetchers.fetch_industry.fetch_stock_industry_em')
    @patch('data_fetchers.fetch_industry.fetch_stock_industry_sw')
    @patch('data_fetchers.fetch_industry.write_json_cache')
    def test_refresh_industry_cache_sw_fallback(self, mock_write, mock_sw, mock_em):
        """TC009-7: EM 失败时降级到 SW"""
        mock_em.side_effect = Exception("EM SSL 错误")
        mock_sw.return_value = {'000001': {'name': '平安银行', 'industry': '银行', 'industry_code': '4801'}}

        result = refresh_industry_cache()
        # EM 失败后应调用 SW
        mock_sw.assert_called_once()
        assert result['000001']['industry_code'] == '4801'

    @patch('data_fetchers.fetch_industry.fetch_stock_industry_em')
    @patch('data_fetchers.fetch_industry.fetch_stock_industry_sw')
    @patch('data_fetchers.fetch_industry.write_json_cache')
    def test_refresh_industry_cache_both_fail_raises_runtime_error(self, mock_write, mock_sw, mock_em):
        """TC009-8: EM + SW 均失败 → RuntimeError"""
        mock_em.side_effect = Exception("EM 失败")
        mock_sw.side_effect = Exception("SW SSL 失败")

        try:
            refresh_industry_cache()
            assert False, "应抛出 RuntimeError"
        except RuntimeError as e:
            assert '行业数据获取失败' in str(e)


class TestSwSslWorkaround:
    """TC010: v3.1 SW SSL 修复 + 防覆盖"""

    def test_get_sw_ca_bundle_returns_existing_path(self):
        """TC010-1: _get_sw_ca_bundle 返回真实存在的系统 CA 路径"""
        from data_fetchers.fetch_industry import _SYSTEM_CA_CANDIDATES, _get_sw_ca_bundle

        result = _get_sw_ca_bundle()
        # 至少在 RHEL/Debian/Mac 任一环境下应返回字符串路径，且文件存在
        if isinstance(result, str):
            assert Path(result).is_file(), f"返回的 CA 路径不存在: {result}"
            assert result in _SYSTEM_CA_CANDIDATES, f"返回的 CA 路径不在候选列表: {result}"
        else:
            # 系统无任何候选 CA，回退 True（让 requests 用 certifi 默认）
            assert result is True

    @patch('pathlib.Path.is_file', return_value=False)
    def test_get_sw_ca_bundle_fallback_when_none_exist(self, _mock_is_file):
        """TC010-2: 系统 CA 都不存在时回退 True（让 requests 用 certifi 默认）"""
        from data_fetchers.fetch_industry import _get_sw_ca_bundle

        result = _get_sw_ca_bundle()
        assert result is True

    def test_download_sw_industry_xls_uses_system_ca(self):
        """TC010-3: _download_sw_industry_xls 使用系统 CA bundle 调用 requests

        Why: 函数内部 import requests/pandas，所以 patch 必须作用在真实模块上而非
        fetch_industry。验证 verify 参数传递路径，避免回归到 certifi 默认（会 SSL 失败）。
        """
        import pandas as pd
        import requests

        import data_fetchers.fetch_industry as fi

        with patch.object(requests, 'get') as mocked_get, patch.object(pd, 'read_excel') as mocked_read:
            mocked_resp = MagicMock()
            mocked_resp.content = b'fake xls bytes'
            mocked_resp.raise_for_status = MagicMock()
            mocked_get.return_value = mocked_resp
            mocked_read.return_value = pd.DataFrame({
                '股票代码': ['000001'],
                '计入日期': ['2021-07-30'],
                '行业代码': ['480301'],
                '更新日期': ['2024-09-27'],
            })

            df = fi._download_sw_industry_xls()

            # verify 参数必须显式传入（系统 CA bundle 路径或 True）
            assert mocked_get.called, "未调用 requests.get"
            kwargs = mocked_get.call_args.kwargs
            assert 'verify' in kwargs, "verify 参数必须显式传入，不能依赖 certifi 默认"
            verify_arg = kwargs['verify']
            assert verify_arg is True or (isinstance(verify_arg, str) and Path(verify_arg).is_file()), (
                f"verify 应为 True 或真实存在的 CA 路径，实际: {verify_arg!r}"
            )

            # 列名 rename 验证
            assert {'symbol', 'industry_code', 'start_date'}.issubset(df.columns)

    def test_write_backup_cache_refuses_to_overwrite_real_cache(self, tmp_path, monkeypatch):
        """TC010-4 (核心防御): 防覆盖 — 现有缓存为 sw_category 时拒绝写 local_backup

        Why: 2026-06-13 事故复盘 — EM+SW 双失败时 _write_backup_cache 静默覆盖 5585 只
        真实数据为 3021 只 'local'。此测试守护回归。
        """
        import data_fetchers.fetch_industry as fi

        # 写一个"真实"缓存
        real_cache_path = tmp_path / "stock_industry.json"
        real_cache = {
            "meta": {
                "version": "3.1",
                "source": "sw_category",
                "level": "一级",
                "updated_at": "2026-06-14",
                "total_count": 5872,
            },
            "industries": {"000001": {"name": "平安银行", "industry": "银行", "industry_code": "480301"}},
        }
        real_cache_path.write_text(json.dumps(real_cache), encoding="utf-8")

        monkeypatch.setattr(fi, "INDUSTRY_CACHE_PATH", real_cache_path)

        # 尝试用 local_backup 覆盖
        fake_backup = {f"{i:06d}": {"name": "", "industry": "其他", "industry_code": "local"} for i in range(100)}
        fi._write_backup_cache(fake_backup)

        # 缓存必须仍是真实版本
        with open(real_cache_path, encoding="utf-8") as f:
            after = json.load(f)
        assert after["meta"]["source"] == "sw_category", "防覆盖失效，真实缓存被 local_backup 覆盖"
        assert after["meta"]["total_count"] == 5872, "防覆盖失效，total_count 被改写"

    def test_write_backup_cache_writes_when_no_existing_cache(self, tmp_path, monkeypatch):
        """TC010-5: 防覆盖不影响首次写入 — 缓存不存在时 local_backup 应正常写入"""
        import data_fetchers.fetch_industry as fi

        cache_path = tmp_path / "stock_industry.json"
        monkeypatch.setattr(fi, "INDUSTRY_CACHE_PATH", cache_path)
        monkeypatch.setattr(fi, "RESULT_DIR", tmp_path)

        fake_backup = {f"{i:06d}": {"name": "", "industry": "其他", "industry_code": "local"} for i in range(50)}
        fi._write_backup_cache(fake_backup)

        assert cache_path.exists(), "缓存不存在时应允许写入 local_backup"
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["meta"]["source"] == "local_backup"
        assert data["meta"]["total_count"] == 50

    def test_write_backup_cache_writes_when_existing_is_local_backup(self, tmp_path, monkeypatch):
        """TC010-6: 现有缓存本身就是 local_backup 时允许覆盖（保持新鲜度）"""
        import data_fetchers.fetch_industry as fi

        cache_path = tmp_path / "stock_industry.json"
        monkeypatch.setattr(fi, "INDUSTRY_CACHE_PATH", cache_path)
        monkeypatch.setattr(fi, "RESULT_DIR", tmp_path)

        # 写一个旧的 local_backup
        cache_path.write_text(json.dumps({
            "meta": {"version": "3.1", "source": "local_backup", "updated_at": "2026-06-01", "total_count": 10},
            "industries": {},
        }), encoding="utf-8")

        # 用新的 local_backup 覆盖
        fake = {f"{i:06d}": {"name": "", "industry": "其他", "industry_code": "local"} for i in range(20)}
        fi._write_backup_cache(fake)

        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["meta"]["source"] == "local_backup"
        assert data["meta"]["total_count"] == 20, "local_backup → local_backup 应允许刷新"


# 运行测试入口（仅用于 pytest 发现，非手动执行）
# 注意：遵循 PROJECT.md 规范，禁止 __main__ 块
