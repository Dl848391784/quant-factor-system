#!/usr/bin/env python3
"""
财务指标数据拉取脚本

从 akshare (同花顺) 拉取所有股票的财务摘要数据，缓存为 JSON。
因子计算所需字段：净资产收益率、净利润同比增长率、基本每股收益 等。

数据源: akshare stock_financial_abstract_ths（同花顺财务摘要）
输出路径: data_fetchers/result/financial_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v1.0 (2026-06-12): 初始版本
  - akshare stock_financial_abstract_ths 数据源（同花顺财务摘要）
  - 增量拉取：仅拉取缓存中缺失的股票
  - 提取关键字段：roe, diluted_roe, net_profit_growth_yoy, basic_eps, revenue_growth_yoy
  - 原子性写入缓存
- v1.0b (2026-06-12): 数据源切换
  - stock_financial_analysis_indicator (东财) → stock_financial_abstract_ths (同花顺)
  - 原因: 东财API返回 AttributeError('NoneType' object has no attribute 'find')
  - 同花顺数据源: 更稳定, 102-121行×22-25列, 含ROE/EPS/净利润增长率
- v1.0c (2026-06-15): 5 项缺陷修复
  - Fix 1: _QUARTER_ANNUALIZE_FACTOR.get(month, 1.0) 静默兜底 → 无效月份 warning + annualized_eps 置 None
  - Fix 2: _parse_percentage 文档约定数据源单位（百分数形式 vs 小数形式），集成测试断言输出范围
  - Fix 3: 缓存结构 list→dict（以股票代码为 key）+ meta.last_full_fetch_date + 超过 90 天触发全量拉取
  - Fix 4: fetch_financial_data_for_stock 返回 None=异常 / []=空数据，main 分别计数 failed/empty
  - Fix 5: _FINANCIAL_FIELD_MAP else 分支 isinstance(raw_val, float) → 统一 pd.isna 兼容 numpy 标量
- v1.0d (2026-06-15): 4 项缺陷修复
  - Fix 1: 缓存结构 list→dict 已在 v1.0c 完成，本次确认无需额外修改
  - Fix 2: 检查点写入 — 每 100 只股票写一次缓存，防崩溃数据丢失（_CHECKPOINT_INTERVAL）
  - Fix 3: 空数据日志 debug→info + 去前导空格
  - Fix 4: 进度日志改用 fetch_count（实际请求次数），跳过率高时也能正常触发
  - Fix 5: write_gzip_cache 后补充写入确认日志（路径 + 股票数 + 记录数）
- v1.0e (2026-06-15): 5 项缺陷修复
  - Fix 1: load_cache 日志 len(dict) 显示 key 数而非记录数 → 按类型分别计算
  - Fix 2: 检查点写入改用浅拷贝 {**stock_data, **new_stock_data}，不提前 mutate stock_data
  - Fix 3: _parse_percentage/_parse_numeric_with_unit 统一 pd.isna 前置检查，消除对 numpy 继承关系的隐式依赖
  - Fix 4: _parse_report_date 增加 pd.isnull 前置检查，防 pd.NaT 漏判为字符串 "NaT"
  - Fix 5: 年化 EPS split+int 用 try/except 包裹，格式异常时 warning 并置 None
- v1.0f (2026-06-15): 5 项缺陷修复
  - Fix 1: 全量模式 API 失败股票记录 stale_codes 写入 meta，供下次优先重拉
  - Fix 2: fetch_financial_data_for_stock 增加 429 限流检测 + 指数退避重试（最多3次）
  - Fix 3: 进度日志去掉多余的 fetch_count > 1 条件（1 % 50 != 0 本不触发）
  - Fix 4: 维护 total_new_count 计数器替换 len(new_stock_data)，避免检查点 clear 后日志失真
  - Fix 5: 旧格式迁移补充统计日志（list 条数 → dict 股票数/记录数）+ asset 为空 warning 计数
- v1.0g (2026-06-15): 5 项缺陷修复
  - Fix 1: _is_rate_limit_error 删除无效的 "429" in exc_name 条件（类名不含数字）
  - Fix 2: 删除 for-else 冗余分支（循环体内已处理所有路径）
  - Fix 3: _parse_percentage/_parse_numeric_with_unit 增加 bool 子类拦截（numpy.bool_(False) 不被 int 分支误命中）
  - Fix 4: 检查点写入删除永远为真的 fetch_count > 0 冗余条件
  - Fix 5: load_cache 空结构返回 {"data": {}} 与新格式一致，避免触发误迁移日志
- v1.0h (2026-06-15): 4 项缺陷修复
  - Fix 1: 增量模式读取 meta.stale_codes 强制重拉失败股票（否则旧数据导致永远跳过）
  - Fix 2: meta 时间戳改用 dt_cls.now() 而非模块级 _NOW（跨日运行时间漂移）
  - Fix 3: 进度日志分母预计算 codes_to_fetch 固定值（避免随 skipped 动态变化）
  - Fix 4: 失败日志补充异常响应摘要 [响应摘要: ...]，帮助判断未识别限流
- v1.0i (2026-06-15): 5 项缺陷修复
  - Fix 1: 失败日志删除冗余 str(e)[:80]，只保留一份较长截断改标签为"异常信息"
  - Fix 2: _is_rate_limit_error 删除 HTTPError 宽泛类名匹配（400/500 也会抛 HTTPError），仅保留 TooManyRequests
  - Fix 3: codes_to_fetch 改为遍历 all_codes 统计与实际跳过逻辑一致（含废弃股票代码场景）
  - Fix 4: _parse_percentage/_parse_numeric_with_unit val is False 冗余→由 isinstance(bool) 统一处理
  - Fix 5: _parse_report_date str 分支增加 YYYY-MM-DD 正则校验，不符合格式返回 None + warning
- v1.0j (2026-06-15): 4 项缺陷修复
  - Fix 1: 增量模式成功重拉的 stale 股票从 meta.stale_codes 移除（否则永远残留）
  - Fix 2: 检查点写入取消浅拷贝 {**stock_data, **new_stock_data}，先 update 再直接写 stock_data
  - Fix 3: Step 3 日志改为"股票总数/待请求/将跳过"三维信息，与 codes_to_fetch 一致
  - Fix 4: 全量模式+stale_codes_from_cache 非空时补充 info 日志说明将自动覆盖
-v1.0k (2026-06-15): 5 项缺陷修复
  - Fix 1: _parse_report_date str 分支增加 datetime.date.fromisoformat 日期有效性验证（"2024-02-31" 通过正则但不是合法日期）
  - Fix 2: _parse_report_date 兜底分支处理 pd.Timestamp（.strftime 格式化）+ 正则校验（杜绝不规范的 "YYYY-MM-DD HH:MM:SS" 返回）
  - Fix 3: 检查点 clear 后 final_stale 计算丢失前批成功码 → 新增 successfully_fetched_codes 集合跨检查点累积
  - Fix 4: _is_rate_limit_error 关键词 "限制" 过于宽泛 → "请求频率限制" / "访问频率"
  - Fix 5: fetch_financial_data_for_stock 删除 df=pd.DataFrame() 初始化，改用 for-else 结构确保 df 只在成功 break 后使用
- v1.0l (2026-06-15): 4 项缺陷修复
  - Fix 1: stale_codes_from_cache 与 all_codes 取交集，过滤已退市/改代码的废弃股票（避免无效请求和 codes_to_fetch 分母虚增）
  - Fix 2: _CHECKPOINT_INTERVAL 100→500，减少全量序列化 stock_data 的 I/O 开销（每次检查点序列化规模与最终写入相当）
  - Fix 3: 调用方 warning 文案"格式无效"→"不符合YYYY-MM-DD格式或非合法日期"（明确区分正则不匹配 vs 日期非法）
  - Fix 4: final_stale 计算改用 successfully_fetched_codes（仅本次请求成功的），成功重拉计数不再虚报历史已有数据
- v1.0m (2026-06-16): 7 项缺陷修复（死代码清理 + 语义/日志/统计修正）
  - Fix 1: _FINANCIAL_FIELD_MAP 字段提取循环 else 分支删除（6 个 key 已被 if/elif 全覆盖，分支死代码）
  - Fix 2: _parse_report_date pd.Timestamp 独立分支删除（pd.Timestamp 是 datetime.date 子类，已被上方分支优先捕获，永远不可达）
  - Fix 3: 年化 EPS 条件 `eps != 0` 移除（EPS == 0 为有效盈亏平衡值，年化结果应为 0 而非 None）
  - Fix 4: fetch_financial_data_for_stock for-else else 块删除（最后一次重试 attempt < _RATE_LIMIT_RETRIES 为 False 必走 return None，else 不可达）
  - Fix 5: 进度日志移至 result 处理之后（原位置在 fetch_financial_data_for_stock 调用前打印，统计数字比已请求次数少 1）
  - Fix 6: 检查点行内注释 "每 100 只" → "每 500 只"，与常量 _CHECKPOINT_INTERVAL=500 对齐
  - Fix 7: 增量模式失败码（含非缓存 code）统一记录到 stale_codes，final_stale = (上次 stale - 本次成功重拉) ∪ 本次新失败，提升日志可观测性
- v1.0n (2026-06-16): 6 项缺陷修复（运行时守卫策略 + 解析语义收紧 + 死代码清理）
  - Fix 1: assert df is not None → if df is None: return None（生产代码避免 -O 优化跳过 + AssertionError 不友好）
  - Fix 2: _is_rate_limit_error 中文/英文关键词分桶（中文不走 lower 避免无意义处理，英文用 casefold）
  - Fix 3: load_cache dict 格式日志同时打印股票数 + 记录数（与 main "缓存已有 N 只股票" 维度对齐）
  - Fix 4: _parse_percentage int/float 分支合并 + 显式 docstring 标注 int 兼容性兜底语义
  - Fix 5: _parse_numeric_with_unit 不再静默 strip 百分号，遇到 % 返回 None + warning（防止 "4.21%亿" 误解析为 4.21e8）
  - Fix 6: all_codes 用 dict.fromkeys 保序去重（消除重复 code 在 successfully_fetched_codes / 检查点重复请求的潜在风险）
  - Fix 8: 删除从未引用的 _NOW 模块级常量（meta 时间戳已全部改用 dt_cls.now()）
- v1.0o (2026-06-16): 6 项缺陷修复（一致性 + 可观测性收尾）
  - Fix 1: _parse_numeric_with_unit 合并 int/float 分支（与 _parse_percentage 风格一致，消除冗余）
  - Fix 2: _parse_numeric_with_unit 增加可选 logger_arg 参数，调用方传入 _logger（避免 warning 绕过调用链路由）
  - Fix 3: _parse_report_date 兜底分支补充注释（明确预期覆盖 numpy.datetime64 等非 datetime.date 子类）
  - Fix 4: df 守卫触发时增加 _logger.error，避免与 fetch 失败 / 空数据静默混淆
  - Fix 5: 主循环 enumerate 改为直接迭代（循环变量 i 从未使用）
  - Fix 6: load_cache 旧格式日志文案 "旧格式 list" → "待迁移旧格式"（准确反映此处仅加载未迁移）

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 setup_logger（MODULE.md 约束）
- 大对象显式 del 释放（MODULE.md 约束 #88→R16）
"""

