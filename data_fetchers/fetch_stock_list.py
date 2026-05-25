#!/usr/bin/env python3
"""
股票列表缓存模块

从新浪财经 API 获取主板股票列表，剔除创业板、科创板、北交所和ST股票，
生成缓存文件供后续因子分析使用。

主板股票定义：
- 沪市主板：60 开头
- 深市主板：00 开头

剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票

版本历史：
- v1.0 (2026-04-02): 初始版本
- v2.0 (2026-05-27): 公共模块规范化
  - 输出目录迁移：cache → result（遵循 MODULE.md 约束 2）
  - 日志规范化：复用 logger_config.py（遵循 PROJECT.md 第561-700行）
  - CLI 日志规范化：print → logger（遵循 PROJECT.md 第780-839行）
  - 类型注解补全 + __all__ 导出（遵循 MODULE.md 约束 53）
  - 版本号常量提取（遵循 MODULE.md 约束 16）
  - datetime.now() 统一调用（遵循 MODULE.md 约束 17）
  - Path 对象迁移 + 公共模块复用（遵循 MODULE.md 约束 62）

作者: 云舟
日期: 2026-04-02
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 公共模块导入
from data_fetchers.common.logger_config import setup_logger
from data_fetchers.common.http_client import create_sina_session
from data_fetchers.common.paths import (
    get_module_result_dir,
    get_module_logs_dir,
    get_cache_dir,
)

__all__ = [
    'refresh_stock_cache',
    'load_cache',
    'get_cached_stock_codes',
    'is_valid_main_board_stock',
    'determine_market',
]


# ============================================================
# 配置常量
# ============================================================

# 输出版本（遵循 MODULE.md 约束 16）
_OUTPUT_VERSION = '2.2'

# 新浪财经 API 端点
SINA_API_URL = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'

# API 请求配置
API_TIMEOUT = 30  # 超时时间（秒）
API_RETRIES = 3   # 重试次数
API_DELAY = 0.5   # 请求间隔（秒）

# 完整性验证阈值
MIN_TOTAL_STOCKS = 2500  # 最低股票数量
WARN_TOTAL_STOCKS = 2800  # 警告阈值
EXPECTED_SH_MIN = 1500   # 沪市主板最低预期
EXPECTED_SZ_MIN = 1200   # 深市主板最低预期


# ============================================================
# 日志配置（复用公共模块）
# ============================================================

# 获取脚本名（不含 .py）
_SCRIPT_NAME = Path(__file__).stem

# 日志文件路径（遵循 PROJECT.md 第621-668行规范）
_LOGS_DIR = get_module_logs_dir()

# 输出文件路径（遵循 MODULE.md 约束 2：输出到 result 目录）
_RESULT_DIR = get_module_result_dir()
RESULT_FILE = _RESULT_DIR / 'stock_list_meta.json'

# 缓存文件路径（股票列表数据仍保留在 cache 目录，供其他模块使用）
CACHE_FILE = get_cache_dir() / 'stock_list.json'


def _get_logger() -> logging.Logger:
    """
    获取日志记录器（复用公共模块）
    
    Returns:
        配置好的 Logger 对象
    """
    return setup_logger(_SCRIPT_NAME, logs_dir=_LOGS_DIR)


# 模块级 logger（仅在模块内部使用）
logger = _get_logger()


# ============================================================
# 股票筛选逻辑
# ============================================================

def is_valid_main_board_stock(code: str, name: str) -> bool:
    """
    判断是否为有效的主板股票
    
    Args:
        code: 股票代码（如 "600000"）
        name: 股票名称（如 "浦发银行"）
    
    Returns:
        True: 有效主板股票，应保留
        False: 应剔除
    
    Example:
        >>> is_valid_main_board_stock('600000', '浦发银行')
        True
        >>> is_valid_main_board_stock('300001', '特锐德')
        False  # 创业板
    """
    # 剔除规则 - 先判断剔除条件
    
    # 1. 创业板（30开头）
    if code.startswith('30'):
        return False
    
    # 2. 科创板（688开头）
    if code.startswith('688'):
        return False
    
    # 3. 北交所（8开头、4开头）
    if code.startswith('8') or code.startswith('4'):
        return False
    
    # 4. ST类股票（包含ST、*ST、SST、S*ST、S等）
    name_upper = name.upper()
    st_keywords = ['ST', '*ST', 'SST', 'S*ST']
    for keyword in st_keywords:
        if keyword in name_upper:
            return False
    
    # 特殊处理：名称以 S 开头但不是 SST 或 S*ST 的情况
    # 检查是否是单独的 S（停牌股票等）
    if name_upper.startswith('S') and not name_upper.startswith('ST'):
        # S开头的股票通常是特殊处理股票，剔除
        return False
    
    # 5. 退市股票
    if '退市' in name:
        return False
    
    # 保留规则 - 判断是否为主板
    
    # 沪市主板（60开头）
    if code.startswith('60'):
        return True
    
    # 深市主板（00开头，含003）
    if code.startswith('00'):
        return True
    
    # 其他情况剔除
    return False


def determine_market(code: str) -> str:
    """
    判断股票所属市场
    
    Args:
        code: 股票代码
    
    Returns:
        'sh': 沪市, 'sz': 深市, 'unknown': 未知
    
    Example:
        >>> determine_market('600000')
        'sh'
        >>> determine_market('000001')
        'sz'
    """
    if code.startswith('60'):
        return 'sh'
    elif code.startswith('00'):
        return 'sz'
    else:
        return 'unknown'


# ============================================================
# API 数据获取
# ============================================================

def fetch_stocks_from_sina(
    logger: Optional[logging.Logger] = None
) -> Tuple[List[Dict[str, Any]], int]:
    """
    从新浪财经 API 获取股票列表（分页获取所有数据）
    
    Args:
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        Tuple[List[Dict], int]: (股票信息列表, API请求页数)
        股票信息格式：[{'code': str, 'name': str, 'market': str}, ...]
    
    Raises:
        RuntimeError: API 获取失败
    
    Example:
        >>> stocks, pages = fetch_stocks_from_sina()
        >>> len(stocks)  # 约 3000 只主板股票
        3000+
    """
    if logger is None:
        logger = _get_logger()
    
    logger.info("从新浪财经 API 获取主板股票...")
    
    # 使用公共模块创建 Session
    session = create_sina_session(logger=logger)
    
    all_stocks: List[Dict[str, Any]] = []
    
    # 新浪API节点说明：
    # sh_a - 沪市A股
    # sz_a - 深市A股
    nodes = [
        {'node': 'sh_a', 'desc': '沪市A股'},
        {'node': 'sz_a', 'desc': '深市A股'},
    ]
    
    total_pages = 0
    page_size = 80  # 每页获取80条，这是需求文档建议的值
    
    for node_info in nodes:
        logger.info(f"  获取 {node_info['desc']}...")
        
        page = 1
        node_stocks_count = 0
        
        while True:
            # 新浪API参数（分页获取）
            params = {
                'page': page,
                'num': page_size,
                'node': node_info['node'],
                'sort': 'symbol',
                'asc': 1,
                '_s_r_a': 'page'
            }
            
            success = False
            data: Optional[List[Dict[str, Any]]] = None
            
            for attempt in range(API_RETRIES):
                try:
                    # 重试时添加延迟
                    if attempt > 0:
                        delay = API_DELAY * (attempt + 1) * 2
                        logger.info(f"    重试 {attempt}/{API_RETRIES}，等待 {delay:.1f}秒...")
                        time.sleep(delay)
                    
                    response = session.get(
                        SINA_API_URL,
                        params=params,
                        timeout=API_TIMEOUT
                    )
                    response.raise_for_status()
                    
                    # 解析 JSON 响应
                    data = response.json()
                    success = True
                    break
                    
                except requests.exceptions.Timeout:
                    logger.warning(f"    ! 请求超时 (第 {page} 页)")
                    if attempt < API_RETRIES - 1:
                        continue
                except requests.exceptions.RequestException as e:
                    logger.warning(f"    ! 请求失败: {e} (第 {page} 页)")
                    if attempt < API_RETRIES - 1:
                        continue
                except json.JSONDecodeError as e:
                    logger.warning(f"    ! JSON解析失败: {e} (第 {page} 页)")
                    if attempt < API_RETRIES - 1:
                        continue
            
            if not success:
                raise RuntimeError(f"获取 {node_info['desc']} 第 {page} 页数据失败，已重试 {API_RETRIES} 次")
            
            # 检查返回数据
            if not data or not isinstance(data, list) or len(data) == 0:
                # 返回空数据，表示已获取完毕
                logger.info(f"    第 {page} 页返回空数据，{node_info['desc']} 获取完成")
                break
            
            # 处理本页数据
            page_added = 0
            for item in data:
                code = item.get('code', '')
                name = item.get('name', '')
                
                # 筛选有效主板股票
                if is_valid_main_board_stock(code, name):
                    market = determine_market(code)
                    all_stocks.append({
                        'code': code,
                        'name': name,
                        'market': market
                    })
                    page_added += 1
            
            node_stocks_count += page_added
            total_pages += 1
            logger.info(f"    第 {page} 页: 获取 {len(data)} 条，新增主板 {page_added} 只")
            
            # 如果返回数据少于页面大小，说明已到最后一页
            if len(data) < page_size:
                logger.info(f"    最后一页，{node_info['desc']} 获取完成")
                break
            
            page += 1
            
            # 页间延迟，避免请求过快
            time.sleep(0.1)
        
        logger.info(f"    ✓ {node_info['desc']} 共获取 {node_stocks_count} 只主板股票")
        
        # 节点间延迟
        time.sleep(API_DELAY)
    
    # 去重
    seen: set = set()
    unique_stocks: List[Dict[str, Any]] = []
    for s in all_stocks:
        if s['code'] not in seen:
            seen.add(s['code'])
            unique_stocks.append(s)
    
    # 按代码排序
    unique_stocks.sort(key=lambda x: x['code'])
    
    if len(unique_stocks) == 0:
        raise RuntimeError("API获取失败，未获取到任何主板股票")
    
    logger.info(f"  ✓ 共获取 {len(unique_stocks)} 只主板股票（去重后）")
    
    return unique_stocks, total_pages


# ============================================================
# 数据完整性验证
# ============================================================

def validate_cache(cache_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证缓存数据完整性
    
    Args:
        cache_data: 缓存数据字典
    
    Returns:
        验证结果字典：
        {
            'passed': bool,
            'warnings': List[str],
            'errors': List[str],
            'stats': Dict[str, int]
        }
    
    Example:
        >>> result = validate_cache(cache_data)
        >>> result['passed']
        True
    """
    result: Dict[str, Any] = {
        'passed': True,
        'warnings': [],
        'errors': [],
        'stats': {}
    }
    
    stocks = cache_data.get('stocks', [])
    
    # 1. 数量检查
    total = len(stocks)
    result['stats']['total'] = total
    
    if total < WARN_TOTAL_STOCKS:
        result['warnings'].append(f"股票总数偏低: {total}，预期 {WARN_TOTAL_STOCKS}+")
    
    if total < MIN_TOTAL_STOCKS:
        result['errors'].append(f"股票总数异常: {total}，预期 {MIN_TOTAL_STOCKS}+")
        result['passed'] = False
    
    # 2. ST股票混入检查
    st_stocks = [s for s in stocks if 'ST' in s['name'].upper()]
    if st_stocks:
        result['errors'].append(f"发现ST股票混入: {[s['code'] for s in st_stocks[:5]]}")
        result['passed'] = False
    
    # 3. 创业板混入检查
    gem_stocks = [s for s in stocks if s['code'].startswith('30')]
    if gem_stocks:
        result['errors'].append(f"发现创业板股票混入: {[s['code'] for s in gem_stocks[:5]]}")
        result['passed'] = False
    
    # 4. 科创板混入检查
    star_stocks = [s for s in stocks if s['code'].startswith('688')]
    if star_stocks:
        result['errors'].append(f"发现科创板股票混入: {[s['code'] for s in star_stocks[:5]]}")
        result['passed'] = False
    
    # 5. 北交所混入检查
    bjb_stocks = [s for s in stocks if s['code'].startswith('8') or s['code'].startswith('4')]
    if bjb_stocks:
        result['errors'].append(f"发现北交所股票混入: {[s['code'] for s in bjb_stocks[:5]]}")
        result['passed'] = False
    
    # 6. 市场分布检查
    sh_count = len([s for s in stocks if s['market'] == 'sh'])
    sz_count = len([s for s in stocks if s['market'] == 'sz'])
    
    result['stats']['sh_count'] = sh_count
    result['stats']['sz_count'] = sz_count
    
    if sh_count < EXPECTED_SH_MIN:
        result['warnings'].append(f"沪市主板数量偏低: {sh_count}，预期 {EXPECTED_SH_MIN}+")
    
    if sz_count < EXPECTED_SZ_MIN:
        result['warnings'].append(f"深市主板数量偏低: {sz_count}，预期 {EXPECTED_SZ_MIN}+")
    
    # 7. 数据格式检查
    required_fields = ['code', 'name', 'market']
    for i, stock in enumerate(stocks[:10]):  # 抽查前10条
        for field in required_fields:
            if field not in stock:
                result['errors'].append(f"股票数据格式错误，缺少字段 '{field}'")
                result['passed'] = False
                break
    
    return result


