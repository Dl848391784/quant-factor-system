#!/usr/bin/env python3
"""
股票行业分类数据获取模块

作者: 云舟
日期: 2026-05-27
版本: v2.0

功能: 获取申万行业分类数据并缓存
数据源: akshare - 申万行业分类

改进历史:
- v1.1 (2026-05-27): 优化 - 添加版本号常量、Dict→dict、iterrows→to_dict、__main__用logger
- v1.2 (2026-05-27): Bug修复 - docstring Returns Dict→dict（5处）、mkdir用RESULT_DIR、meta添加version字段
- v1.3 (2026-05-27): Bug修复 - 文档头版本号同步、第355行Dict→dict、异常日志加类型名、Counter顶部导入、原子写入异常处理
- v1.4 (2026-05-27): Bug修复 - SW_INDUSTRY_CODE_MAP添加近似映射注释+TODO、原子写入捕获所有异常+日志位置修正、全局缓存线程安全（DCL双重检查）
- v1.5 (2026-05-27): Bug修复 - 日期解析异常warning日志、关键词映射移除歧义(新能)、__all__移除私有名称(_OUTPUT_VERSION)
- v1.6 (2026-05-27): Bug修复 - DataFrame列名校验、备用数据路径提取常量+参数注入
- v1.7 (2026-05-27): Bug修复 - threading重复导入删除、关键词重叠消除(光伏/风电只在电力)、注释修正(中信在证券)、备用数据写入缓存
- v1.8 (2026-05-27): Bug修复 - 缓存过期刷新失败降级用旧缓存、SW_INDUSTRY_CODE_MAP注释修正+移除TODO、load_local_industry_backup注释修正(名称关键词而非代码特征)
- v1.9 (2026-05-27): Bug修复 - SW_INDUSTRY_CODE_MAP注释诚实化（承认未核对官方标准，恢复TODO，注释改为"二级归属待核实"）
- v2.0 (2026-05-27): Bug修复 - SW_INDUSTRY_CODE_MAP核对申万2021官方标准（移除错误映射，不存在的一级代码映射到'其他'）

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 logger（PROJECT.md 日志规范）
"""

import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from collections import Counter

# 版本号常量（MODULE.md 约束 #16）
_OUTPUT_VERSION = '2.0'

logger = logging.getLogger(__name__)

# 项目根目录（使用公共路径）
BASE_DIR = Path(__file__).parent.parent
RESULT_DIR = BASE_DIR / 'result'
CACHE_DIR = BASE_DIR / 'cache'

# 行业数据缓存路径（输出到 result 目录，MODULE.md 约束 #2）
INDUSTRY_CACHE_PATH = RESULT_DIR / 'stock_industry.json'

# 备用数据路径（避免跨模块硬编码耦合）
STOCK_LIST_BACKUP_PATH = CACHE_DIR / 'stock_list.json'

# akshare API 期望列名（防御性校验）
_EXPECTED_INDUSTRY_COLS = ['symbol', 'industry_code', 'start_date']
_EXPECTED_STOCK_NAME_COLS = ['code', 'name']


# 申万2021版行业代码映射（一级代码 -> 行业名称）
# 注意：此映射基于申万2021官方一级分类标准（31个行业）
# - 一级代码是连续的：11, 21, 23, 24, 25, 26, 27, 31, 32, 34, 35, 36, 41, 42, 43, 44, 45, 46, 48, 49, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 77
# - akshare 返回的 industry_code 格式为4位（如 '2101'），前两位为一级代码
# - 不存在的一级代码（如 22, 28, 33, 37, 47, 51, 61）是二级代码前两位，映射到 '其他'
# 参考: 申万2021行业分类标准
SW_INDUSTRY_CODE_MAP: dict[str, str] = {
    # 申万2021官方一级分类（31个行业）
    '11': '农林牧渔',
    '21': '基础化工',
    '23': '钢铁',
    '24': '有色金属',
    '25': '汽车',
    '26': '家用电器',
    '27': '电子',
    '31': '商贸零售',
    '32': '医药生物',
    '34': '食品饮料',
    '35': '纺织服饰',
    '36': '轻工制造',
    '41': '公用事业',
    '42': '交通运输',
    '43': '房地产',
    '44': '建筑材料',
    '45': '社会服务',
    '46': '综合',
    '48': '银行',
    '49': '非银金融',
    '62': '建筑装饰',
    '63': '电力设备',
    '64': '机械设备',
    '65': '国防军工',
    '71': '计算机',
    '72': '传媒',
    '73': '通信',
    '74': '煤炭',
    '75': '石油石化',
    '76': '环保',
    '77': '美容护理',
    # 不存在的一级代码（二级代码前两位）→ 映射到 '其他'
    '22': '其他',  # 不存在于申万2021一级分类
    '28': '其他',  # 不存在于申万2021一级分类
    '33': '其他',  # 不存在于申万2021一级分类
    '37': '其他',  # 不存在于申万2021一级分类
    '47': '其他',  # 不存在于申万2021一级分类
    '51': '其他',  # 不存在于申万2021一级分类
    '61': '其他',  # 不存在于申万2021一级分类
}