import datetime
import gc
import json
import logging
import re
import sys
import time
from datetime import datetime as dt_cls
from typing import Any

import akshare as ak
import pandas as pd


# 公共模块导入（遵循 MODULE.md 约束 #4）
try:
    from data_fetchers.common import (
        get_module_result_dir,
        load_main_board_stock_list,
        setup_logger,
        write_gzip_cache,
    )
except ImportError:
    from common import (
        get_module_result_dir,
        load_main_board_stock_list,
        setup_logger,
        write_gzip_cache,
    )

# 版本号常量（MODULE.md 约束 #16）
_OUTPUT_VERSION = "1.0o"

logger = logging.getLogger(__name__)

# 使用公共模块路径函数
RESULT_DIR = get_module_result_dir()
CACHE_FILE = RESULT_DIR / "financial_data.json.gz"

# 同花顺财务摘要关键字段映射
# 中文名 → 英文逻辑名（因子计算函数使用）
_FINANCIAL_FIELD_MAP: dict[str, str] = {
    "净资产收益率": "roe",
    "净资产收益率-摊薄": "diluted_roe",
    "净利润同比增长率": "net_profit_growth_yoy",
    "营业总收入同比增长率": "revenue_growth_yoy",
    "基本每股收益": "basic_eps",
    "每股净资产": "book_value_per_share",
}

