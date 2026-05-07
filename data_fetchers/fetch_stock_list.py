#!/usr/bin/env python3
"""
股票列表缓存模块

从新浪财经 API 获取主板股票列表，剔除创业板、科创板、北交所和ST股票，
生成缓存文件供后续因子分析使用。

主板股票定义：
- 沪市主板：60 开头
- 深市主板：00 开头

剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票

作者: 云舟
日期: 2026-04-02
"""

import os
import json
import time
import logging
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ============================================================
# 配置常量
# ============================================================

# 缓存文件路径 - 使用项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
CACHE_DIR = os.path.join(_PROJECT_ROOT, 'cache')
CACHE_FILE = os.path.join(CACHE_DIR, 'stock_list.json')

# 日志文件路径
LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'stock_cache.log')

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
# 日志配置
# ============================================================

def setup_logger() -> logging.Logger:
    """配置日志记录器"""
    # 确保日志目录存在
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)
    
    logger = logging.getLogger('stock_cache')
    logger.setLevel(logging.INFO)
    
    # 避免重复添加 handler
    if not logger.handlers:
        # 文件 handler
        file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter('[%(asctime)s] %(levelname)s  %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # 控制台 handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    return logger


logger = setup_logger()


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

def fetch_stocks_from_sina() -> List[Dict]:
    """
    从新浪财经 API 获取股票列表（分页获取所有数据）
    
    Returns:
        股票信息列表 [{'code': str, 'name': str}, ...]
    
    Raises:
        RuntimeError: API 获取失败
    """
    logger.info("从新浪财经 API 获取主板股票...")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': 'http://finance.sina.com.cn/',
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    all_stocks = []
    
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
            data = None
            
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
    seen = set()
    unique_stocks = []
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

def validate_cache(cache_data: Dict) -> Dict:
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
            'stats': Dict
        }
    """
    result = {
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

def ensure_cache_dir():
    """确保缓存目录存在"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR, exist_ok=True)
        logger.info(f"创建缓存目录: {CACHE_DIR}")


def save_cache(new_stocks: List[Dict], api_pages: int) -> Dict:
    """
    增量更新股票列表到持久化文件
    
    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留
    
    Args:
        new_stocks: 从 API 获取的新股票列表
        api_pages: API 请求页数
    
    Returns:
        缓存数据字典，包含 'added_count'、'removed_count'、'removed_codes' 字段
    """
    ensure_cache_dir()
    
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    # 加载现有数据
    existing_data = load_cache()
    existing_stocks = existing_data.get('stocks', []) if existing_data else []
    
    logger.info(f"  现有股票: {len(existing_stocks)} 只")
    logger.info(f"  API股票: {len(new_stocks)} 只")
    
    # 构建代码集合用于快速查找
    api_stock_codes = set(s['code'] for s in new_stocks)
    existing_stock_codes = set(s['code'] for s in existing_stocks)
    
    # 找出新增的股票（API有但文件没有）
    added_stocks = []
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
    
    # 构建持久化数据
    cache_data = {
        'meta': {
            'last_updated': now.isoformat(),
            'source': 'sina_api',
            'total_count': len(all_stocks),
            'sh_count': sh_count,
            'sz_count': sz_count,
            'added_count': added_count,
            'removed_count': removed_count,
            'removed_codes': removed_codes,
            'existing_count': len(existing_stocks),
            'api_pages': api_pages,
            'version': '2.1'
        },
        'stocks': all_stocks,
        'codes': [s['code'] for s in all_stocks]
    }
    
    # 写入文件
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"持久化文件已保存: {CACHE_FILE}")
    
    # 返回数据包含新增/删除信息
    cache_data['_added_count'] = added_count
    cache_data['_removed_count'] = removed_count
    cache_data['_removed_codes'] = removed_codes
    return cache_data


def load_cache() -> Optional[Dict]:
    """
    加载缓存文件
    
    Returns:
        缓存数据字典，如果不存在则返回 None
    """
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载缓存失败: {e}")
        return None


def get_cached_stock_codes() -> List[str]:
    """
    获取缓存的股票代码列表
    
    Returns:
        股票代码列表，如果缓存不存在或无效则返回空列表
    """
    cache_data = load_cache()
    if cache_data and 'codes' in cache_data:
        return cache_data['codes']
    return []


# ============================================================
# 主函数
# ============================================================

def refresh_stock_cache() -> Dict:
    """
    增量更新股票列表持久化文件
    
    这是主入口函数，从新浪API获取主板股票列表，
    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留
    
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
            "warnings": List[str]
        }
    
    Raises:
        StockCacheError: 缓存刷新失败
    """
    logger.info("开始增量更新股票列表")
    start_time = time.time()
    
    result = {
        'success': False,
        'total_count': 0,
        'added_count': 0,
        'removed_count': 0,
        'removed_codes': [],
        'existing_count': 0,
        'sh_count': 0,
        'sz_count': 0,
        'message': '',
        'cache_file': CACHE_FILE,
        'warnings': []
    }
    
    try:
        # Step 1: 从 API 获取数据
        stocks, api_pages = fetch_stocks_from_sina()
        
        # Step 2: 增量更新持久化文件
        cache_data = save_cache(stocks, api_pages)
        
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
        
        added_count = cache_data.get('_added_count', 0)
        removed_count = cache_data.get('_removed_count', 0)
        removed_codes = cache_data.get('_removed_codes', [])
        existing_count = cache_data['meta'].get('existing_count', 0)
        
        result['success'] = True
        result['total_count'] = validation['stats']['total']
        result['added_count'] = added_count
        result['removed_count'] = removed_count
        result['removed_codes'] = removed_codes
        result['existing_count'] = existing_count
        result['sh_count'] = validation['stats']['sh_count']
        result['sz_count'] = validation['stats']['sz_count']
        
        logger.info(f"验证通过，写入持久化文件")
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
        error_msg = f"增量更新股票列表失败: {e}"
        logger.error(error_msg)
        result['message'] = error_msg
        raise RuntimeError(error_msg)


# ============================================================
# CLI 入口
# ============================================================

if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("股票列表增量更新工具")
    print("=" * 60)
    
    try:
        result = refresh_stock_cache()
        
        print("\n" + "=" * 60)
        print("更新结果")
        print("=" * 60)
        print(f"  状态: {'成功 ✓' if result['success'] else '失败 ✗'}")
        print(f"  新增: {result['added_count']} 只")
        if result['removed_count'] > 0:
            print(f"  删除: {result['removed_count']} 只（退市/ST）")
            removed_display = ', '.join(result['removed_codes'][:10])
            if result['removed_count'] > 10:
                removed_display += f"... 等共{result['removed_count']}只"
            print(f"    删除代码: {removed_display}")
        print(f"  现有: {result['existing_count']} 只")
        print(f"  总数: {result['total_count']}")
        print(f"  沪市主板: {result['sh_count']}")
        print(f"  深市主板: {result['sz_count']}")
        print(f"  持久化文件: {result['cache_file']}")
        print(f"  消息: {result['message']}")
        
        if result['warnings']:
            print("\n警告:")
            for warning in result['warnings']:
                print(f"  ⚠️ {warning}")
        
        print("=" * 60)
        sys.exit(0)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        print("=" * 60)
        sys.exit(1)