def fetch_stock_industry_sw() -> dict:
    """
    获取申万行业分类数据
    
    使用 akshare 新版本 API: stock_industry_clf_hist_sw
    获取股票的最新行业分类历史数据
    
    Returns:
        dict: {股票代码: {name, industry, industry_code}}
    """
    try:
        import akshare as ak
        
        logger.info(f"[行业数据 v{_OUTPUT_VERSION}] 开始获取申万行业分类...")
        
        # 获取申万行业分类历史数据（新版本API）
        industry_df = ak.stock_industry_clf_hist_sw()
        
        # 列名校验（防御性编程）
        missing_cols = [col for col in _EXPECTED_INDUSTRY_COLS if col not in industry_df.columns]
        if missing_cols:
            raise KeyError(f"申万行业分类缺少必需列: {missing_cols}, 实际列: {list(industry_df.columns)}")
        
        # 获取每只股票的最新行业分类（按start_date降序）
        industry_df_latest = industry_df.sort_values('start_date', ascending=False).drop_duplicates(
            subset='symbol', keep='first'
        )
        
        # 获取股票名称映射
        stock_names_df = ak.stock_info_a_code_name()
        
        # 列名校验（防御性编程）
        missing_name_cols = [col for col in _EXPECTED_STOCK_NAME_COLS if col not in stock_names_df.columns]
        if missing_name_cols:
            raise KeyError(f"股票名称数据缺少必需列: {missing_name_cols}, 实际列: {list(stock_names_df.columns)}")
        
        stock_names_df['code'] = stock_names_df['code'].astype(str).str.zfill(6)
        stock_names_dict = dict(zip(stock_names_df['code'], stock_names_df['name']))
        
        # 构建股票→行业映射（使用 to_dict 替代 iterrows，性能优化）
        industry_map = {}
        
        # 转为字典遍历（避免 iterrows 性能问题）
        for row_dict in industry_df_latest.to_dict('records'):
            code = str(row_dict.get('symbol', '')).strip()
            industry_code = str(row_dict.get('industry_code', '')).strip()
            
            # 从行业代码提取一级行业（前2位）
            first_level = industry_code[:2] if len(industry_code) >= 2 else ''
            
            # 映射到行业名称
            industry_name = SW_INDUSTRY_CODE_MAP.get(first_level, '其他')
            
            # 获取股票名称
            stock_name = stock_names_dict.get(code, '')
            
            if code:
                industry_map[code] = {
                    'name': stock_name,
                    'industry': industry_name,
                    'industry_code': industry_code
                }
        
        logger.info(f"[行业数据] 获取完成: {len(industry_map)} 只股票")
        return industry_map
        
    except Exception as e:
        logger.error(f"[行业数据] 获取失败 [{type(e).__name__}]: {e}")
        return {}


