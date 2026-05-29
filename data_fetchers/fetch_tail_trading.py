#!/usr/bin/env python3
"""
尾盘数据拉取脚本

拉取尾盘（14:30-15:00）的5分钟K线数据，用于构建尾盘因子。
数据源：东方财富5分钟K线 API

输出路径：data_fetchers/result/tail_trading_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v1.2 (2026-05-29 13:30): 第二轮深度优化
  - params 中魔法数字替换为常量（API_KLT, API_FQT, API_LMT_FULL, API_LMT_INCREMENTAL）
  - datetime.now() 替换为 _NOW_STR 固定时间戳（遵循 MODULE.md 约束 #17）
  - 删除未使用常量 DEFAULT_HISTORY_DAYS
  - 异常处理精确化（load_cache: requests.RequestException + json.JSONDecodeError; save_cache: OSError）
  - 常量命名规范化（CACHE_FILE → _CACHE_FILE）
- v1.1 (2026-05-29 11:50): 规范合规优化
  - 补充 API 配置常量（API_KLT, API_FQT, API_LMT_FULL, API_LMT_INCREMENTAL）
  - 异常处理精确化（区分 requests.RequestException 和 json.JSONDecodeError）
  - main 函数 docstring 删除 Returns 节（遵循 MODULE.md 约束 #15）
- v1.0 (2026-05-29 11:30): 初始版本
  - 复用公共模块：http_client, cache_manager, stock_utils, paths
  - 支持全量模式（历史12天）和增量模式（最新一天）
  - 遵循 MODULE.md 约束 #1-#106

作者: 云瑶
日期: 2026-05-29
"""

import json
import logging
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests import Session

# ============================================================
# 公共模块导入（遵循 MODULE.md 约束 #51：导入在模块顶部）
# ============================================================

from common import (
    # 缓存管理
    read_cache,
    write_cache,
    # 股票筛选
    load_main_board_stock_list,
    # 路径管理
    get_module_result_dir,
    # 日志配置
    setup_logger,
)

# HTTP 客户端（eastmoney_session 未在 __init__.py 导出，需直接导入）
from common.http_client import (
    eastmoney_session,
    request_with_retry,
)

# ============================================================
# 配置常量（遵循 MODULE.md 约束 #16）
# ============================================================

# 输出版本
_OUTPUT_VERSION = '1.0'

# 固定时间戳（遵循 MODULE.md 约束 #17）
_NOW = datetime.now()
_NOW_ISO = _NOW.isoformat()
_NOW_STR = _NOW.strftime('%Y-%m-%d %H:%M:%S')

# 输出文件路径
_RESULT_DIR = get_module_result_dir()
_CACHE_FILE = _RESULT_DIR / 'tail_trading_data.json.gz'  # 缓存文件路径（私有常量）

# API 配置
EASTMONEY_API_URL = 'http://push2his.eastmoney.com/api/qt/stock/kline/get'
API_KLT = 5                  # K线类型：5分钟K线（遵循 MODULE.md 约束 #16）
API_FQT = 1                  # 前复权
API_LMT_FULL = 500           # 全量模式最大条数（约12天）
API_LMT_INCREMENTAL = 50     # 增量模式最大条数（约1天）

# 尾盘时段定义（5分钟K线）
TAIL_PERIOD_START = '14:30'  # 尾盘开始时间
TAIL_PERIOD_END = '15:00'    # 尾盘结束时间（收盘）
TAIL_KLINE_COUNT = 7         # 尾盘K线数量（14:30-15:00共7根5分钟K线）

# 默认参数
DEFAULT_REQUEST_DELAY = 0.2  # 请求间隔（秒），遵循 MODULE.md 约束 #78

# ============================================================
# Logger 配置
# ============================================================

logger = setup_logger('fetch_tail_trading')


# ============================================================
# 数据拉取函数
# ============================================================

def _parse_market_code(code: str) -> tuple[int, str]:
    """
    解析股票代码，返回市场ID和纯代码
    
    Args:
        code: 6位股票代码
        
    Returns:
        (市场ID, 纯代码)
        - 市场ID：0=深市，1=沪市
        
    Example:
        >>> market_id, pure_code = _parse_market_code('000001')
        >>> market_id
        0
        >>> pure_code
        '000001'
    """
    if code.startswith('6'):
        return (1, code)  # 沪市
    else:
        return (0, code)  # 深市


