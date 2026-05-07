#!/usr/bin/env python3
"""
股票行业分类数据获取模块
作者: 云舟 🛠️
功能: 获取申万行业分类数据并缓存

数据源: akshare - 申万行业分类

改进 1: 行业分散约束支持模块
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache'

# 行业数据缓存路径
INDUSTRY_CACHE_PATH = CACHE_DIR / 'stock_industry.json'


# 申万2021版行业代码映射（一级代码 -> 行业名称）
# 基于实际股票验证建立
SW_INDUSTRY_CODE_MAP = {
    '11': '农林牧渔',
    '21': '基础化工',
    '22': '基础化工',
    '23': '钢铁',
    '24': '有色金属',
    '25': '汽车',
    '26': '家用电器',
    '27': '电子',
    '28': '汽车',
    '31': '商贸零售',
    '32': '医药生物',
    '33': '家用电器',
    '34': '食品饮料',
    '35': '纺织服饰',
    '36': '轻工制造',
    '37': '医药生物',
    '41': '公用事业',
    '42': '交通运输',
    '43': '房地产',
    '44': '建筑材料',
    '45': '社会服务',
    '46': '综合',
    '47': '综合',
    '48': '银行',
    '49': '非银金融',
    '51': '综合',
    '61': '建筑材料',
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
}


def fetch_stock_industry_sw() -> Dict:
    """
    获取申万行业分类数据
    
    使用 akshare 新版本 API: stock_industry_clf_hist_sw
    获取股票的最新行业分类历史数据
    
    Returns:
        Dict: {股票代码: {name, industry, industry_code}}
    """
    try:
        import akshare as ak
        
        logger.info("[行业数据] 开始获取申万行业分类...")
        
        # 获取申万行业分类历史数据（新版本API）
        industry_df = ak.stock_industry_clf_hist_sw()
        
        # 获取每只股票的最新行业分类（按start_date降序）
        industry_df_latest = industry_df.sort_values('start_date', ascending=False).drop_duplicates(
            subset='symbol', keep='first'
        )
        
        # 获取股票名称映射
        stock_names_df = ak.stock_info_a_code_name()
        stock_names_df['code'] = stock_names_df['code'].astype(str).str.zfill(6)
        stock_names_dict = dict(zip(stock_names_df['code'], stock_names_df['name']))
        
        # 构建股票→行业映射
        industry_map = {}
        
        for _, row in industry_df_latest.iterrows():
            code = str(row.get('symbol', '')).strip()
            industry_code = str(row.get('industry_code', '')).strip()
            
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
        logger.error(f"[行业数据] 获取失败: {e}")
        return {}


def load_stock_industry() -> Dict:
    """
    加载股票行业数据（优先从缓存）
    
    Returns:
        Dict: {股票代码: {name, industry, industry_code}}
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
                        logger.info(f"[行业数据] 缓存已过期 {days_old} 天，重新获取...")
                        return refresh_industry_cache()
                except ValueError:
                    pass  # 日期解析失败，使用缓存
            
            logger.info(f"[行业数据] 从缓存加载: {len(industries)} 只股票")
            return industries
            
        except Exception as e:
            logger.warning(f"[行业数据] 缓存加载失败: {e}")
    
    # 缓存不存在，重新获取
    return refresh_industry_cache()


def refresh_industry_cache() -> Dict:
    """
    刷新行业数据缓存
    
    Returns:
        Dict: {股票代码: {name, industry, industry_code}}
    """
    industry_map = fetch_stock_industry_sw()
    
    if not industry_map:
        logger.warning("[行业数据] 获取失败，返回空映射")
        # 尝试使用本地备用数据
        return load_local_industry_backup()
    
    # 写入缓存
    cache_data = {
        'meta': {
            'source': 'sw_category',
            'level': '一级',
            'updated_at': datetime.now().strftime('%Y-%m-%d'),
            'total_count': len(industry_map)
        },
        'industries': industry_map
    }
    
    # 确保缓存目录存在
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 原子写入
    temp_path = INDUSTRY_CACHE_PATH.with_suffix('.tmp')
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    temp_path.rename(INDUSTRY_CACHE_PATH)
    logger.info(f"[行业数据] 缓存已更新: {INDUSTRY_CACHE_PATH}")
    
    return industry_map


def load_local_industry_backup() -> Dict:
    """
    加载本地备用行业数据（当 akshare 不可用时）
    
    Returns:
        Dict: 基本的行业映射（主要行业分类）
    """
    # 简化的行业分类（基于股票代码特征）
    # 银行: 000001-000999, 600000-600999
    # 房地产: 000002 类
    # 新能源/电力: 603693 类
    
    logger.info("[行业数据] 使用本地备用分类...")
    
    # 从 stock_list.json 加载股票基本信息
    stock_list_path = CACHE_DIR / 'stock_list.json'
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
            return industry_map
            
        except Exception as e:
            logger.warning(f"[行业数据] 本地备用加载失败: {e}")
    
    return {}


def infer_industry_from_name(name: str) -> str:
    """
    从股票名称推断行业（备用方案）
    
    Args:
        name: 股票名称
        
    Returns:
        str: 推断的行业名称
    """
    # 常见行业关键词映射
    industry_keywords = {
        '银行': ['银行', '金融', '信达', '华创'],
        '证券': ['证券', '券商', '中信'],
        '保险': ['保险', '人寿', '平安'],
        '电力': ['电力', '电能', '新能', '水电', '火电', '风电', '光伏'],
        '新能源': ['新能', '光伏', '锂电', '电池', '风电', '太阳能'],
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


# 模块级缓存
_industry_cache = None

def get_industry_map() -> Dict:
    """
    获取行业映射（带模块级缓存）
    
    Returns:
        Dict: {股票代码: {name, industry, industry_code}}
    """
    global _industry_cache
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


def get_industry_distribution(stocks: list) -> Dict:
    """
    获取股票列表的行业分布
    
    Args:
        stocks: 股票代码列表
        
    Returns:
        Dict: {行业名称: 数量}
    """
    from collections import Counter
    industry_count = Counter()
    
    for code in stocks:
        industry = get_stock_industry(code)
        industry_count[industry] += 1
    
    return dict(industry_count)


if __name__ == '__main__':
    # 测试：获取并打印行业数据
    print("[测试] 开始获取行业数据...")
    industry_map = refresh_industry_cache()
    print(f"行业数据: {len(industry_map)} 只股票")
    
    # 打印示例
    for code, info in list(industry_map.items())[:5]:
        print(f"  {code}: {info['name']} -> {info['industry']}")
    
    # 测试行业分布统计
    test_codes = ['000001', '603693', '001258', '000002', '600519']
    print("\n测试行业分布:")
    for code in test_codes:
        industry = get_stock_industry(code)
        print(f"  {code}: {industry}")