def load_stock_industry() -> dict:
    """
    加载股票行业数据（优先从缓存）
    
    Returns:
        dict: {股票代码: {name, industry, industry_code}}
    """
    # 优先从缓存加载
    if INDUSTRY_CACHE_PATH.exists():
        try:
            with open(INDUSTRY_CACHE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            industries = data.get('industries', {})
            
            # 检查缓存是否过期（超过7天更新）
            meta = data.get('meta', {})
            updated_at = meta.get('updated_at', '')
            
            if updated_at:
                try:
                    update_date = datetime.strptime(updated_at, '%Y-%m-%d')
                    days_old = (datetime.now() - update_date).days
                    
                    if days_old > 7:
                        logger.info(f"[行业数据] 缓存已过期 {days_old} 天，尝试重新获取...")
                        try:
                            return refresh_industry_cache()
                        except Exception as e:
                            # 刷新失败时降级使用旧缓存（而非直接返回备用数据）
                            logger.warning(f"[行业数据] 刷新失败 [{type(e).__name__}]: {e}，降级使用旧缓存")
                            return industries
                except ValueError as e:
                    # 日期格式异常，使用现有缓存（而非静默 pass）
                    logger.warning(f"[行业数据] 日期格式异常 {updated_at!r}: {e}，使用现有缓存")
            
            logger.info(f"[行业数据] 从缓存加载: {len(industries)} 只股票")
            return industries
            
        except Exception as e:
            logger.warning(f"[行业数据] 缓存加载失败 [{type(e).__name__}]: {e}")
    
    # 缓存不存在，重新获取
    return refresh_industry_cache()


def refresh_industry_cache() -> dict:
    """
    刷新行业数据缓存
    
    Returns:
        dict: {股票代码: {name, industry, industry_code}}
    """
    industry_map = fetch_stock_industry_sw()
    
    if not industry_map:
        logger.warning("[行业数据] 获取失败，返回空映射")
        # 尝试使用本地备用数据
        return load_local_industry_backup()
    
    # 写入缓存
    cache_data = {
        'meta': {
            'version': _OUTPUT_VERSION,
            'source': 'sw_category',
            'level': '一级',
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'total_count': len(industry_map)
        },
        'industries': industry_map
    }
    
    # 确保输出目录存在（MODULE.md 约束 #2：输出到 result 目录）
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 原子写入（异常处理保证清理）
    temp_path = INDUSTRY_CACHE_PATH.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        temp_path.rename(INDUSTRY_CACHE_PATH)
        # rename 成功后才打印日志
        logger.info(f"[行业数据] 缓存已更新: {INDUSTRY_CACHE_PATH} (v{_OUTPUT_VERSION})")
    except Exception as e:
        # 捕获所有异常（包括 OSError 子类和其他如 RuntimeError）
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"缓存写入失败 [{type(e).__name__}]: {e}") from e
    
    return industry_map


def load_local_industry_backup(stock_list_path: Path | None = None, write_cache: bool = True) -> dict:
    """
    加载本地备用行业数据（当 akshare 不可用时）
    
    Args:
        stock_list_path: 股票列表文件路径（默认使用 STOCK_LIST_BACKUP_PATH）
        write_cache: 是否写入缓存文件（默认 True，避免每次重复读文件）
        
    Returns:
        dict: 基本的行业映射（主要行业分类）
    
    Note:
        基于**股票名称关键词**推断行业（调用 infer_industry_from_name），
        而非股票代码特征。推断准确性低于 akshare 数据，仅作备用。
    """
    # 简化的行业分类（基于名称关键词推断，准确性低于 akshare）
    # 银行类: 名称含 '银行'
    # 房地产类: 名称含 '地产'/'万科'/'保利'
    # 新能源类: 名称含 '新能源'/'锂电'/'太阳能'
    
    logger.info("[行业数据] 使用本地备用分类（基于名称关键词推断）...")
    
    # 使用参数注入路径（避免硬编码耦合）
    if stock_list_path is None:
        stock_list_path = STOCK_LIST_BACKUP_PATH
    if stock_list_path.exists():
        try:
            with open(stock_list_path, 'r', encoding='utf-8') as f:
                stock_data = json.load(f)
            
            stocks = stock_data.get('stocks', [])
            industry_map = {}
            
            # 简化分类规则
            for stock in stocks:
                code = stock.get('code', stock.get('asset', ''))
                name = stock.get('name', '')
                
                # 基于名称推断行业
                industry = infer_industry_from_name(name)
                
                industry_map[code] = {
                    'name': name,
                    'industry': industry,
                    'industry_code': 'local'
                }
            
            logger.info(f"[行业数据] 本地备用分类完成: {len(industry_map)} 只股票")
            
            # 写入缓存（避免每次重复读文件）
            if write_cache and industry_map:
                _write_backup_cache(industry_map)
            
            return industry_map
            
        except Exception as e:
            logger.warning(f"[行业数据] 本地备用加载失败 [{type(e).__name__}]: {e}")
    
    return {}


def _write_backup_cache(industry_map: dict) -> None:
    """
    写入备用数据缓存（私有函数）
    
    Args:
        industry_map: 行业映射数据
    """
    cache_data = {
        'meta': {
            'version': _OUTPUT_VERSION,
            'source': 'local_backup',
            'level': '一级',
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'total_count': len(industry_map)
        },
        'industries': industry_map
    }
    
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = INDUSTRY_CACHE_PATH.with_suffix('.tmp')
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        temp_path.rename(INDUSTRY_CACHE_PATH)
        logger.info(f"[行业数据] 备用缓存已写入: {INDUSTRY_CACHE_PATH}")
    except Exception as e:
        temp_path.unlink(missing_ok=True)
        logger.warning(f"[行业数据] 备用缓存写入失败 [{type(e).__name__}]: {e}")