# 拉取速率控制
_FETCH_DELAY = 0.3  # 每只股票拉取间隔（秒）
_BATCH_LOG_INTERVAL = 50  # 每实际拉取50只股票输出一次进度日志
_CHECKPOINT_INTERVAL = 500  # 每拉取500只股票做一次检查点写入（全量序列化 stock_data，频率过高 I/O 开销大）
_RATE_LIMIT_RETRIES = 3  # 限流退避最大重试次数
_RATE_LIMIT_BASE_DELAY = 2.0  # 限流退避基础延迟（秒），每次翻倍

# 年化系数：季度 EPS → 年化 EPS
# Q1: ×4, Q2: ×2, Q3: ×4/3, Q4: ×1
_QUARTER_ANNUALIZE_FACTOR: dict[int, float] = {
    3: 4.0,
    6: 2.0,
    9: 4.0 / 3.0,
    12: 1.0,
}


def _parse_percentage(val: Any) -> float | None:
    """解析百分比字符串（如 '-4.21%' → -4.21）

    Args:
        val: 原始值（可能是百分比字符串、float、或 NaN/False/None）

    Returns:
        解析后的浮点数，无法解析返回 None

    Note:
        数据源单位约定（akshare stock_financial_abstract_ths）：
        - str 类型：带 '%' 后缀的百分数形式（如 '4.21%' 表示 4.21%）
        - float 类型：已是百分数形式（如 4.21 表示 4.21%，而非 0.0421）
        - int 类型：兼容性兜底，与 float 同语义（如 5 表示 5%，少数据源可能返回纯整数）
        - 若数据源返回小数形式，调用方需自行 ×100 转换
        - 集成测试通过已知股票数据断言输出范围来验证单位一致性
          （如 ROE 应在 [-100, 100] 区间，若出现 0.0421 量级则说明单位错误）
    """
    if val is None:
        return None
    # 拦截 bool 子类（含 numpy.bool_）：bool 是 int 子类，会被 isinstance(val, int) 命中
    if isinstance(val, bool):
        return None
    # 统一 NA 检查（兼容 float/numpy.float64/pd.NaT 等），消除对继承关系的隐式依赖
    try:
        if pd.isna(val):
            return None
    except (ValueError, TypeError):
        pass  # pd.isna 对非数值类型（如 list）可能抛异常，此时忽略
    # int 与 float 同语义（数据源返回的数值已是百分数形式），合并分支消除冗余
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        # 去掉百分号和空格
        s = val.strip().replace("%", "").replace("％", "")
        if s in ("", "-", "N/A", "nan", "NaN", "--"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_numeric_with_unit(val: Any, logger_arg: logging.Logger | None = None) -> float | None:
    """解析带单位的数值（如 '426.33亿' → 426330000000.0, '2.0700' → 2.07）

    Args:
        val: 原始值（可能是带亿/万单位的字符串、float、或 NaN/None）
        logger_arg: 可选 logger，若提供则 warning 通过该 logger 输出（与调用链路由一致）；
                    否则使用模块级 logger 作为兜底。

    Returns:
        解析后的浮点数（亿→×1e8, 万→×1e4, 无单位→原值），无法解析返回 None

    Note:
        NA 值统一通过 pd.isna 前置检查处理，兼容 Python float / numpy.float64 / pd.NaT，
        不依赖 isinstance(val, float) 对 numpy 标量的隐式继承关系。
    """
    _logger = logger_arg or logger
    if val is None:
        return None
    # 拦截 bool 子类（含 numpy.bool_）：bool 是 int 子类，会被 isinstance(val, int) 命中
    if isinstance(val, bool):
        return None
    # 统一 NA 检查（兼容 float/numpy.float64/pd.NaT 等），消除对继承关系的隐式依赖
    try:
        if pd.isna(val):
            return None
    except (ValueError, TypeError):
        pass
    # int 与 float 同语义（数据源返回的数值已是裸数值），合并分支消除冗余
    # （与 _parse_percentage 风格保持一致）
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s in ("", "-", "N/A", "nan", "NaN", "--"):
            return None
        # Fix 5 (v1.0n): 本函数定位为"数值带单位"（亿/万），百分号属于百分比格式，
        # 不应静默 strip。若混入百分号（如脏数据 "4.21%亿" → 误解析为 4.21e8），
        # 直接返回 None 让调用方走 _parse_percentage 或上抛 warning。
        if "%" in s or "％" in s:
            _logger.warning("_parse_numeric_with_unit 收到含百分号的输入: %r，返回 None", s[:40])
            return None
        # 处理亿/万单位
        multiplier = 1.0
        if "亿" in s:
            s = s.replace("亿", "")
            multiplier = 1e8
        elif "万" in s:
            s = s.replace("万", "")
            multiplier = 1e4
        try:
            return float(s) * multiplier
        except ValueError:
            return None
    return None


# 报告期日期正则：YYYY-MM-DD 格式校验
_REPORT_DATE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _parse_report_date(report_date_raw: Any) -> str | None:
    """解析报告期日期，兼容 datetime.date、pd.Timestamp 和字符串类型

    注意：
    - pd.NaT（pandas 缺失时间戳）不是 None，isinstance(NaT, datetime.date) 为 False，
      但 str(NaT) 返回 'NaT' 会误判为有效日期，因此需前置 pd.isnull 检查。
    - str 类型需通过 YYYY-MM-DD 正则校验，不规范格式（如 "20240331"、"2024年3月31日"）
      返回 None，避免写入缓存后下游月份提取静默出错。
    """
    if report_date_raw is None:
        return None
    # 前置 NA 检查：拦截 pd.NaT 和其他 pandas 缺失值
    try:
        if pd.isnull(report_date_raw):
            return None
    except (ValueError, TypeError):
        pass
    if isinstance(report_date_raw, datetime.date):
        # 注意：pd.Timestamp 是 datetime.date 子类，会在此分支被捕获，
        # 其 strftime("%Y-%m-%d") 行为与 datetime.date 一致，无需独立分支。
        return report_date_raw.strftime("%Y-%m-%d")
    if isinstance(report_date_raw, str):
        if _REPORT_DATE_RE.match(report_date_raw):
            # 正则只校验格式，需进一步验证日期逻辑有效性
            # （如 "2024-02-31" 通过正则但不是合法日期，下游月份提取 31 会触发无效月份 warning）
            try:
                datetime.date.fromisoformat(report_date_raw)
            except ValueError:
                return None
            return report_date_raw
        return None
    # 其他类型兜底：尝试转为字符串后校验。
    # 预期覆盖的类型（不属于 datetime.date / str 的合法日期对象）：
    # - numpy.datetime64：str() 输出 "2024-03-31" 或 "2024-03-31T00:00:00"，前者可通过正则
    # - 自定义日期类（实现 __str__ 返回 ISO 格式）：极少见但允许
    # 注：pd.NaT 已被前置 pd.isnull 拦截，不会走到这里；pd.Timestamp 已被 datetime.date 分支捕获。
    # 若 str() 结果不符合 YYYY-MM-DD，统一返回 None（不规范输入应该被拒绝）。
    try:
        fallback_str = str(report_date_raw)
    except Exception:
        return None
    if _REPORT_DATE_RE.match(fallback_str):
        try:
            datetime.date.fromisoformat(fallback_str)
        except ValueError:
            return None
        return fallback_str
    return None


def _is_rate_limit_error(exc: Exception) -> bool:
    """检测异常是否为 API 限流（429/频率限制）特征

    识别策略：
    - HTTP 429 状态码（urllib/requests 的 HTTPError）
    - 异常消息包含限流关键词（频率/限制/429/rate limit）
    """
    exc_name = type(exc).__name__
    exc_msg = str(exc)
    # HTTP 429（仅检查异常消息，类名不含 "429"）
    if "429" in exc_msg:
        return True
    # 明确的限流异常类名（不包含 HTTPError：400/500 等非限流错误也会抛 HTTPError）
    if exc_name == "TooManyRequests":
        return True
    # 中文关键词：精确匹配，不受大小写影响，对原串直接 in 判断
    cn_keywords = ("频率", "请求频率限制", "访问频率")
    if any(kw in exc_msg for kw in cn_keywords):
        return True
    # 英文关键词：本身全为小写，仅对英文匹配场景做 casefold（兼容 unicode 大写映射）
    # 不对全消息 .lower()，避免对中文字符串做无意义处理。
    exc_msg_cf = exc_msg.casefold()
    en_keywords = ("rate limit", "too many", "throttl")
    return any(kw in exc_msg_cf for kw in en_keywords)


def fetch_financial_data_for_stock(
    symbol: str,
    logger_arg: logging.Logger | None = None,
) -> list[dict[str, Any]] | None:
    """拉取单只股票的财务摘要数据（同花顺数据源）

    Args:
        symbol: 股票代码（如 '000001'），6位纯数字
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        财务数据记录列表，每项包含 {asset, report_date, roe, eps, ...}
        拉取异常返回 None（API 错误/网络超时）
        数据为空返回空列表（该股票确实无财务数据）
    """
    _logger = logger_arg or logger
    # df 在 try 成功后立即 break；except 分支均会 return None 或 continue。
    # 初始化为 None 仅为静态分析（Pyright reportPossiblyUnbound）友好，
    # 实际执行路径下 `assert df is not None` 永远成立。
    df: pd.DataFrame | None = None
    for attempt in range(1, _RATE_LIMIT_RETRIES + 1):
        try:
            df = ak.stock_financial_abstract_ths(symbol=symbol)
            break  # 成功则退出重试循环
        except Exception as e:
            # 检测限流特征：HTTP 429 或常见限流异常关键词
            is_rate_limit = _is_rate_limit_error(e)
            if is_rate_limit and attempt < _RATE_LIMIT_RETRIES:
                delay = _RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1))
                _logger.warning(
                    "拉取 %s 触发限流 (第%d次), %0.1fs 后重试: %s (%s)",
                    symbol,
                    attempt,
                    delay,
                    str(e)[:80],
                    type(e).__name__,
                )
                time.sleep(delay)
                continue
            # 非限流异常 或 限流但已达最后一次重试 → 直接返回 None
            # 最后一次循环 attempt == _RATE_LIMIT_RETRIES，
            # `attempt < _RATE_LIMIT_RETRIES` 为 False 必落入此分支 return None，
            # 因此 for-else 子句永远不可达，已删除。
            _logger.warning(
                "拉取 %s 财务数据失败: (%s) [异常信息: %s]%s",
                symbol,
                type(e).__name__,
                str(e)[:120],
                f" (重试{_RATE_LIMIT_RETRIES}次后仍失败)" if is_rate_limit else "",
            )
            return None

    # 静态分析守卫：循环正常路径必通过 break 后 df 有值，否则 except 分支已 return。
    # 用 if 显式守卫而非 assert，避免 -O 优化跳过守卫 + AssertionError 不友好。
    # 运行期理论上永真，仍保留以兼容未来 except 分支重构（防御性编程）。
    if df is None:
        # Fix 4 (v1.0o): 守卫被实际触发意味着 except 重构破坏了原契约（所有失败路径都 return None），
        # 必须 error 级别记录以便排查，禁止与 fetch 失败 / 空数据 (return [] / None) 混淆。
        _logger.error("df 意外为 None (symbol=%s)，请检查重试逻辑契约是否被破坏", symbol)
        return None
    if df.empty:
        _logger.info("%s 财务数据为空", symbol)
        return []

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {"asset": symbol}
        # 解析报告期日期
        report_date_raw = row.get("报告期", None)
        report_date_str = _parse_report_date(report_date_raw)
        if report_date_str is None:
            if report_date_raw is not None:
                _logger.warning(
                    "报告期日期不符合YYYY-MM-DD格式或非合法日期 (stock=%s, raw=%s), 跳过该记录",
                    symbol,
                    str(report_date_raw)[:40],
                )
            continue
        record["report_date"] = report_date_str

        # 提取关键字段（中文名 → 英文逻辑名）
        # 百分比字段: 净利润同比增长率, 营业总收入同比增长率, ROE
        # _FINANCIAL_FIELD_MAP 共 6 个字段：4 个百分比 + 2 个数值带单位，已被下方分支全覆盖
        for cn_name, en_name in _FINANCIAL_FIELD_MAP.items():
            if cn_name in ("净利润同比增长率", "营业总收入同比增长率", "净资产收益率", "净资产收益率-摊薄"):
                record[en_name] = _parse_percentage(row.get(cn_name, None))
            elif cn_name in ("基本每股收益", "每股净资产"):
                record[en_name] = _parse_numeric_with_unit(row.get(cn_name, None), _logger)

        # 计算年化 EPS（用于 PE 计算）
        # 遵循 PROJECT.md R15（显式除零保护）：factor 为 None 时置 None 而非静默兜底
        # 注意：eps == 0 是有效的盈亏平衡数值（非缺失），年化后仍为 0，不应置 None。
        eps = record.get("basic_eps")
        if eps is not None:
            try:
                parts = report_date_str.split("-")
                month = int(parts[1])
            except (IndexError, ValueError):
                _logger.warning(
                    "报告期日期格式异常无法提取月份 (stock=%s, report_date=%s), annualized_eps 置 None",
                    symbol,
                    report_date_str,
                )
                record["annualized_eps"] = None
            else:
                factor = _QUARTER_ANNUALIZE_FACTOR.get(month)
                if factor is None:
                    _logger.warning(
                        "报告期月份 %d 不在季度年化系数字典中 (stock=%s, report_date=%s), annualized_eps 置 None",
                        month,
                        symbol,
                        report_date_str,
                    )
                    record["annualized_eps"] = None
                else:
                    record["annualized_eps"] = eps * factor
        else:
            record["annualized_eps"] = None

        records.append(record)

    return records


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any]:
    """加载已有的财务数据缓存

    Returns:
        缓存数据字典，包含 meta 和 data 键。缓存不存在返回空结构。
    """
    _logger = logger_arg or logger
    if not CACHE_FILE.exists():
        _logger.info("财务数据缓存不存在，将全新拉取")
        return {"meta": {}, "data": {}}

    try:
        import gzip

        with gzip.open(CACHE_FILE, "rt") as f:
            data = json.load(f)
        # 兼容 dict（v1.0c+）和 list（v1.0b）格式，计算实际记录数
        # Fix 3 (v1.0n): dict 格式同时打印股票数 + 记录数，与 main 中 "缓存已有 N 只股票" 对齐
        raw_data_field = data.get("data", [])
        if isinstance(raw_data_field, dict):
            stock_count = len(raw_data_field)
            record_count = sum(len(v) for v in raw_data_field.values())
            _logger.info("加载财务数据缓存: %d 只股票 / %d 条记录", stock_count, record_count)
        else:
            record_count = len(raw_data_field)
            _logger.info("加载财务数据缓存（待迁移旧格式）: %d 条记录", record_count)
        return data
    except Exception as e:
        _logger.warning("加载缓存失败: %s (%s)，将全新拉取", str(e)[:80], type(e).__name__)
        return {"meta": {}, "data": {}}


