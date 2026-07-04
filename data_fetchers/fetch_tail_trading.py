#!/usr/bin/env python3
"""
尾盘数据拉取脚本

拉取尾盘（14:00-15:00）的5分钟K线数据，用于构建尾盘因子。
数据源：新浪财经5分钟K线 API（v3.0: 东财API不可用，改用新浪API）

输出路径：data_fetchers/result/tail_trading_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v3.9 (2026-06-04): 修复 Pitfall 162——全量模式强制拉取所有股票
  - 问题：原逻辑只检查股票完整性（missing_codes + cached_failed_valid），不检查日期完整性
  - 影响：用户指定 --full 参数期望全量拉取，但脚本检测到股票完整后跳过，缺失日期无法补齐
  - 修复：全量模式下强制拉取所有有效股票（codes_to_fetch = valid_codes），删除跳过逻辑
  - 验证：运行 --full 后补齐 06-01、06-02 缺失日期
- v3.8 (2026-05-31): Bug修复——5项问题清理（第八轮）
  - fetch_tail_trading_batch 统计日志补充 total_stocks：三项状态改为 N/total 格式，读者可直观验证三项之和
  - fetch_tail_trading_for_stock kline_time 规范化：去掉微秒后缀，与 tuple 中 datetime_time 对象语义一致
  - _calculate_tail_metrics 删除冗余排序：直接利用 dict 插入顺序（Python 3.7+），与 excess_timestamps 处理一致
  - main 全量模式补充设计注释：说明失败股票拉全量历史的合理性，merge_records 去重消除重复
  - merge_records 防御性处理顺序调整：与函数签名参数顺序对应，避免维护者困惑
  - fetch_tail_trading_batch 统计语义修正：分别输出 success/no_data/failed 三种状态数量
  - fetch_tail_trading_batch 字典访问改为 .get()：避免 KeyError，status 缺失时计入失败
  - main 结构校验日志表达式修正：正确反映实际类型而非错误逻辑
  - _calculate_tail_metrics 提取排序：避免两个分支重复排序，统一处理
  - merge_records 补充边界日志：无现有缓存且无新数据时说明新建空结构
  - main 全量模式简化合并逻辑：因 cached_failed_valid 与 missing_codes 定义互斥删除冗余过滤
  - fetch_tail_trading_for_stock 外层 except 注释：说明为非预期异常兜底而非主要错误处理
  - fetch_tail_trading_for_stock 防御性检查注释：说明正常流程不可达，保留以防未来变更
- v3.6 (2026-05-30): Bug修复——8项问题清理（第六轮）
  - 删除 date 规范化死代码：Python strptime('%Y-%m-%d') 已支持单数字月日，手动解析分支冗余
  - 单条K线字段解析独立化：单条失败不影响其他K线，改用独立 try-except 并记录 warning
  - 删除 overlap_count 死代码：missing_codes 与 cached_failed_valid 定义互斥，overlap_count 永远为 0
  - batch_result 字典访问改为 .get()：避免 KeyError 不被 CLI 捕获，返回结构异常时记录 error
  - 动态引用版本号：main 开头日志改为 f"...（v{_OUTPUT_VERSION}）"
  - merge_records 快速路径 date_range 注释：说明有意只读引用，未来修改需浅层复制
  - _filter_tail_klines 分别统计：空字段数量与格式异常数量分开输出，便于区分数据问题根源
  - _calculate_tail_metrics 超量截断日志：补充打印超出时间戳列表，便于判断数据异常
- v3.5 (2026-05-30): Bug修复——8项问题清理（第五轮）
  - 扩展异常捕获：fetch_tail_trading_for_stock 新增 TypeError，覆盖 float(None) 等情况
  - 截断超量K线：_calculate_tail_metrics 去重后超过13根时截取前13条
  - date 格式规范化：避免月份不补零导致重复记录（如 '2026-5-29' → '2026-05-29'）
  - 消除浅拷贝隐患：merge_records 快速路径改用直接构建新字典
  - 全量模式确定性顺序：codes_to_fetch 按 valid_codes 原序构建，不依赖集合遍历
  - 日志措辞修正：全量模式补充重叠数量说明，避免混淆
  - 时间解析汇总统计：_filter_tail_klines 改为循环结束后输出一条汇总 warning
  - date_range 空值处理：main 结束统计日志中 None 输出为"（无数据）"
- v3.4 (2026-05-30): Bug修复——8项问题清理（第四轮）
  - 重构 _filter_tail_klines 返回类型：改为 list[tuple] 附带已解析时间对象，避免下游重复解析
  - 新增 _calculate_tail_metrics 时间戳去重：同一天重复时间戳保留最后一条
  - 修复 _parse_time_str 默认参数：log_on_failure 改为 True，避免静默失败风险
  - 增强 fetch_tail_trading_for_stock 日志：parsed_klines 非空但 date_groups 为空时补充 warning
  - 修复 main 全量模式断点续传：缓存中失败股票也加入拉取列表，成功后从 failed_stocks 移除
  - 优化 merge_records 性能：无新数据但有失败股票时使用快速路径，仅更新 meta
  - 提取状态常量：_STATUS_SUCCESS/_STATUS_NO_DATA/_STATUS_FAILED 替代字符串字面量
  - 修正 fetch_tail_trading_batch 日志措辞："已限制最大拉取数量"而非"测试模式限制"
- v3.3 (2026-05-30): Bug修复——8项问题清理（第三轮）
  - 修复 merge_records 短路逻辑：改为"无新数据且无失败股票"才短路返回，避免失败信息丢失
  - 提取 _parse_time_str 函数：统一时间解析逻辑，消除重复代码
  - 修复 _filter_tail_klines 日志：len(time_parts)<2 时补充 warning 日志
  - 修复 _calculate_tail_metrics 排序：过滤无法解析时间的 K 线而非用哨兵值兜底
  - 增强 fetch_tail_trading_for_stock 日志：parsed_klines 为空但 klines 非空时记录 warning
  - 修复 date_groups 构建：过滤空字符串 date，避免脏数据写入缓存
  - 补充 main 结束统计：输出累计失败股票数量
  - 增强 fetch_tail_trading_batch 日志：切片前记录原始数量，便于测试模式观察
- v3.2 (2026-05-30): Bug修复——8项问题清理（第二轮）
  - 修复 merge_records 可变默认参数：改为 None 并在函数体首行处理
  - 修复 _calculate_tail_metrics 排序逻辑：使用 datetime.time 对象替代字符串排序
  - 修复 volume 类型一致性：解析阶段直接转为整数 int(float(...))
  - 增强 fetch_tail_trading_for_stock 返回结构：区分 'success'/'no_data'/'failed' 三种状态
  - 修复 main 无新数据分支：failed_stocks 非空时仍合并并保存，避免失败信息丢失
  - 优化 main 差集计算：将 priority_codes 转为 set 避免 O(n²)
  - 增强 _filter_tail_klines 日志：时间解析失败时记录 warning 日志
  - 补充 main 增量模式日志：无断点续传时输出拉取全部股票的说明
- v3.1 (2026-05-30): Bug修复——10项问题清理
  - 修复 _filter_tail_klines 时间比较逻辑：使用 datetime.time 对象替代字符串比较
  - 修复 merge_records 默认参数：source='eastmoney_5min' → 'sina_5min'
  - 修复 main docstring："拉取历史12天" → "拉取历史10天"
  - 删除未使用常量 BATCH_SIZE（死代码清理）
  - 增强 _calculate_tail_metrics 日志：K线不足时记录debug日志
  - 增强 fetch_tail_trading_batch 统计：添加总记录数输出
  - 优化 main 无新数据处理：删除重复写入缓存的I/O操作
  - 修复 _format_sina_code：添加北交所股票代码处理（8/4开头 → bj）
  - 新增增量模式断点续传：fetch_tail_trading_batch 返回 failed_stocks，merge_records 保存到 meta，下次优先拉取
- v3.0 (2026-05-29 17:00): 数据源切换
  - 东财API（push2his.eastmoney.com）连接被拒绝，改用新浪API
  - 新浪API：http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
  - 数据量：500条（约10交易日），与东财API相当
  - 数据格式：JSON列表，每条包含 day, open, high, low, close, volume
  - 断点续传逻辑保留
- v2.3 (2026-05-29 19:00): 第七轮深度优化——断点续传
  - 新增 get_cached_stock_codes() 函数：获取缓存中已有的股票代码列表
  - 全量模式支持断点续传：检查缓存中已有的股票，只拉取缺失的股票
  - 容错优化：即使部分失败，只要有成功数据就保存（不再全部失败才退出）
  - 输出版本号同步：_OUTPUT_VERSION 更新为 '2.2'
- v2.2 (2026-05-29 18:00): 第六轮深度优化
  - 输出版本号同步：_OUTPUT_VERSION 从 '2.0' 更新为 '2.1'（遵循 Pitfall 169）
  - 异常处理精确化：main/CLI 入口删除 requests.RequestException（遵循 Pitfall 175）
  - 虚假引用删除：merge_records Note 节删除不存在的 MODULE.md 约束 #93（遵循 Pitfall 174）
- v2.1 (2026-05-29 17:00): 第五轮深度优化
  - 注释修正：第161行尾盘时段注释（14:30→14:00）
  - 异常处理修正：load_cache 捕获本地文件异常（删除 requests.RequestException）
  - 删除未使用参数：_calculate_tail_metrics 的 day_volume 参数
- v2.0 (2026-05-29 16:30): 字段结构重构
  - 尾盘时段从 14:30-15:00（7根K线）扩展到 14:00-15:00（13根K线）
  - 新增 prices/volumes 数组（13个收盘价和成交量）
  - 删除冗余字段：tail_volume、tail_volume_pct、tail_close
- v1.4 (2026-05-29 15:00): 第四轮深度优化
  - 修复变量名覆盖 bug（time → kline_time，避免覆盖导入的 time 模块）
  - 删除未使用导入（Path）
  - 异常处理精确化（fetch_tail_trading_for_stock: Exception → ValueError）
  - API常量命名规范化（EASTMONEY_API_URL → _EASTMONEY_API_URL）
  - 修复增量拉取逻辑（full=False 时若拉取失败但已有缓存，保留缓存）
- v1.3 (2026-05-29 14:00): 第三轮深度优化
  - datetime.now() 替换为 _NOW_STR 固定时间戳（第660行 main 结束日志）
  - 异常处理精确化（main/CLI入口：requests.RequestException + json.JSONDecodeError + OSError）
  - docstring Raises 修复（fetch_tail_trading_for_stock: 删除错误 Raises，添加 Note 说明；main: RuntimeError → OSError）
  - 输出版本号同步更新（_OUTPUT_VERSION = '1.2'）
  - 注释引用常量名（DEFAULT_REQUEST_DELAY 替代具体值 200ms）
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

import argparse
import json
import logging
import sys
import time
from datetime import datetime, time as datetime_time
from typing import Any

import requests

# ============================================================
# 公共模块导入（遵循 MODULE.md 约束 #51：导入在模块顶部）
# ============================================================
from common import (
    # 路径管理
    get_module_result_dir,
    # 股票筛选
    load_main_board_stock_list,
    # 缓存管理
    read_cache,
    # 日志配置
    setup_logger,
    write_cache,
)


# ============================================================
# 配置常量（遵循 MODULE.md 约束 #16）
# ============================================================

# 输出版本（遵循 MODULE.md 约束 #18）
_OUTPUT_VERSION = "3.9"  # v3.9: 修复 Pitfall 162——全量模式强制拉取所有股票

# v3.4: 状态常量（避免字符串字面量比较，提供静态约束）
_STATUS_SUCCESS = "success"
_STATUS_NO_DATA = "no_data"
_STATUS_FAILED = "failed"

# 固定时间戳（遵循 MODULE.md 约束 #17）
_NOW = datetime.now()
_NOW_ISO = _NOW.isoformat()
_NOW_STR = _NOW.strftime("%Y-%m-%d %H:%M:%S")

# 输出文件路径
_RESULT_DIR = get_module_result_dir()
_CACHE_FILE = _RESULT_DIR / "tail_trading_data.json.gz"  # 缓存文件路径（私有常量）

# 新浪API配置（v3.0）
_SINA_API_URL = "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
API_SCALE = 5  # K线类型：5分钟K线
API_DATALEN_FULL = 500  # 全量模式最大条数（约10交易日）
API_DATALEN_INCREMENTAL = 50  # 增量模式最大条数（约1天）

# 尾盘时段定义（5分钟K线）—— 使用 datetime.time 对象进行比较，避免字符串比较陷阱
TAIL_PERIOD_START_TIME = datetime_time(14, 0)  # 尾盘开始时间（v2.0: 扩展到14:00）
TAIL_PERIOD_END_TIME = datetime_time(15, 0)  # 尾盘结束时间（收盘）
TAIL_KLINE_COUNT = 13  # 尾盘K线数量（14:00-15:00共13根5分钟K线）

# 默认参数
DEFAULT_REQUEST_DELAY = 2.0  # 请求间隔（秒），v3.0: 增加到2秒避免新浪API封禁
BATCH_PAUSE = 80  # 每100个请求后停顿时间（秒），避免触发反爬

# ============================================================
# Logger 配置
# ============================================================

logger = setup_logger("fetch_tail_trading")


# ============================================================
# 时间解析辅助函数（v3.3: 统一复用，消除重复代码）
# ============================================================


def _parse_time_str(
    time_str: str,
    logger_arg: logging.Logger | None = None,
    log_on_failure: bool = True,  # v3.4: 默认值改为 True，避免静默失败风险
) -> datetime_time | None:
    """
    解析时间字符串为 datetime.time 对象

    Args:
        time_str: 时间字符串，支持格式：'HH:MM:SS', 'HH:MM', 'H:MM:SS', 'H:MM'
        logger_arg: 日志 logger
        log_on_failure: 是否在解析失败时记录 warning 日志（v3.4: 默认 True）

    Returns:
        datetime_time 对象，解析失败时返回 None

    Note:
        v3.3: 提取为模块级函数，统一 _filter_tail_klines 和 _calculate_tail_metrics 的解析逻辑
        避免重复代码和潜在的行为不一致
        v3.4: log_on_failure 默认值改为 True，由需要静默的少数调用方显式传 False
    """
    _logger = logger_arg or logger

    if not time_str:
        if log_on_failure:
            _logger.warning("时间解析失败: time_str 为空字符串")
        return None

    try:
        time_parts = time_str.split(":")
        if len(time_parts) < 2:
            if log_on_failure:
                _logger.warning("时间解析失败: time_str='%s', 时间格式不完整（少于2个部分）", time_str)
            return None

        hour = int(time_parts[0])
        minute = int(time_parts[1])
        return datetime_time(hour, minute)

    except (ValueError, IndexError) as e:
        if log_on_failure:
            _logger.warning("时间解析失败: time_str='%s', 错误=[%s]: %s", time_str, type(e).__name__, e)
        return None


# ============================================================
# 数据拉取函数
# ============================================================


def _format_sina_code(code: str) -> str:
    """
    格式化股票代码为新浪API格式

    Args:
        code: 6位股票代码

    Returns:
        新浪API格式的代码（如 sz000001, sh600000, bj430001）

    Note:
        - 沪市：以 6 开头（sh）
        - 深市：以 0、3 开头（sz）
        - 北交所：以 8、4 开头（bj）—— 新浪API北交所股票可能返回空数据
    """
    if code.startswith("6"):
        return f"sh{code}"  # 沪市
    elif code.startswith("8") or code.startswith("4"):
        return f"bj{code}"  # 北交所（北京证券交易所）
    else:
        return f"sz{code}"  # 深市（0、3开头）


def _filter_tail_klines(
    klines: list[dict[str, Any]], logger_arg: logging.Logger | None = None
) -> list[tuple[datetime_time, dict[str, Any]]]:
    """
    过滤尾盘时段的K线数据

    Args:
        klines: K线数据列表，每条包含 time, open, close, high, low, volume
        logger_arg: 日志 logger（v3.2: 新增参数用于记录解析异常）

    Returns:
        尾盘时段（14:00-15:00）的K线列表，每条为 (datetime_time, kline_dict) 元组
        v3.4: 返回类型改为 list[tuple]，附带已解析的时间对象，避免下游重复解析

    Note:
        尾盘时段共13根5分钟K线：14:00, 14:05, 14:10, 14:15, 14:20, 14:25, 14:30, 14:35, 14:40, 14:45, 14:50, 14:55, 15:00
        使用 datetime.time 对象进行比较，避免字符串字典序陷阱（如 '9:30:00' > '14:00' 为 True）
        v3.5: 时间解析失败改为汇总统计，避免高频日志淹没
        v3.6: 分别统计空字段数量和格式异常数量，便于区分数据问题根源
    """
    _logger = logger_arg or logger

    tail_klines: list[tuple[datetime_time, dict[str, Any]]] = []
    # v3.6: 分别统计空字段和格式异常，便于区分数据问题根源
    empty_field_count = 0  # time 字段为空字符串
    format_error_count = 0  # time 字段非空但格式异常

    for kline in klines:
        time_str = kline.get("time", "")

        # v3.6: 区分空字段和格式异常
        if not time_str:
            empty_field_count += 1
            continue

        # v3.5: 使用静默模式解析（log_on_failure=False），避免逐条日志
        kline_time = _parse_time_str(time_str, logger_arg=_logger, log_on_failure=False)
        if kline_time is None:
            format_error_count += 1
            continue

        # 过滤尾盘时段（14:00-15:00，包含边界）
        if TAIL_PERIOD_START_TIME <= kline_time <= TAIL_PERIOD_END_TIME:
            # v3.4: 返回 tuple，附带已解析的时间对象，避免下游重复解析
            tail_klines.append((kline_time, kline))

    # v3.6: 分别输出空字段和格式异常日志
    if empty_field_count > 0:
        _logger.warning("时间字段为空: %s 条K线（API返回缺失 time 字段）", empty_field_count)
    if format_error_count > 0:
        _logger.warning("时间格式异常: %s 条K线（time 字段非空但无法解析）", format_error_count)

    return tail_klines


def _calculate_tail_metrics(
    tail_klines: list[tuple[datetime_time, dict[str, Any]]],
    date: str = "",
    code: str = "",
    logger_arg: logging.Logger | None = None,
) -> dict[str, Any] | None:
    """
    计算尾盘指标

    Args:
        tail_klines: 尾盘K线数据列表（v3.4: 每条为 (datetime_time, kline_dict) 元组）
        date: 交易日期（用于日志）
        code: 股票代码（用于日志）
        logger_arg: 日志 logger

    Returns:
        尾盘指标字典，包含：
        - prices: 14:00-15:00 的13个收盘价（按时间升序）
        - volumes: 14:00-15:00 的13个成交量（按时间升序）
        - tail_high: 尾盘最高价
        - tail_low: 尾盘最低价

    Note:
        若尾盘K线数量不足13根，返回 None 并记录日志
        v3.4: 输入类型改为 list[tuple]，直接使用已解析的时间对象，无需重复解析
        v3.4: 新增时间戳去重逻辑（同一天重复时间戳保留最后一条）
    """
    _logger = logger_arg or logger

    kline_count = len(tail_klines)
    if kline_count < TAIL_KLINE_COUNT:
        # K线不足时记录debug日志，便于排查数据缺失原因
        _logger.debug(
            "[%s] [%s] 尾盘K线不足: 期望 %s 根, 实际 %s 根%s",
            code,
            date,
            TAIL_KLINE_COUNT,
            kline_count,
            "（可能为非交易日或半日市）" if kline_count > 0 else "（无数据）",
        )
        return None

    # v3.4: 直接使用已解析的时间对象（tuple 中第一个元素），无需重复解析
    # 按时间排序
    sorted_klines_with_time = sorted(tail_klines, key=lambda x: x[0])

    # v3.4: 时间戳去重（同一天重复时间戳保留最后一条）
    # 使用 dict 以时间为 key，后出现的覆盖前出现的（sorted 已按时间升序）
    # 但需要保留最后一条，所以反向遍历或使用最后一次出现的值
    time_to_kline: dict[datetime_time, dict[str, Any]] = {}
    for kline_time, kline_dict in sorted_klines_with_time:
        # 相同时间戳，后出现的覆盖前出现的（保留最后一条）
        time_to_kline[kline_time] = kline_dict

    # 去重后检查数量
    unique_count = len(time_to_kline)
    if unique_count != kline_count:
        _logger.warning("[%s] [%s] 发现重复时间戳: 原始 %s 根 → 去重后 %s 根", code, date, kline_count, unique_count)

    if unique_count < TAIL_KLINE_COUNT:
        _logger.warning("[%s] [%s] 去重后K线不足: 期望 %s 根, 实际 %s 根", code, date, TAIL_KLINE_COUNT, unique_count)
        return None

    # v3.7: 提取排序到分支判断之前，避免两个分支重复排序
    # v3.8: 删除冗余排序——time_to_kline 已按时间升序构建，dict 保持插入顺序（Python 3.7+）
    # 直接转为列表即可，无需再次 sorted()，与 excess_timestamps 处理逻辑一致
    sorted_unique_klines = list(time_to_kline.items())

    # v3.6: 去重后超过 13 根时截断（取前 13 条，即最早时间）
    # 确保输出数组长度严格为 TAIL_KLINE_COUNT
    # v3.6: 补充打印超量的具体时间戳，便于判断是数据异常还是 API 返回了额外的标准时间点
    if unique_count > TAIL_KLINE_COUNT:
        # v3.8: 删除冗余排序——time_to_kline.keys() 已是升序（sorted_unique_klines 已排序）
        # 直接转为列表切片即可，避免重复排序开销
        excess_timestamps = [str(t) for t in list(time_to_kline.keys())[TAIL_KLINE_COUNT:]]
        _logger.warning(
            "[%s] [%s] 去重后K线超量: 期望 %s 根, 实际 %s 根 → 截取前 %s 根（超出的时间戳: %s）",
            code,
            date,
            TAIL_KLINE_COUNT,
            unique_count,
            TAIL_KLINE_COUNT,
            excess_timestamps,
        )
        # v3.7: 截取前 TAIL_KLINE_COUNT 条（按时间升序，取最早的13根）
        sorted_unique_klines = sorted_unique_klines[:TAIL_KLINE_COUNT]

    final_klines = [kline_dict for _, kline_dict in sorted_unique_klines]

    # 提取收盘价和成交量数组
    prices = [round(kline.get("close", 0), 2) for kline in final_klines]
    volumes = [int(kline.get("volume", 0)) for kline in final_klines]

    # 计算尾盘最高价和最低价
    tail_high = round(max(kline.get("high", 0) for kline in final_klines), 2)
    tail_low = round(min(kline.get("low", 0) for kline in final_klines), 2)

    return {
        "prices": prices,
        "volumes": volumes,
        "tail_high": tail_high,
        "tail_low": tail_low,
    }


def fetch_tail_trading_for_stock(
    code: str, full: bool = False, logger_arg: logging.Logger | None = None
) -> dict[str, Any]:
    """
    拉取单只股票的尾盘数据（新浪API）

    Args:
        code: 6位股票代码
        full: 全量模式（拉取历史10天），否则增量模式（拉取最新一天）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）

    Returns:
        包含以下键的字典：
        - records: 尾盘数据记录列表，每条包含 date, asset, prices, volumes, tail_high, tail_low
        - status: 拉取状态，取值：
            - 'success': 请求成功且有有效尾盘数据
            - 'no_data': 请求成功但无有效尾盘数据（K线不足或无数据）
            - 'failed': 请求失败（网络异常、API异常等）

    Note:
        v3.2: 返回结构改为字典，区分"请求成功但无数据"与"请求失败"两种状态
        避免无数据股票被无限重试（no_data 状态不应计入 failed_stocks）
    """
    _logger = logger_arg or logger

    # 格式化股票代码（新浪API格式）
    sina_code = _format_sina_code(code)

    # 构建API参数
    params = {
        "symbol": sina_code,
        "scale": API_SCALE,
        "datalen": API_DATALEN_FULL if full else API_DATALEN_INCREMENTAL,
    }

    try:
        # 发送请求（新浪API不需要特殊Session）
        response = requests.get(_SINA_API_URL, params=params, timeout=10)

        if response.status_code != 200:
            _logger.warning("[%s] API返回状态码异常: %s", code, response.status_code)
            return {"records": [], "status": _STATUS_FAILED}  # v3.4: 使用常量

        # 解析JSON数据
        klines = response.json()

        # 类型校验：应为列表
        if not isinstance(klines, list):
            _logger.warning("[%s] API返回数据类型异常: %s", code, type(klines).__name__)
            return {"records": [], "status": _STATUS_FAILED}  # v3.4: 使用常量

        if not klines:
            _logger.debug("[%s] 无K线数据", code)
            return {"records": [], "status": _STATUS_NO_DATA}  # v3.4: 使用常量

        # 解析K线数据（新浪API格式：day, open, high, low, close, volume）
        # day 格式：'2026-05-29 14:45:00'
        parsed_klines = []
        for kline in klines:
            day_str = kline.get("day", "")
            if not day_str:
                continue

            # 从 day 字段分离日期和时间
            # v3.8: 使用 split(maxsplit=1) 确保按任意空白分割且最多切两段
            # 避免 '2026-05-29  14:45:00'（双空格）时 parts[1] 为空字符串
            parts = day_str.split(maxsplit=1)
            if len(parts) < 2 or not parts[1]:
                continue

            raw_date = parts[0]
            # v3.8: kline_time 规范化截取，只保留 HH:MM:SS 部分
            # 去掉微秒等后缀（如 '14:45:00.123' → '14:45:00'），与 tuple 中 datetime_time 对象语义一致
            kline_time = parts[1].split(".")[0]

            # v3.6: date 字段格式规范化，避免月份不补零导致重复记录
            # Python strptime('%Y-%m-%d') 已支持单数字月日（如 '2026-5-29'）
            # 删除冗余的手动解析分支（v3.5 遗留的死代码）
            try:
                normalized_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            except ValueError:
                _logger.warning("[%s] date 格式异常无法规范化: '%s', 跳过该K线", code, raw_date)
                continue

            # v3.6: 单条 K 线字段解析改为独立 try-except，单条失败不影响其他 K 线
            try:
                parsed_kline = {
                    "date": normalized_date,
                    "time": kline_time,
                    "open": float(kline.get("open", 0)),
                    "close": float(kline.get("close", 0)),
                    "high": float(kline.get("high", 0)),
                    "low": float(kline.get("low", 0)),
                    "volume": int(float(kline.get("volume", 0))),
                }
                parsed_klines.append(parsed_kline)
            except (ValueError, TypeError) as e:
                _logger.warning(
                    "[%s] 单条K线字段解析失败（day='%s'）: [%s]: %s, 跳过该K线",
                    code,
                    day_str,
                    type(e).__name__,
                    e,
                )
                continue

        # v3.3: parsed_klines 为空但 klines 非空时记录 warning（解析全部失败而非 API 无数据）
        if not parsed_klines and klines:
            _logger.warning("[%s] API返回 %s 条K线但全部解析失败（day字段可能为空或格式异常）", code, len(klines))
            return {"records": [], "status": _STATUS_NO_DATA}  # v3.4: 使用常量

        # 按日期分组（v3.3: 过滤空字符串 date，避免脏数据写入缓存）
        date_groups: dict[str, list[dict[str, Any]]] = {}
        for kline in parsed_klines:
            date = kline.get("date", "")
            if not date:  # v3.3: 过滤空字符串 date
                continue
            if date not in date_groups:
                date_groups[date] = []
            date_groups[date].append(kline)

        # v3.7: 此检查为边界防御，正常流程不可达
        # v3.6 date 规范化后，parsed_klines 非空时 date 字段必已规范化
        # 此处保留以防未来逻辑变更（如 date 规范化被移除）
        if parsed_klines and not date_groups:
            _logger.warning(
                "[%s] parsed_klines 有 %s 条但 date_groups 为空（date 字段全部为空字符串，已过滤）——边界防御触发",
                code,
                len(parsed_klines),
            )
            return {"records": [], "status": _STATUS_NO_DATA}

        # 计算每日尾盘指标
        records = []
        for date, day_klines in date_groups.items():
            # 过滤尾盘K线（v3.2: 传入 logger_arg）
            tail_klines = _filter_tail_klines(day_klines, logger_arg=_logger)

            # 计算尾盘指标
            tail_metrics = _calculate_tail_metrics(tail_klines, date=date, code=code, logger_arg=_logger)

            if tail_metrics:
                records.append({"date": date, "asset": code, **tail_metrics})

        # v3.2: 区分"有有效数据"与"无有效数据"
        if records:
            _logger.debug("[%s] 获取 %s 天尾盘数据", code, len(records))
            return {"records": records, "status": _STATUS_SUCCESS}  # v3.4: 使用常量
        else:
            _logger.debug("[%s] 无有效尾盘数据（K线不足）", code)
            return {"records": [], "status": _STATUS_NO_DATA}  # v3.4: 使用常量

    except requests.RequestException as e:
        _logger.warning("[%s] 网络请求失败: [%s]: %s", code, type(e).__name__, e)
        return {"records": [], "status": _STATUS_FAILED}  # v3.4: 使用常量
    except json.JSONDecodeError as e:
        _logger.warning("[%s] JSON解析失败: [%s]: %s", code, type(e).__name__, e)
        return {"records": [], "status": _STATUS_FAILED}  # v3.4: 使用常量
    # v3.7: 此 except 为非预期异常兜底，正常情况下不应触发
    # 单条 K 线解析错误已在循环内独立 try-except 处理
    # 此处仅捕获网络层/JSON层之外的非预期异常（如 response.json() 内部错误）
    except (ValueError, TypeError) as e:  # v3.5: 新增 TypeError，覆盖 float(None) 等情况
        _logger.warning("[%s] 数据解析失败（非预期异常）: [%s]: %s", code, type(e).__name__, e)
        return {"records": [], "status": _STATUS_FAILED}  # v3.4: 使用常量


def fetch_tail_trading_batch(
    stock_codes: list[str], full: bool = False, max_stocks: int = 0, logger_arg: logging.Logger | None = None
) -> dict[str, Any]:
    """
    批量拉取尾盘数据

    Args:
        stock_codes: 股票代码列表
        full: 全量模式（拉取历史10天）
        max_stocks: 最大股票数（用于测试，0为不限制）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）

    Returns:
        包含以下键的字典：
        - records: 尾盘数据记录列表
        - failed_stocks: 拉取失败的股票代码列表

    Note:
        - 请求间隔 DEFAULT_REQUEST_DELAY 秒，避免限流
        - 每100股打印进度日志
    """
    _logger = logger_arg or logger

    # v3.3: 切片前记录原始数量，便于测试模式下看到原始列表规模
    original_count = len(stock_codes)

    # 限制股票数（用于测试）
    if max_stocks > 0:
        stock_codes = stock_codes[:max_stocks]
        # v3.4: 日志措辞修正——"已限制最大拉取数量"而非"测试模式限制"
        _logger.info("已限制最大拉取数量: 原始 %s 支 → 实际拉取 %s 支", original_count, len(stock_codes))

    total_stocks = len(stock_codes)
    _logger.info("开始拉取尾盘数据: %s 支股票", total_stocks)
    _logger.info("模式: %s", "全量（历史10天）" if full else "增量（最新一天）")

    all_records = []
    failed_stocks = []
    # v3.7: 分别统计三种状态，语义更准确
    success_count = 0  # 有有效尾盘数据
    no_data_count = 0  # 请求成功但无有效尾盘数据
    failed_count = 0  # 请求失败

    # 新浪API不需要特殊Session，直接逐个请求
    for idx, code in enumerate(stock_codes):
        # 请求间隔（遵循 MODULE.md 约束 #78）
        if idx > 0:
            time.sleep(DEFAULT_REQUEST_DELAY)

        # 拉取单股数据（v3.2: 返回字典格式）
        result = fetch_tail_trading_for_stock(code=code, full=full, logger_arg=_logger)

        # v3.7: 使用 .get() 替代直接字典访问，避免 KeyError
        # v3.7: 分别统计三种状态
        status = result.get("status")
        if status is None:
            _logger.warning("[%s] 返回结构异常: status 字段缺失", code)
            failed_stocks.append(code)
            failed_count += 1
        elif status == _STATUS_SUCCESS:
            # v3.8: 使用 .get() or [] 避免 None 值，并校验类型
            records = result.get("records") or []
            if not isinstance(records, list):
                _logger.warning("[%s] records 类型异常: %s", code, type(records).__name__)
                failed_stocks.append(code)
                failed_count += 1
            else:
                all_records.extend(records)
                success_count += 1
        elif status == _STATUS_FAILED:
            failed_stocks.append(code)
            failed_count += 1
        elif status == _STATUS_NO_DATA:
            no_data_count += 1
        # v3.8: 补充 else 分支处理非预期 status 值，避免静默忽略
        else:
            _logger.warning("[%s] 返回非预期 status 值: '%s'", code, status)
            failed_stocks.append(code)
            failed_count += 1
        # _STATUS_NO_DATA 状态：请求成功但无有效尾盘数据，不计入 failed_stocks

        # 进度日志（每100股）
        if (idx + 1) % 100 == 0:
            progress_pct = (idx + 1) / total_stocks * 100
            _logger.info("进度: %s/%s (%.1f%%)", idx + 1, total_stocks, progress_pct)

            # 每批完成后停顿（避免触发反爬）
            if idx + 1 < total_stocks:  # 不是最后一批
                _logger.info("本批完成，停顿 %s 秒...", BATCH_PAUSE)
                time.sleep(BATCH_PAUSE)

    # v3.8: 统计日志补充 total_stocks 总数，读者可直观验证三项之和
    _logger.info(
        "拉取完成: %s/%s 有数据, %s/%s 无数据, %s/%s 失败",
        success_count,
        total_stocks,
        no_data_count,
        total_stocks,
        failed_count,
        total_stocks,
        f", 总记录数 {len(all_records)} 条",
    )
    if failed_stocks:
        _logger.warning("失败股票（前10支）: %s", failed_stocks[:10])

    # v3.1: 返回包含 records 和 failed_stocks 的字典，支持增量模式断点续传
    return {
        "records": all_records,
        "failed_stocks": failed_stocks,
    }


# ============================================================
# 缓存管理函数
# ============================================================


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any] | None:
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
            _logger.warning("缓存数据类型异常: %s", type(data).__name__)
            return None

        _logger.info("加载缓存成功: %s 条记录", len(data.get("data", [])))
        return data

    except (json.JSONDecodeError, OSError) as e:
        _logger.warning("加载缓存失败: [%s]: %s", type(e).__name__, e)
        return None


def get_cached_stock_codes(existing_data: dict[str, Any] | None, logger_arg: logging.Logger | None = None) -> set[str]:
    """
    获取缓存中已有的股票代码列表

    Args:
        existing_data: 现有缓存数据
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）

    Returns:
        已有股票代码集合

    Note:
        用于断点续传：全量模式下只拉取缺失的股票
    """
    _logger = logger_arg or logger

    if not existing_data:
        return set()

    records = existing_data.get("data", [])
    if not records:
        return set()

    # 提取所有已有的股票代码
    cached_codes = set()
    for record in records:
        asset = record.get("asset")
        if asset:
            cached_codes.add(asset)

    _logger.info("缓存中已有 %s 支股票的数据", len(cached_codes))
    return cached_codes


def save_cache(data: dict[str, Any], logger_arg: logging.Logger | None = None) -> None:
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
        _logger.info("保存缓存成功: %s", _CACHE_FILE)

    except OSError as e:
        _logger.error("保存缓存失败: [%s]: %s", type(e).__name__, e)
        raise


def merge_records(
    existing_data: dict[str, Any] | None,
    new_records: list[dict[str, Any]],
    failed_stocks: list[str] | None = None,  # v3.2: 可变默认参数改为 None
    source: str = "sina_5min",  # v3.0: 数据源切换为新浪API
    logger_arg: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    合并新旧数据并去重

    Args:
        existing_data: 现有缓存数据
        new_records: 新拉取的数据记录
        failed_stocks: 本次拉取失败的股票代码列表（用于增量模式断点续传）
        source: 数据源标识
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）

    Returns:
        合并后的数据字典

    Note:
        - 去重策略：以 (date, asset) 作为 key
        - 数据源合并逻辑：优先使用现有缓存的 source，若新旧数据源不同则标记为 'mixed'
        - failed_stocks 合并逻辑：与现有缓存的 failed_stocks 合并，成功拉取的股票从中移除
    """
    _logger = logger_arg or logger

    # v3.8: 防御性 None 处理顺序与函数签名参数顺序对应（new_records 在 failed_stocks 前面）
    if new_records is None:
        new_records = []

    # v3.2: 可变默认参数标准处理
    if failed_stocks is None:
        failed_stocks = []

    # v3.3: 修复短路逻辑——"无新数据且无失败股票"才短路返回，否则继续合并失败列表
    if not new_records and not failed_stocks:
        if existing_data:
            _logger.info("无新数据且无失败股票，保留现有缓存")
            return existing_data
        else:
            _logger.warning("无数据且无失败股票，返回空结构")
            return {
                "meta": {
                    "generated_at": _NOW_ISO,
                    "source": source,
                    "n_days": 0,
                    "n_assets": 0,
                    "date_range": {"start": None, "end": None},
                    "last_updated": datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),  # 实际保存时间（遵循 MODULE.md 约束 #106）
                    "version": _OUTPUT_VERSION,
                    "failed_stocks": [],  # 无失败股票
                },
                "data": [],
            }

    # v3.4: 快速路径——"无新数据但有失败股票"时，仅更新 meta 中的 failed_stocks
    # 避免重建整个 record_map，减少性能开销
    if not new_records and failed_stocks and existing_data:
        _logger.info("无新数据但有失败股票，仅更新 meta.failed_stocks（快速路径）")
        existing_meta = existing_data.get("meta")
        existing_records = existing_data.get("data", [])

        # 合并失败股票列表
        existing_failed_stocks = set(existing_meta.get("failed_stocks", [])) if existing_meta else set()
        final_failed_stocks = existing_failed_stocks.union(set(failed_stocks))
        final_failed_stocks_list = sorted(final_failed_stocks)

        if final_failed_stocks_list:
            _logger.info("失败股票累计: %s 支（下次将优先拉取）", len(final_failed_stocks_list))

        # v3.5: 直接构建新返回字典，消除浅拷贝隐患
        # 'data' 字段直接引用 existing_data['data']（不修改，无需复制）
        # 'meta' 字段重新构建包含所有字段的新字典
        new_meta = {
            "generated_at": existing_meta.get("generated_at", _NOW_ISO) if existing_meta else _NOW_ISO,
            "source": existing_meta.get("source", source) if existing_meta else source,
            "n_days": existing_meta.get("n_days", 0) if existing_meta else 0,
            "n_assets": existing_meta.get("n_assets", 0) if existing_meta else 0,
            # v3.6: date_range 是嵌套字典 {'start': ..., 'end': ...}
            # 此处直接引用 existing_meta['date_range'] 是有意的只读引用：
            # 1. 快速路径下不修改 date_range 内容
            # 2. 外部代码也不会修改返回值中的 date_range
            # 3. 若未来需要修改 date_range，应改为 dict(...) 浅层复制
            "date_range": existing_meta.get("date_range", {"start": None, "end": None})
            if existing_meta
            else {"start": None, "end": None},
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": _OUTPUT_VERSION,
            "failed_stocks": final_failed_stocks_list,
        }
        return {
            "meta": new_meta,
            "data": existing_records,  # 直接引用，不复制（数据不变）
        }

    # 正常合并流程
    existing_records = []
    existing_meta = None
    if existing_data:
        existing_records = existing_data.get("data", [])
        existing_meta = existing_data.get("meta")

    # v3.7: "无新数据、有失败股票、无现有缓存"路径补充日志
    # 此路径理论上不应触发（应在快速路径处理），但保留防御性处理
    if not new_records and failed_stocks and not existing_data:
        _logger.warning("无现有缓存且无新数据，新建空结构并记录失败股票（边界情况）")

    all_records = existing_records + new_records

    # 去重（以 (date, asset) 作为 key）
    record_map: dict[tuple[str, str], dict[str, Any]] = {}
    for record in all_records:
        # 防御性编程（遵循 MODULE.md 约束 #104）
        date_val = record.get("date")
        asset_val = record.get("asset")
        if date_val and asset_val:
            key = (date_val, asset_val)
            record_map[key] = record

    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x.get("date", ""), x.get("asset", "")))

    # 提取元信息（过滤 None 值）
    unique_dates = sorted(set(r.get("date") for r in merged_records if r.get("date")))  # noqa: C401
    unique_assets = sorted(set(r.get("asset") for r in merged_records if r.get("asset")))  # noqa: C401

    # 数据源合并逻辑：优先使用现有缓存的 source，若新旧数据源不同则标记为 'mixed'
    final_source = source
    if existing_meta:
        existing_source = existing_meta.get("source", source)
        if existing_source != source:
            final_source = "mixed"

    # generated_at 语义：数据首次生成时间（遵循 MODULE.md 约束 #98）
    generated_at = _NOW_ISO
    if existing_meta:
        generated_at = existing_meta.get("generated_at", _NOW_ISO)

    # v3.1: failed_stocks 合并逻辑
    # 1. 获取现有缓存的失败股票列表
    existing_failed_stocks = set()
    if existing_meta:
        existing_failed_stocks = set(existing_meta.get("failed_stocks", []))

    # 2. 合并本次失败的股票
    final_failed_stocks = existing_failed_stocks.union(set(failed_stocks))

    # 3. 从失败列表中移除本次成功拉取的股票（有新记录的股票）
    successful_stocks = set(r.get("asset") for r in new_records if r.get("asset"))  # noqa: C401
    final_failed_stocks = final_failed_stocks.difference(successful_stocks)

    # 转为排序后的列表（便于调试）
    final_failed_stocks_list = sorted(final_failed_stocks)

    if final_failed_stocks_list:
        _logger.info("失败股票累计: %s 支（下次将优先拉取）", len(final_failed_stocks_list))

    return {
        "meta": {
            "generated_at": generated_at,
            "source": final_source,
            "n_days": len(unique_dates),
            "n_assets": len(unique_assets),
            "date_range": {
                "start": unique_dates[0] if unique_dates else None,
                "end": unique_dates[-1] if unique_dates else None,
            },
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 实际保存时间（遵循 MODULE.md 约束 #106）
            "version": _OUTPUT_VERSION,
            "failed_stocks": final_failed_stocks_list,  # v3.1: 新增失败股票列表
        },
        "data": merged_records,
    }