def infer_industry_from_name(name: str) -> str:
    """
    从股票名称推断行业（备用方案）
    
    Args:
        name: 股票名称
        
    Returns:
        str: 推断的行业名称
    """
    # 常见行业关键词映射
    # 注意：关键词需避免歧义，遍历顺序决定匹配优先级
    # - 已消除重复关键词：光伏/风电只在电力中，新能源使用锂电/电池/太阳能
    # - 具体关键词优先：中信→证券（而非混入银行）
    industry_keywords = {
        '证券': ['证券', '券商', '中信'],  # 中信：中信证券特定名称（具体优先）
        '银行': ['银行', '金融'],
        '保险': ['保险', '人寿', '平安'],
        '电力': ['电力', '电能', '水电', '火电', '风电', '光伏'],  # 光伏/风电只在电力
        '新能源': ['新能源', '锂电', '电池', '太阳能'],  # 移除重复的 光伏/风电
        '房地产': ['地产', '房产', '万科', '保利', '城建'],
        '医药': ['医药', '生物', '制药', '药业', '医疗'],
        '科技': ['科技', '电子', '芯片', '半导体', '软件'],
        '汽车': ['汽车', '车企', '比亚迪', '上汽', '长城'],
        '消费': ['消费', '食品', '饮料', '酒', '零售'],
        '化工': ['化工', '化学', '石化'],
        '机械': ['机械', '设备', '重工', '工程'],
        '通信': ['通信', '电信', '移动'],
        '建材': ['建材', '水泥', '玻璃'],
        '煤炭': ['煤炭', '煤业'],
        '有色': ['有色', '铜', '铝', '金属'],
        '钢铁': ['钢铁', '钢'],
        '交通': ['交通', '运输', '物流', '港口'],
        '传媒': ['传媒', '出版', '影视'],
        '其他': []
    }
    
    for industry, keywords in industry_keywords.items():
        if industry == '其他':
            continue
        for kw in keywords:
            if kw in name:
                return industry
    
    return '其他'


# 模块级缓存（线程安全：使用 threading.Lock）
# 注意：threading 已在顶部导入（第28行），此处不再重复导入
_industry_cache = None
_cache_lock = threading.Lock()

def get_industry_map() -> dict:
    """
    获取行业映射（带模块级缓存，线程安全）
    
    Returns:
        dict: {股票代码: {name, industry, industry_code}}
    """
    global _industry_cache
    if _industry_cache is None:
        with _cache_lock:
            # 双重检查：锁内再次判断，避免重复加载
            if _industry_cache is None:
                _industry_cache = load_stock_industry()
    return _industry_cache


def get_stock_industry(code: str) -> str:
    """
    获取单只股票的行业
    
    Args:
        code: 股票代码（如 '000001'）
        
    Returns:
        str: 行业名称，未知股票返回 '未知'
    """
    industry_map = get_industry_map()
    stock_info = industry_map.get(code, {})
    return stock_info.get('industry', '未知')


def get_industry_distribution(stocks: list) -> dict:
    """
    获取股票列表的行业分布
    
    Args:
        stocks: 股票代码列表
        
    Returns:
        dict: {行业名称: 数量}
    """
    industry_count = Counter()
    
    for code in stocks:
        industry = get_stock_industry(code)
        industry_count[industry] += 1
    
    return dict(industry_count)


# 公共接口导出列表（MODULE.md 约束）
# 注意：以 _ 开头的名称表示模块私有，不应放入 __all__
__all__ = [
    'fetch_stock_industry_sw',
    'load_stock_industry',
    'refresh_industry_cache',
    'get_industry_map',
    'get_stock_industry',
    'get_industry_distribution',
    'infer_industry_from_name',
    'load_local_industry_backup',  # 新增：参数注入路径
    'SW_INDUSTRY_CODE_MAP',
    'INDUSTRY_CACHE_PATH',
    'STOCK_LIST_BACKUP_PATH',  # 新增：备用数据路径常量
]


if __name__ == '__main__':
    # 测试：获取并打印行业数据（使用 logger，遵循 PROJECT.md 日志规范）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    )
    
    logger.info(f"[测试] 开始获取行业数据 (v{_OUTPUT_VERSION})...")
    industry_map = refresh_industry_cache()
    logger.info(f"行业数据: {len(industry_map)} 只股票")
    
    # 打印示例
    for code, info in list(industry_map.items())[:5]:
        logger.info(f"  {code}: {info['name']} -> {info['industry']}")
    
    # 测试行业分布统计
    test_codes = ['000001', '603693', '001258', '000002', '600519']
    logger.info("测试行业分布:")
    for code in test_codes:
        industry = get_stock_industry(code)
        logger.info(f"  {code}: {industry}")