# ============================================================
# 缓存文件操作
# ============================================================

def ensure_cache_dir() -> None:
    """确保缓存目录存在"""
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"确保缓存目录存在: {cache_dir}")


def ensure_result_dir() -> None:
    """确保结果目录存在"""
    _RESULT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"确保结果目录存在: {_RESULT_DIR}")


def save_cache(
    new_stocks: List[Dict[str, Any]],
    api_pages: int,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    增量更新股票列表到持久化文件
    
    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留
    
    Args:
        new_stocks: 从 API 获取的新股票列表
        api_pages: API 请求页数
        logger: 日志记录器（可选）
    
    Returns:
        缓存数据字典，包含统计信息
    
    Example:
        >>> cache_data = save_cache(stocks, api_pages)
        >>> cache_data['meta']['total_count']
        3000+
    """
    if logger is None:
        logger = _get_logger()
    
    ensure_cache_dir()
    ensure_result_dir()
    
    # 遵循 MODULE.md 约束 17：datetime.now() 只调用一次
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    timestamp = now.isoformat()
    
    # 加载现有数据
    existing_data = load_cache()
    existing_stocks = existing_data.get('stocks', []) if existing_data else []
    
    logger.info(f"  现有股票: {len(existing_stocks)} 只")
    logger.info(f"  API股票: {len(new_stocks)} 只")
    
    # 构建代码集合用于快速查找
    api_stock_codes = set(s['code'] for s in new_stocks)
    existing_stock_codes = set(s['code'] for s in existing_stocks)
    
    # 找出新增的股票（API有但文件没有）
    added_stocks: List[Dict[str, Any]] = []
    for stock in new_stocks:
        if stock['code'] not in existing_stock_codes:
            added_stocks.append({
                'code': stock['code'],
                'name': stock['name'],
                'market': stock['market'],
                'added_at': today
            })
    
    added_count = len(added_stocks)
    
    # 找出删除的股票（文件有但API没有 → 退市/ST）
    removed_codes = list(existing_stock_codes - api_stock_codes)
    removed_count = len(removed_codes)
    
    # 只保留API中存在的股票（删除退市/ST）
    all_stocks = [s for s in existing_stocks if s['code'] not in removed_codes]
    
    # 添加新增股票
    all_stocks.extend(added_stocks)
    
    # 按代码排序
    all_stocks.sort(key=lambda x: x['code'])
    
    # 统计
    sh_count = len([s for s in all_stocks if s['market'] == 'sh'])
    sz_count = len([s for s in all_stocks if s['market'] == 'sz'])
    
    # 构建缓存数据（股票列表保留在 cache 目录）
    cache_data: Dict[str, Any] = {
        'meta': {
            'last_updated': timestamp,
            'source': 'sina_api',
            'total_count': len(all_stocks),
            'sh_count': sh_count,
            'sz_count': sz_count,
            'added_count': added_count,
            'removed_count': removed_count,
            'removed_codes': removed_codes,
            'existing_count': len(existing_stocks),
            'api_pages': api_pages,
            'version': _OUTPUT_VERSION
        },
        'stocks': all_stocks,
        'codes': [s['code'] for s in all_stocks]
    }
    
    # 写入缓存文件（cache 目录）
    _write_json_file(CACHE_FILE, cache_data, logger)
    
    # 写入结果元信息文件（result 目录）
    result_data: Dict[str, Any] = {
        'meta': cache_data['meta'],
        'timestamp': timestamp,
        'script': _SCRIPT_NAME,
    }
    _write_json_file(RESULT_FILE, result_data, logger)
    
    logger.info(f"缓存文件已保存: {CACHE_FILE}")
    logger.info(f"结果元信息已保存: {RESULT_FILE}")
    
    return cache_data


def _write_json_file(
    path: Path,
    data: Dict[str, Any],
    logger: logging.Logger
) -> None:
    """
    原子写入 JSON 文件
    
    Args:
        path: 文件路径
        data: JSON 数据
        logger: 日志记录器
    
    Raises:
        OSError: 文件写入失败
    """
    temp_path = path.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        # 原子替换
        temp_path.replace(path)
    except OSError as e:
        # 失败时清理临时文件
        if temp_path.exists():
            temp_path.unlink()
        logger.error(f"写入文件失败: {path}, [{type(e).__name__}]: {e}")
        raise


def load_cache() -> Optional[Dict[str, Any]]:
    """
    加载缓存文件
    
    Returns:
        缓存数据字典，如果不存在则返回 None
    
    Example:
        >>> cache_data = load_cache()
        >>> if cache_data:
        ...     print(cache_data['meta']['total_count'])
    """
    if not CACHE_FILE.exists():
        return None
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"加载缓存失败: [{type(e).__name__}]: {e}")
        return None


def get_cached_stock_codes() -> List[str]:
    """
    获取缓存的股票代码列表
    
    Returns:
        股票代码列表，如果缓存不存在或无效则返回空列表
    
    Example:
        >>> codes = get_cached_stock_codes()
        >>> len(codes)  # 约 3000 只
        3000+
    """
    cache_data = load_cache()
    if cache_data and 'codes' in cache_data:
        return cache_data['codes']
    return []


# ============================================================
# 主函数
# ============================================================

def refresh_stock_cache(
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    增量更新股票列表持久化文件
    
    这是主入口函数，从新浪API获取主板股票列表，
    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留
    
    Args:
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        {
            "success": True/False,
            "total_count": int,
            "added_count": int,
            "removed_count": int,
            "removed_codes": List[str],
            "existing_count": int,
            "sh_count": int,
            "sz_count": int,
            "message": str,
            "cache_file": str,
            "result_file": str,
            "warnings": List[str]
        }
    
    Raises:
        RuntimeError: 缓存刷新失败
    
    Example:
        >>> result = refresh_stock_cache()
        >>> result['success']
        True
    """
    if logger is None:
        logger = _get_logger()
    
    logger.info("开始增量更新股票列表")
    start_time = time.time()
    
    result: Dict[str, Any] = {
        'success': False,
        'total_count': 0,
        'added_count': 0,
        'removed_count': 0,
        'removed_codes': [],
        'existing_count': 0,
        'sh_count': 0,
        'sz_count': 0,
        'message': '',
        'cache_file': str(CACHE_FILE),
        'result_file': str(RESULT_FILE),
        'warnings': []
    }
    
    try:
        # Step 1: 从 API 获取数据
        stocks, api_pages = fetch_stocks_from_sina(logger)
        
        # Step 2: 增量更新持久化文件
        cache_data = save_cache(stocks, api_pages, logger)
        
        # Step 3: 验证完整性
        validation = validate_cache(cache_data)
        
        if not validation['passed']:
            error_msg = "; ".join(validation['errors'])
            raise RuntimeError(f"数据验证失败: {error_msg}")
        
        # 收集警告
        if validation['warnings']:
            for warning in validation['warnings']:
                logger.warning(f"  ⚠️ {warning}")
            result['warnings'] = validation['warnings']
        
        # Step 4: 返回结果
        elapsed_time = time.time() - start_time
        
        added_count = cache_data['meta'].get('added_count', 0)
        removed_count = cache_data['meta'].get('removed_count', 0)
        removed_codes = cache_data['meta'].get('removed_codes', [])
        existing_count = cache_data['meta'].get('existing_count', 0)
        
        result['success'] = True
        result['total_count'] = validation['stats']['total']
        result['added_count'] = added_count
        result['removed_count'] = removed_count
        result['removed_codes'] = removed_codes
        result['existing_count'] = existing_count
        result['sh_count'] = validation['stats']['sh_count']
        result['sz_count'] = validation['stats']['sz_count']
        
        logger.info("验证通过，写入持久化文件")
        logger.info(f"增量更新完成，耗时 {elapsed_time:.1f} 秒")
        logger.info(f"  新增 {added_count} 只股票")
        if removed_count > 0:
            logger.info(f"  删除 {removed_count} 只股票（退市/ST）: {', '.join(removed_codes[:10])}{'...' if removed_count > 10 else ''}")
        logger.info(f"  总数: {result['total_count']}")
        logger.info(f"  沪市主板: {result['sh_count']}")
        logger.info(f"  深市主板: {result['sz_count']}")
        
        # 构建消息
        msg_parts = [f"新增 {added_count} 只"]
        if removed_count > 0:
            msg_parts.append(f"删除 {removed_count} 只（退市/ST）")
        msg_parts.append(f"共 {result['total_count']} 只（沪{result['sh_count']}+深{result['sz_count']}）")
        result['message'] = f"成功增量更新，{', '.join(msg_parts)}，耗时 {elapsed_time:.1f} 秒"
        
        return result
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        error_msg = f"增量更新股票列表失败: [{type(e).__name__}]: {e}"
        logger.error(error_msg)
        result['message'] = error_msg
        raise RuntimeError(error_msg) from e


# ============================================================
# CLI 入口
# ============================================================

if __name__ == '__main__':
    import sys
    import requests  # fetch_stocks_from_sina 需要
    
    # 使用公共模块 logger
    cli_logger = _get_logger()
    
    cli_logger.info("=" * 60)
    cli_logger.info("股票列表增量更新工具")
    cli_logger.info("=" * 60)
    
    try:
        result = refresh_stock_cache(cli_logger)
        
        cli_logger.info("=" * 60)
        cli_logger.info("更新结果")
        cli_logger.info("=" * 60)
        cli_logger.info(f"  状态: {'成功 ✓' if result['success'] else '失败 ✗'}")
        cli_logger.info(f"  新增: {result['added_count']} 只")
        if result['removed_count'] > 0:
            cli_logger.info(f"  删除: {result['removed_count']} 只（退市/ST）")
            removed_display = ', '.join(result['removed_codes'][:10])
            if result['removed_count'] > 10:
                removed_display += f"... 等共{result['removed_count']}只"
            cli_logger.info(f"    删除代码: {removed_display}")
        cli_logger.info(f"  现有: {result['existing_count']} 只")
        cli_logger.info(f"  总数: {result['total_count']}")
        cli_logger.info(f"  沪市主板: {result['sh_count']}")
        cli_logger.info(f"  深市主板: {result['sz_count']}")
        cli_logger.info(f"  缓存文件: {result['cache_file']}")
        cli_logger.info(f"  结果文件: {result['result_file']}")
        cli_logger.info(f"  消息: {result['message']}")
        
        if result['warnings']:
            cli_logger.warning("警告:")
            for warning in result['warnings']:
                cli_logger.warning(f"  ⚠️ {warning}")
        
        cli_logger.info("=" * 60)
        sys.exit(0)
        
    except Exception as e:
        cli_logger.error(f"错误: [{type(e).__name__}]: {e}")
        cli_logger.info("=" * 60)
        sys.exit(1)