# ============================================================
# 主函数
# ============================================================


def main(full: bool = False, max_stocks: int = 0, logger_arg: logging.Logger | None = None) -> bool:
    """
    主函数：拉取尾盘数据

    Args:
        full: 全量模式（拉取历史10天），否则增量模式（拉取最新一天）
        max_stocks: 最大股票数（用于测试，0为不限制）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 #77）

    Raises:
        OSError: 缓存文件写入失败时抛出

    Note:
        返回值仅用于 CLI 入口判断执行状态，调用方不应依赖返回值做业务判断
    """
    _logger = logger_arg or logger

    _logger.info("=" * 60)
    _logger.info("[%s] 开始拉取尾盘数据", _NOW_STR)
    _logger.info("=" * 60)
    # v3.8: 拆分版本号日志，语义更清晰——API版本与脚本版本分开
    _logger.info("数据源: 新浪财经5分钟K线 API")
    _logger.info("脚本版本: v%s", _OUTPUT_VERSION)
    _logger.info("尾盘时段: 14:00-15:00（共13根5分钟K线）")
    _logger.info("缓存路径: %s", _CACHE_FILE)

    # Step 1: 加载股票列表
    try:
        stock_list = load_main_board_stock_list(logger=_logger)
        if not stock_list:
            _logger.error("股票列表加载失败")
            return False

        # load_main_board_stock_list 已筛选主板股票并剔除 ST
        # 直接提取股票代码
        valid_codes = [s.get("code", "") for s in stock_list if s.get("code")]

        _logger.info("有效股票数: %s 支", len(valid_codes))

    except (json.JSONDecodeError, OSError) as e:
        _logger.error("加载股票列表失败: [%s]: %s", type(e).__name__, e)
        return False

    # Step 2: 加载现有缓存（全量模式和增量模式都需要）
    existing_data = load_cache(logger_arg=_logger)

    # Step 3: 计算需要拉取的股票代码
    # v3.4: 获取缓存中的失败股票列表（全量模式和增量模式都需要）
    existing_meta = existing_data.get("meta") if existing_data else None
    cached_failed_stocks = existing_meta.get("failed_stocks", []) if existing_meta else []

    if full:
        # v3.9: 全量模式强制拉取所有有效股票
        # 修复 Pitfall 162：原逻辑只检查股票完整性，不检查日期完整性
        # 用户指定 --full 参数时，应执行真正的全量拉取，而非跳过
        # 即使缓存中有所有股票数据，日期可能不完整（如06-01、06-02缺失）
        codes_to_fetch = valid_codes

        cached_codes_count = len(get_cached_stock_codes(existing_data, logger_arg=_logger))
        _logger.info("全量模式: 拉取所有 %s 支股票（缓存已有 %s 支）", len(valid_codes), cached_codes_count)
    else:
        # v3.1: 增量模式断点续传——优先拉取上次失败的股票
        # v3.4: existing_meta 和 cached_failed_stocks 已在 Step 3 开头统一获取

        if cached_failed_stocks:
            # v3.2: 优化差集计算，将 priority_codes 转为 set 避免 O(n²)
            valid_codes_set = set(valid_codes)
            priority_codes = [code for code in cached_failed_stocks if code in valid_codes_set]
            priority_set = set(priority_codes)
            other_codes = [code for code in valid_codes if code not in priority_set]
            codes_to_fetch = priority_codes + other_codes  # 失败股票优先

            _logger.info("增量模式断点续传: 优先拉取 %s 支失败股票", len(priority_codes))
        else:
            # v3.2: 补充日志说明（与有断点续传时对称）
            _logger.info("增量模式: 拉取全部 %s 支股票的最新数据", len(valid_codes))
            codes_to_fetch = valid_codes

    # Step 4: 批量拉取数据（v3.1: 返回字典格式）
    # v3.8: 全量模式下失败股票也拉全量历史（full=True），以确保数据完整性
    # 虽然 cached_failed_valid 已有历史数据，但增量拉取可能导致数据不完整
    # merge_records 的去重逻辑会消除重复记录，不会产生冗余
    batch_result = fetch_tail_trading_batch(
        stock_codes=codes_to_fetch, full=full, max_stocks=max_stocks, logger_arg=_logger
    )

    new_records = batch_result.get("records")
    failed_stocks = batch_result.get("failed_stocks")

    # v3.6: 验证 batch_result 返回结构完整性
    # v3.7: 修正日志表达式——正确反映实际类型
    if new_records is None or failed_stocks is None:
        _logger.error(
            "batch_result 结构异常: records=%s, failed_stocks=%s",
            "None" if new_records is None else type(new_records).__name__,
            "None" if failed_stocks is None else type(failed_stocks).__name__,
        )
        return False

    # 数据拉取结果处理（容错优化：只要有数据就保存）
    # v3.2: 即使无新数据，failed_stocks 非空时仍需合并并保存，避免失败信息丢失
    if not new_records and not failed_stocks:
        if existing_data:
            # merge_records 已有短路逻辑：无新数据时返回 existing_data
            # 此处无需重复写入缓存，直接返回即可
            _logger.info("本次拉取未获取新数据，且无失败股票，保留现有缓存（无需重新写入）")
            return True
        else:
            _logger.error("未获取到任何数据，且无现有缓存")
            return False

    # v3.2: 即使 new_records 为空但 failed_stocks 非空，仍需合并失败列表
    # v3.8: 记录合并前记录数，用于计算本次新增
    prev_count = len(existing_data.get("data", [])) if existing_data else 0
    # Step 5: 合并去重（v3.1: 传入 failed_stocks）
    merged_data = merge_records(
        existing_data=existing_data,
        new_records=new_records,
        failed_stocks=failed_stocks,  # v3.1: 新增参数
        source="sina_5min",  # v3.0: 数据源改为新浪
        logger_arg=_logger,
    )

    # Step 6: 保存缓存
    save_cache(merged_data, logger_arg=_logger)

    # 输出统计
    meta = merged_data["meta"]
    _logger.info("=" * 60)
    _logger.info("[%s] 尾盘数据拉取完成", _NOW_STR)
    _logger.info("=" * 60)
    # v3.5: date_range 为 None 时输出"（无数据）"替代 "None ~ None"
    date_start = meta["date_range"]["start"]
    date_end = meta["date_range"]["end"]
    if date_start is None or date_end is None:
        _logger.info("日期范围: （无数据）")
    else:
        _logger.info("日期范围: %s ~ %s", date_start, date_end)
    _logger.info("交易日数: %s", meta["n_days"])
    _logger.info("股票数量: %s", meta["n_assets"])
    # v3.8: 补充本次新增记录数，便于评估增量效果
    new_record_count = len(merged_data["data"]) - prev_count
    _logger.info("本次新增记录: %s 条", new_record_count)
    _logger.info("总记录数: %s", len(merged_data["data"]))
    # v3.3: 补充 failed_stocks 数量输出
    _logger.info("累计失败股票: %s 支", len(meta.get("failed_stocks", [])))

    return True


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    # CLI 入口 logger 设置（遵循 PROJECT.md 日志规范）
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    cli_logger = logging.getLogger("fetch_tail_trading.cli")

    parser = argparse.ArgumentParser(description="尾盘数据拉取")
    parser.add_argument("--full", action="store_true", help="全量拉取（不使用缓存）")
    parser.add_argument("--max-stocks", type=int, default=0, help="最大股票数（用于测试，0为不限制）")
    parser.add_argument("--test", action="store_true", help="测试模式（只拉取10支股票）")

    args = parser.parse_args()

    # 测试模式
    max_stocks = args.max_stocks
    if args.test:
        max_stocks = 10
        cli_logger.info("测试模式：只拉取10支股票")

    try:
        success = main(full=args.full, max_stocks=max_stocks, logger_arg=cli_logger)

        if not success:
            sys.exit(1)

    except (json.JSONDecodeError, OSError) as e:
        cli_logger.error("执行失败: [%s]: %s", type(e).__name__, e)
        sys.exit(1)