def get_cached_stock_codes(cache_data: dict[str, Any]) -> set[str]:
    """从缓存数据中提取已拉取的股票代码集合

    兼容两种格式：dict（v1.0c+）和 list（v1.0b 及更早）
    """
    data = cache_data.get("data", {})
    if isinstance(data, dict):
        return set(data.keys())
    # 旧格式兼容：data 是 list
    return {r.get("asset", "") for r in data if r.get("asset")}


def main(logger_arg: logging.Logger | None = None) -> int:
    """主函数：拉取所有股票财务数据并保存缓存

    Returns:
        0=成功, 1=失败
    """
    _logger = logger_arg or logger
    _logger.info("=== 财务数据拉取开始 (v%s) ===", _OUTPUT_VERSION)

    # Step 1: 加载缓存
    cache_data = load_cache(logger_arg=_logger)

    # 迁移旧格式：data 为 list → 转为 dict（以股票代码为 key）
    raw_data = cache_data.get("data", {})
    if isinstance(raw_data, list):
        _logger.info("检测到旧格式缓存（list），迁移为 dict 格式")
        stock_data: dict[str, list[dict[str, Any]]] = {}
        dropped_recs = 0
        for rec in raw_data:
            code = rec.get("asset", "")
            if code:
                stock_data.setdefault(code, []).append(rec)
            else:
                dropped_recs += 1
        migrated_records = sum(len(v) for v in stock_data.values())
        _logger.info(
            "迁移完成: list %d 条 → dict %d 只股票 / %d 条记录",
            len(raw_data),
            len(stock_data),
            migrated_records,
        )
        if dropped_recs > 0:
            _logger.warning("迁移丢弃 %d 条 asset 为空的记录", dropped_recs)
    else:
        stock_data = raw_data

    cached_codes = set(stock_data.keys())
    _logger.info("缓存已有 %d 只股票数据", len(cached_codes))

    # Step 2: 判断全量/增量模式
    # 超过一个季度（90天）未全量拉取 → 全量模式
    last_full_date_str = cache_data.get("meta", {}).get("last_full_fetch_date")
    need_full_fetch = True
    if last_full_date_str:
        try:
            last_full_dt = dt_cls.strptime(last_full_date_str, "%Y-%m-%d").date()
            days_since = (dt_cls.now().date() - last_full_dt).days
            need_full_fetch = days_since > 90
            _logger.info(
                "上次全量拉取: %s (%d天前), 模式: %s",
                last_full_date_str,
                days_since,
                "全量" if need_full_fetch else "增量",
            )
        except ValueError:
            _logger.warning("无法解析 last_full_fetch_date: %s", last_full_date_str)
    else:
        _logger.info("无 last_full_fetch_date 记录，执行全量拉取")

    # 读取上次 stale_codes，增量模式下强制重拉这些失败的股票
    stale_codes_from_cache: set[str] = set()
    raw_stale = cache_data.get("meta", {}).get("stale_codes")
    if raw_stale and isinstance(raw_stale, list):
        stale_codes_from_cache = set(raw_stale)
        if not need_full_fetch and stale_codes_from_cache:
            _logger.info(
                "上次全量拉取有 %d 只股票 API 失败，本次增量模式强制重拉",
                len(stale_codes_from_cache),
            )
        elif need_full_fetch and stale_codes_from_cache:
            _logger.info(
                "上次全量拉取有 %d 只股票 API 失败，本次全量模式将自动覆盖",
                len(stale_codes_from_cache),
            )

    # Step 3: 加载股票列表
    try:
        stock_list = load_main_board_stock_list(logger=_logger)
    except Exception as e:
        _logger.error("加载股票列表失败: %s", e)
        return 1

    # 提取6位股票代码
    # Fix 6 (v1.0n): 用 dict.fromkeys 保序去重，从根本上消除 stock_list 重复 code 的潜在风险
    # （避免重复 code 在 successfully_fetched_codes 计数偏差，以及检查点后重复发起 API 请求）
    raw_codes: list[str] = []
    for stock in stock_list:
        code = str(stock.get("code", "")).zfill(6)
        if len(code) == 6 and code.isdigit():
            raw_codes.append(code)
    all_codes: list[str] = list(dict.fromkeys(raw_codes))
    if len(all_codes) != len(raw_codes):
        _logger.info(
            "stock_list 含重复 code，已去重: 原 %d → 去重后 %d",
            len(raw_codes),
            len(all_codes),
        )

    # 过滤 stale_codes_from_cache 中已退市/改代码的废弃代码
    # （已不在当前 all_codes 中的代码不应被计入 codes_to_fetch 或尝试拉取）
    all_codes_set = set(all_codes)
    if stale_codes_from_cache and not stale_codes_from_cache.issubset(all_codes_set):
        removed_stale = stale_codes_from_cache - all_codes_set
        stale_codes_from_cache &= all_codes_set
        _logger.info(
            "stale_codes 中 %d 只股票已不在当前列表（退市/改代码），已过滤",
            len(removed_stale),
        )

    # 预计算待拉取股票数（固定分母，与循环内跳过逻辑保持一致）
    codes_to_fetch = sum(
        1 for c in all_codes if need_full_fetch or c not in cached_codes or c in stale_codes_from_cache
    )
    _logger.info("股票总数=%d, 待请求=%d, 将跳过=%d", len(all_codes), codes_to_fetch, len(all_codes) - codes_to_fetch)

    # Step 4: 拉取数据
    new_stock_data: dict[str, list[dict[str, Any]]] = {}
    successfully_fetched_codes: set[str] = set()  # 跨检查点累积所有成功拉取的股票代码
    skipped = 0
    failed = 0
    empty = 0
    fetch_count = 0  # 实际发起 API 请求的次数（不含跳过）
    total_new_count = 0  # 本次运行实际新增的股票总数（不受检查点 clear 影响）
    stale_codes: set[str] = set()  # 本次运行 API 失败的股票代码（全量/增量统一记录），最终汇入 meta.stale_codes

    for code in all_codes:
        # 增量模式跳过已有数据（但 stale_codes_from_cache 中的股票强制重拉）；全量模式全部重新拉取
        if not need_full_fetch and code in cached_codes and code not in stale_codes_from_cache:
            skipped += 1
            continue

        fetch_count += 1

        result = fetch_financial_data_for_stock(code, logger_arg=_logger)
        if result is None:
            failed += 1
            # Fix 7: 统一记录失败码到 stale_codes（不再受 need_full_fetch 限制）
            # 增量模式下若 code 不在 cached_codes，原逻辑不会记录，
            # 导致下次运行虽仍会重试但无法通过 meta.stale_codes 日志感知失败状态。
            stale_codes.add(code)
        elif result:
            new_stock_data[code] = result
            successfully_fetched_codes.add(code)
            total_new_count += 1
        else:
            empty += 1

        # Fix 5: 进度日志移至 result 处理之后，使本次请求结果纳入统计。
        # 原位置（调用前）会导致 total_new_count/failed/empty 比已请求次数少 1。
        if fetch_count % _BATCH_LOG_INTERVAL == 0:
            _logger.info(
                "拉取进度: 请求=%d/%d (新增=%d, 失败=%d, 空数据=%d, 跳过=%d)",
                fetch_count,
                codes_to_fetch,
                total_new_count,
                failed,
                empty,
                skipped,
            )

        # 检查点写入 — 每 500 只股票写一次缓存，防崩溃丢失（_CHECKPOINT_INTERVAL）
        # 先 update 再直接写 stock_data，避免浅拷贝导致内存峰值翻倍
        if fetch_count % _CHECKPOINT_INTERVAL == 0 and new_stock_data:
            stock_data.update(new_stock_data)
            checkpoint_meta: dict[str, Any] = {
                "version": _OUTPUT_VERSION,
                "fetched_at": dt_cls.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d")
                if need_full_fetch
                else (last_full_date_str or dt_cls.now().strftime("%Y-%m-%d")),
                "stock_count": len(stock_data),
                "record_count": sum(len(v) for v in stock_data.values()),
                "fields": list(_FINANCIAL_FIELD_MAP.values()) + ["annualized_eps"],
                "source": "akshare_stock_financial_abstract_ths",
                "checkpoint": True,
            }
            checkpoint_data = {"meta": checkpoint_meta, "data": stock_data}
            write_gzip_cache(CACHE_FILE, checkpoint_data, ensure_dir=True, logger=_logger)
            _logger.info(
                "检查点写入: %s (%d 只股票, %d 条记录)",
                CACHE_FILE,
                len(stock_data),
                checkpoint_meta["record_count"],
            )
            new_stock_data.clear()

        # 速率控制
        time.sleep(_FETCH_DELAY)

    _logger.info(
        "拉取完成: 新增 %d 只股票, 失败 %d, 空数据 %d, 跳过 %d (共请求 %d 次)",
        total_new_count,
        failed,
        empty,
        skipped,
        fetch_count,
    )

    # Step 5: 合并数据（dict 格式：以股票代码为 key，新数据覆盖旧数据）
    stock_data.update(new_stock_data)

    # Step 6: 构建元数据
    total_records = sum(len(v) for v in stock_data.values())
    meta: dict[str, Any] = {
        "version": _OUTPUT_VERSION,
        "fetched_at": dt_cls.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_full_fetch_date": dt_cls.now().strftime("%Y-%m-%d")
        if need_full_fetch
        else (last_full_date_str or dt_cls.now().strftime("%Y-%m-%d")),
        "stock_count": len(stock_data),
        "record_count": total_records,
        "fields": list(_FINANCIAL_FIELD_MAP.values()) + ["annualized_eps"],
        "source": "akshare_stock_financial_abstract_ths",
    }
    # 全量/增量模式统一处理 stale_codes（Fix 7：所有模式下失败码统一记录）：
    # - stale_codes：本次运行实际失败的 code（含非缓存新失败）
    # - 全量模式：final_stale = 本次失败码（覆盖式记录）
    # - 增量模式：final_stale = (上次 stale - 本次成功重拉) ∪ 本次新失败码
    final_stale: set[str] = set()
    if need_full_fetch:
        final_stale = stale_codes
    else:
        # 增量模式：保留上次仍未成功的 + 本次新失败的，移除本次成功重拉的
        kept_from_cache = stale_codes_from_cache - successfully_fetched_codes
        final_stale = kept_from_cache | stale_codes
        successfully_refetched = stale_codes_from_cache & successfully_fetched_codes
        if stale_codes_from_cache and (successfully_refetched or stale_codes):
            _logger.info(
                "stale_codes: 上次 %d 只 → 本次成功重拉 %d 只 → 本次新失败 %d 只 → 剩余 %d 只",
                len(stale_codes_from_cache),
                len(successfully_refetched),
                len(stale_codes - stale_codes_from_cache),
                len(final_stale),
            )
        elif stale_codes:
            _logger.info(
                "stale_codes: 上次 0 只 → 本次新失败 %d 只",
                len(stale_codes),
            )
    if final_stale:
        meta["stale_codes"] = sorted(final_stale)
        _logger.warning(
            "%s: %d 只股票 API 失败，已记录到 meta.stale_codes",
            "全量拉取" if need_full_fetch else "增量拉取（含历史 stale）",
            len(final_stale),
        )

    # Step 7: 写入缓存
    output_data = {"meta": meta, "data": stock_data}
    write_gzip_cache(CACHE_FILE, output_data, ensure_dir=True, logger=_logger)
    _logger.info(
        "缓存写入完成: %s (%d 只股票, %d 条记录)",
        CACHE_FILE,
        meta["stock_count"],
        meta["record_count"],
    )

    # 显式释放大对象（遵循 R16）
    del new_stock_data, cache_data, stock_data
    gc.collect()

    _logger.info("=== 财务数据拉取完成 ===")
    return 0


if __name__ == "__main__":
    cli_logger = setup_logger("fetch_financial.cli")
    sys.exit(main(logger_arg=cli_logger))