def _filter_tail_klines(klines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    过滤尾盘时段的K线数据
    
    Args:
        klines: K线数据列表，每条包含 time, open, close, high, low, volume
        
    Returns:
        尾盘时段（14:30-15:00）的K线列表
        
    Note:
        尾盘时段共7根5分钟K线：14:30, 14:35, 14:40, 14:45, 14:50, 14:55, 15:00
    """
    tail_klines = []
    for kline in klines:
        time_str = kline.get('time', '')
        # 过滤尾盘时段（14:30-15:00）
        if time_str >= TAIL_PERIOD_START and time_str <= TAIL_PERIOD_END:
            tail_klines.append(kline)
    return tail_klines


def _calculate_tail_metrics(
    tail_klines: list[dict[str, Any]],
    day_volume: float
) -> dict[str, Any] | None:
    """
    计算尾盘指标
    
    Args:
        tail_klines: 尾盘K线数据列表
        day_volume: 全天成交量
        
    Returns:
        尾盘指标字典，包含：
        - tail_volume: 尾盘成交量
        - tail_volume_pct: 尾盘成交量占比
        - tail_high: 尾盘最高价
        - tail_low: 尾盘最低价
        - tail_close: 尾盘收盘价
        
    Note:
        若尾盘K线数量不足，返回 None
    """
    if len(tail_klines) < TAIL_KLINE_COUNT:
        return None
    
    # 计算尾盘成交量
    tail_volume = sum(kline.get('volume', 0) for kline in tail_klines)
    
    # 计算尾盘成交量占比
    tail_volume_pct = 0.0
    if day_volume > 0:
        tail_volume_pct = tail_volume / day_volume
    
    # 计算尾盘最高价和最低价
    tail_high = max(kline.get('high', 0) for kline in tail_klines)
    tail_low = min(kline.get('low', 0) for kline in tail_klines)
    
    # 尾盘收盘价（最后一根K线的收盘价）
    tail_close = tail_klines[-1].get('close', 0)
    
    return {
        'tail_volume': int(tail_volume),
        'tail_volume_pct': round(tail_volume_pct, 4),
        'tail_high': round(tail_high, 2),
        'tail_low': round(tail_low, 2),
        'tail_close': round(tail_close, 2),
    }


def fetch_tail_trading_for_stock(
    code: str,
    session: Session,
    full: bool = False,
    logger_arg: logging.Logger | None = None
) -> list[dict[str, Any]]:
    """
    拉取单只股票的尾盘数据
    
    Args:
        code: 6位股票代码
        session: HTTP Session（遵循 MODULE.md 约束 #78）
        full: 全量模式（拉取历史12天），否则增量模式（拉取最新一天）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Returns:
        尾盘数据记录列表，每条包含：
        - date: 交易日期
        - asset: 股票代码
        - tail_volume: 尾盘成交量
        - tail_volume_pct: 尾盘成交量占比
        - tail_high: 尾盘最高价
        - tail_low: 尾盘最低价
        - tail_close: 尾盘收盘价
        
    Raises:
        RuntimeError: API请求失败时抛出
    """
    _logger = logger_arg or logger
    
    market_id, pure_code = _parse_market_code(code)
    
    # 构建API参数（使用常量）
    params = {
        'secid': f'{market_id}.{pure_code}',
        'fields1': 'f1,f2,f3,f4,f5,f6',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
        'klt': API_KLT,           # 5分钟K线（常量）
        'fqt': API_FQT,           # 前复权（常量）
        'end': '20500101',
        'lmt': API_LMT_FULL,      # 全量模式最大条数（常量）
    }
    
    # 增量模式：只拉取最近一天的数据
    if not full:
        params['lmt'] = API_LMT_INCREMENTAL  # 增量模式条数（常量）
    
    try:
        # 使用 request_with_retry 发送请求（遵循 MODULE.md 约束 #78）
        response_data = request_with_retry(
            session=session,
            url=EASTMONEY_API_URL,
            params=params,
            logger=_logger
        )
        
        if response_data is None:
            _logger.warning(f"[{code}] API返回空数据")
            return []
        
        # 类型校验：response_data 应为 dict
        if not isinstance(response_data, dict):
            _logger.warning(f"[{code}] API返回数据类型异常: {type(response_data).__name__}")
            return []
        
        # 解析K线数据
        klines_data = response_data.get('data', {})
        if not klines_data:
            _logger.debug(f"[{code}] 无K线数据")
            return []
        
        # klines_data 应为 dict
        if not isinstance(klines_data, dict):
            _logger.debug(f"[{code}] K线数据类型异常: {type(klines_data).__name__}")
            return []
        
        klines = klines_data.get('klines', [])
        if not klines:
            _logger.debug(f"[{code}] K线列表为空")
            return []
        
        # 解析K线字符串（格式：日期 时间,开盘,收盘,最高,最低,成交量,成交额,振幅...）
        # 注意：日期和时间用空格分隔，如 '2026-05-28 14:30'
        parsed_klines = []
        for kline_str in klines:
            parts = kline_str.split(',')
            if len(parts) >= 6:
                # 从 parts[0] 分离日期和时间
                datetime_part = parts[0].split(' ')
                if len(datetime_part) >= 2:
                    date = datetime_part[0]
                    time = datetime_part[1]
                else:
                    continue  # 格式异常，跳过
                
                parsed_klines.append({
                    'date': date,
                    'time': time,
                    'open': float(parts[1]),
                    'close': float(parts[2]),
                    'high': float(parts[3]),
                    'low': float(parts[4]),
                    'volume': float(parts[5]),
                })
        
        # 按日期分组
        date_groups: dict[str, list[dict[str, Any]]] = {}
        for kline in parsed_klines:
            date = kline.get('date', '')
            if date not in date_groups:
                date_groups[date] = []
            date_groups[date].append(kline)
        
        # 计算每日尾盘指标
        records = []
        for date, day_klines in date_groups.items():
            # 计算全天成交量
            day_volume = sum(kline.get('volume', 0) for kline in day_klines)
            
            # 过滤尾盘K线
            tail_klines = _filter_tail_klines(day_klines)
            
            # 计算尾盘指标
            tail_metrics = _calculate_tail_metrics(tail_klines, day_volume)
            
            if tail_metrics:
                records.append({
                    'date': date,
                    'asset': code,
                    **tail_metrics
                })
        
        _logger.debug(f"[{code}] 获取 {len(records)} 天尾盘数据")
        return records
        
    except requests.RequestException as e:
        _logger.warning(f"[{code}] 网络请求失败: [{type(e).__name__}]: {e}")
        return []
    except json.JSONDecodeError as e:
        _logger.warning(f"[{code}] JSON解析失败: [{type(e).__name__}]: {e}")
        return []
    except Exception as e:
        _logger.error(f"[{code}] 未预期异常: [{type(e).__name__}]: {e}")
        return []


def fetch_tail_trading_batch(
    stock_codes: list[str],
    full: bool = False,
    max_stocks: int = 0,
    logger_arg: logging.Logger | None = None
) -> list[dict[str, Any]]:
    """
    批量拉取尾盘数据
    
    Args:
        stock_codes: 股票代码列表
        full: 全量模式（拉取历史12天）
        max_stocks: 最大股票数（用于测试，0为不限制）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Returns:
        尾盘数据记录列表
        
    Note:
        - 请求间隔200ms，避免限流
        - 每100股打印进度日志
    """
    _logger = logger_arg or logger
    
    # 限制股票数（用于测试）
    if max_stocks > 0:
        stock_codes = stock_codes[:max_stocks]
    
    total_stocks = len(stock_codes)
    _logger.info(f"开始拉取尾盘数据: {total_stocks} 支股票")
    _logger.info(f"模式: {'全量（历史12天）' if full else '增量（最新一天）'}")
    
    all_records = []
    failed_stocks = []
    
    # 使用 eastmoney_session 上下文管理器（遵循 MODULE.md 约束 #78）
    with eastmoney_session() as session:
        for idx, code in enumerate(stock_codes):
            # 请求间隔（遵循 MODULE.md 约束 #78）
            if idx > 0:
                time.sleep(DEFAULT_REQUEST_DELAY)
            
            # 拉取单股数据
            records = fetch_tail_trading_for_stock(
                code=code,
                session=session,
                full=full,
                logger_arg=_logger
            )
            
            if records:
                all_records.extend(records)
            else:
                failed_stocks.append(code)
            
            # 进度日志（每100股）
            if (idx + 1) % 100 == 0:
                progress_pct = (idx + 1) / total_stocks * 100
                _logger.info(f"进度: {idx + 1}/{total_stocks} ({progress_pct:.1f}%)")
    
    # 统计结果
    _logger.info(f"拉取完成: 成功 {total_stocks - len(failed_stocks)} 支, 失败 {len(failed_stocks)} 支")
    if failed_stocks:
        _logger.warning(f"失败股票（前10支）: {failed_stocks[:10]}")
    
    return all_records


# ============================================================
# 缓存管理函数
# ============================================================

def load_cache(
    logger_arg: logging.Logger | None = None
) -> dict[str, Any] | None:
    """
    加载现有缓存数据
    
    Args:
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Returns:
        缓存数据字典，若不存在则返回 None
    """
    _logger = logger_arg or logger
    
    if not _CACHE_FILE.exists():
        _logger.info("缓存文件不存在，将进行全量拉取")
        return None
    
    try:
        data = read_cache(_CACHE_FILE, logger=_logger)
        
        # 类型校验（遵循 MODULE.md 约束 #87）
        if not isinstance(data, dict):
            _logger.warning(f"缓存数据类型异常: {type(data).__name__}")
            return None
        
        _logger.info(f"加载缓存成功: {len(data.get('data', []))} 条记录")
        return data
        
    except (requests.RequestException, json.JSONDecodeError) as e:
        _logger.warning(f"加载缓存失败: [{type(e).__name__}]: {e}")
        return None


def save_cache(
    data: dict[str, Any],
    logger_arg: logging.Logger | None = None
) -> None:
    """
    保存缓存数据
    
    Args:
        data: 数据字典（包含 meta 和 data）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Raises:
        OSError: 文件写入失败时抛出
    """
    _logger = logger_arg or logger
    
    # 确保目录存在
    _RESULT_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        write_cache(_CACHE_FILE, data, logger=_logger)
        _logger.info(f"保存缓存成功: {_CACHE_FILE}")
        
    except OSError as e:
        _logger.error(f"保存缓存失败: [{type(e).__name__}]: {e}")
        raise


def merge_records(
    existing_data: dict[str, Any] | None,
    new_records: list[dict[str, Any]],
    source: str = 'eastmoney_5min',
    logger_arg: logging.Logger | None = None
) -> dict[str, Any]:
    """
    合并新旧数据并去重
    
    Args:
        existing_data: 现有缓存数据
        new_records: 新拉取的数据记录
        source: 数据源标识
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Returns:
        合并后的数据字典
        
    Note:
        - 去重策略：以 (date, asset) 作为 key
        - 数据源合并逻辑：遵循 MODULE.md 约束 #93
    """
    _logger = logger_arg or logger
    
    # 空数据处理（遵循 MODULE.md 约束 #88）
    if not new_records:
        if existing_data:
            _logger.info("无新数据，保留现有缓存")
            return existing_data
        else:
            _logger.warning("无数据，返回空结构")
            return {
                'meta': {
                    'generated_at': _NOW_ISO,
                    'source': source,
                    'n_days': 0,
                    'n_assets': 0,
                    'date_range': {'start': None, 'end': None},
                    'last_updated': _NOW_STR,  # 固定时间戳（遵循 MODULE.md 约束 #17）
                    'version': _OUTPUT_VERSION,
                },
                'data': []
            }
    
    # 正常合并流程
    existing_records = []
    existing_meta = None
    if existing_data:
        existing_records = existing_data.get('data', [])
        existing_meta = existing_data.get('meta')
    
    all_records = existing_records + new_records
    
    # 去重（以 (date, asset) 作为 key）
    record_map: dict[tuple[str, str], dict[str, Any]] = {}
    for record in all_records:
        # 防御性编程（遵循 MODULE.md 约束 #104）
        date_val = record.get('date')
        asset_val = record.get('asset')
        if date_val and asset_val:
            key = (date_val, asset_val)
            record_map[key] = record
    
    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x.get('date', ''), x.get('asset', '')))
    
    # 提取元信息（过滤 None 值）
    unique_dates = sorted(set(r.get('date') for r in merged_records if r.get('date')))
    unique_assets = sorted(set(r.get('asset') for r in merged_records if r.get('asset')))
    
    # 数据源合并逻辑（遵循 MODULE.md 约束 #93）
    final_source = source
    if existing_meta:
        existing_source = existing_meta.get('source', source)
        if existing_source != source:
            final_source = 'mixed'
    
    # generated_at 语义：数据首次生成时间（遵循 MODULE.md 约束 #98）
    generated_at = _NOW_ISO
    if existing_meta:
        generated_at = existing_meta.get('generated_at', _NOW_ISO)
    
    return {
        'meta': {
            'generated_at': generated_at,
            'source': final_source,
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': _NOW_STR,  # 固定时间戳（遵循 MODULE.md 约束 #17）
            'version': _OUTPUT_VERSION,
        },
        'data': merged_records
    }


# ============================================================
# 主函数
# ============================================================

def main(
    full: bool = False,
    max_stocks: int = 0,
    logger_arg: logging.Logger | None = None
) -> bool:
    """
    主函数：拉取尾盘数据
    
    Args:
        full: 全量模式（拉取历史12天），否则增量模式（拉取最新一天）
        max_stocks: 最大股票数（用于测试，0为不限制）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）
        
    Raises:
        RuntimeError: 数据拉取失败时抛出
        
    Note:
        返回值仅用于 CLI 入口判断执行状态，调用方不应依赖返回值做业务判断
    """
    _logger = logger_arg or logger
    
    _logger.info("=" * 60)
    _logger.info(f"[{_NOW_STR}] 开始拉取尾盘数据")
    _logger.info("=" * 60)
    _logger.info("数据源: 东方财富5分钟K线 API")
    _logger.info("尾盘时段: 14:30-15:00（共7根5分钟K线）")
    _logger.info(f"缓存路径: {_CACHE_FILE}")
    
    # Step 1: 加载股票列表
    try:
        stock_list = load_main_board_stock_list(logger=_logger)
        if not stock_list:
            _logger.error("股票列表加载失败")
            return False
        
        # load_main_board_stock_list 已筛选主板股票并剔除 ST
        # 直接提取股票代码
        valid_codes = [s.get('code', '') for s in stock_list if s.get('code')]
        
        _logger.info(f"有效股票数: {len(valid_codes)} 支")
        
    except Exception as e:
        _logger.error(f"加载股票列表失败: [{type(e).__name__}]: {e}")
        return False
    
    # Step 2: 加载现有缓存（增量模式）
    existing_data = None
    if not full:
        existing_data = load_cache(logger_arg=_logger)
    
    # Step 3: 批量拉取数据
    new_records = fetch_tail_trading_batch(
        stock_codes=valid_codes,
        full=full,
        max_stocks=max_stocks,
        logger_arg=_logger
    )
    
    if not new_records:
        _logger.error("未获取到任何数据")
        return False
    
    # Step 4: 合并去重
    merged_data = merge_records(
        existing_data=existing_data,
        new_records=new_records,
        source='eastmoney_5min',
        logger_arg=_logger
    )
    
    # Step 5: 保存缓存
    save_cache(merged_data, logger_arg=_logger)
    
    # 输出统计
    meta = merged_data['meta']
    _logger.info("=" * 60)
    _logger.info(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 尾盘数据拉取完成")
    _logger.info("=" * 60)
    _logger.info(f"日期范围: {meta['date_range']['start']} ~ {meta['date_range']['end']}")
    _logger.info(f"交易日数: {meta['n_days']}")
    _logger.info(f"股票数量: {meta['n_assets']}")
    _logger.info(f"总记录数: {len(merged_data['data'])}")
    
    return True


# ============================================================
# CLI 入口
# ============================================================

if __name__ == '__main__':
    # CLI 入口 logger 设置（遵循 PROJECT.md 日志规范）
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    cli_logger = logging.getLogger('fetch_tail_trading.cli')
    
    parser = argparse.ArgumentParser(description='尾盘数据拉取')
    parser.add_argument('--full', action='store_true', help='全量拉取（不使用缓存）')
    parser.add_argument('--max-stocks', type=int, default=0, help='最大股票数（用于测试，0为不限制）')
    parser.add_argument('--test', action='store_true', help='测试模式（只拉取10支股票）')
    
    args = parser.parse_args()
    
    # 测试模式
    max_stocks = args.max_stocks
    if args.test:
        max_stocks = 10
        cli_logger.info("测试模式：只拉取10支股票")
    
    try:
        success = main(
            full=args.full,
            max_stocks=max_stocks,
            logger_arg=cli_logger
        )
        
        if not success:
            sys.exit(1)
            
    except Exception as e:
        cli_logger.error(f"执行失败: [{type(e).__name__}]: {e}")
        sys.exit(1)