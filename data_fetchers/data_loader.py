#!/usr/bin/env python3
"""
真实 A股历史数据加载器

职责：从 API 获取股票历史数据（OHLCV K线）

公开接口（__all__）：
- RealDataLoader: 数据加载器主类
- get_module_logger: logger 工厂函数
- PermanentFailureError: 永久性失败异常
- MIN_VALID_ROWS: 单只股票"有效行数"阈值（=15），同步暴露给调用方做二次校验，
  以保证调用方与 _get_api_stock_history/_fetch_single_stock_with_retry 三处阈值一致。
  推荐外部使用：直接 from data_fetchers.data_loader import MIN_VALID_ROWS。
- KLINE_SCALE_DAILY: 新浪 K 线 scale 参数日线值（=240），仅作模块内部魔法数字消除使用。
  外部一般无需引用；如需对接其他周期，请新增对应常量而非复用此值。

版本历史：
- v1.0 (2026-04-01): 首次创建（云舟）
- v2.0 (2026-05-27): 简化重构
  - 移除股票列表获取逻辑（已迁移到 fetch_stock_list.py）
  - 移除缓存管理逻辑（已迁移到 common/cache_manager.py）
  - 移除因子计算逻辑（已迁移到 factor_calculator.py）
  - 移除 IC 计算逻辑（不属于此模块职责）
  - 移除模拟数据生成（已迁移到 common/data_loader.py）
  - 保留核心数据获取功能：get_stock_history, _fetch_stock_batch_parallel
- v2.1 (2026-05-27): 问题修复
  - 修复异常处理静默吞掉问题（拆分为 requests/JSON/其他异常）
  - 修复永久性失败无意义重试问题（引入 PermanentFailureError）
  - 删除类内重复的 KLINE_URL 和 LOCAL_DATA_DIR 定义
  - 删除函数内重复的 headers 定义，使用 session 级别 headers
  - 移除已废弃的 max_workers 参数
  - 修复 future 顺序阻塞等待问题（改用 as_completed）
  - 修复 logger 多线程竞态条件（模块加载时初始化）
- v2.2 (2026-05-27): 问题修复
  - API返回非列表改为临时失败（warning+return None），而非 PermanentFailureError
  - _get_local_stock_history 添加异常处理，与 API 路径风格一致
  - 删除 _fetch_stock_batch 中未使用的 enumerate 变量 i
  - 删除未使用的 datetime 导入
  - 删除未使用的 typing.Any 导入
- v2.3 (2026-06-15): 问题修复
  - 提取魔法数字为模块级常量：MIN_VALID_ROWS=15、KLINE_SCALE_DAILY=240
  - _fetch_single_stock_with_retry 数据不足分支补 debug 日志（含 code/attempt/rows）
  - _fetch_single_stock_with_retry 兜底 except 补 warning 日志（含 code/attempt/异常类型）
  - _fetch_stock_batch_parallel 改为接收单一完整列表，内部二等分（封装线程分配）
  - get_stock_history 入口校验 stock_code/days 参数
  - _fetch_stock_batch_parallel ThreadError 改用 logger.exception 保留完整堆栈
  - _get_local_stock_history 成功路径补 debug 日志（含 file_path/rows）
- v2.4 (2026-06-15): 问题修复
  - _fetch_stock_batch_parallel Note 补充 stocks 长度为 1 的边界行为说明
  - _fetch_stock_batch_parallel 跳过对空分片的线程提交，避免无意义任务
  - get_stock_history bool 守卫补行内注释，防止维护者误删
  - _get_local_stock_history 改用 result = df.tail(days)，保证日志 rows 与返回行数严格一致
  - _fetch_single_stock_with_retry 抖动公式补注释（最大额外延迟 = delay * 0.095）
  - 模块 docstring 补"公开接口"段，明确 MIN_VALID_ROWS 推荐外部引用、KLINE_SCALE_DAILY 不推荐
  - _get_api_stock_history 单条解析失败补 debug 日志（含 stock_code/损坏 item/异常类型）
"""

# 标准库导入
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

# 第三方库导入
import pandas as pd
import requests


# 本地模块导入（条件导入）
try:
    from data_fetchers.common.logger_config import setup_logger

    HAS_COMMON_MODULES = True
except ImportError:
    HAS_COMMON_MODULES = False
    setup_logger = None  # type: ignore

# ============================================================================
# 模块级常量
# ============================================================================

# 新浪财经 K线 API 端点
KLINE_URL = "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"

# 本地数据路径（兜底）
LOCAL_DATA_DIR = os.path.expanduser("~/projects/factor_ic_analyzer/data")

# 新浪 K 线接口 scale 参数：240 表示日线（60=60分钟，30=30分钟，15=15分钟，5=5分钟）
# 公开导出仅为消除模块内魔法数字；不推荐外部模块引用此值做语义判断
KLINE_SCALE_DAILY = 240

# 单只股票 K 线被视为"有效"的最小行数；少于此值视为数据不足，触发重试或丢弃
# 同时被 _get_api_stock_history 的有效行数校验和 _fetch_single_stock_with_retry 的成功判定引用
# **推荐外部引用**：调用方（如 fetch_factor_cache.py）应 import 此常量做二次校验，
# 保证"加载器内部判定"与"调用方过滤逻辑"使用同一阈值，避免改一处漏一处
MIN_VALID_ROWS = 15

# ============================================================================
# 异常定义
# ============================================================================


class PermanentFailureError(Exception):
    """永久性失败异常，表示重试无法解决的问题（如不支持的股票代码前缀）"""

    pass


# ============================================================================
# Logger 配置（模块加载时初始化，消除多线程竞态条件）
# ============================================================================

if HAS_COMMON_MODULES and setup_logger is not None:
    _MODULE_LOGGER = setup_logger("data_fetchers.data_loader")
else:
    _MODULE_LOGGER = logging.getLogger("data_fetchers.data_loader")
    if not _MODULE_LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
        _MODULE_LOGGER.addHandler(handler)
        _MODULE_LOGGER.setLevel(logging.INFO)


def get_module_logger(logger_arg: logging.Logger | None = None) -> logging.Logger:
    """获取模块 logger

    Args:
        logger_arg: 外部传入的 logger（可选）

    Returns:
        logging.Logger: 模块 logger

    Note:
        - 如果 logger_arg 为 None，返回模块默认 logger
        - 模块默认 logger 在模块加载时已初始化，无竞态条件
    """
    if logger_arg is not None:
        if not isinstance(logger_arg, logging.Logger):
            raise TypeError(f"logger 参数必须是 logging.Logger 类型，实际: {type(logger_arg)}")
        return logger_arg
    return _MODULE_LOGGER


# ============================================================================
# RealDataLoader 类
# ============================================================================


class RealDataLoader:
    """真实 A股历史数据加载器

    职责：从新浪财经 API 获取股票历史 K线数据（OHLCV）

    不负责：
    - 股票列表获取（请使用 fetch_stock_list.py）
    - 缓存管理（请使用 common/cache_manager.py）
    - 因子计算（请使用 factor_calculator.py）
    """

    def __init__(
        self, timeout: int = 30, retries: int = 3, use_local: bool = False, logger: logging.Logger | None = None
    ):
        """初始化数据加载器

        Args:
            timeout: 请求超时时间（秒）
            retries: 失败重试次数
            use_local: 使用本地CSV数据
            logger: 外部传入的 logger（可选）
        """
        self._logger = get_module_logger(logger)
        self.timeout = timeout
        self.retries = retries
        self.use_local = use_local
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._request_count = 0

        # session 级别 headers，供所有请求复用
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "*/*",
                "Referer": "http://finance.sina.com.cn/",
            }
        )

    def get_stock_history(self, stock_code: str, days: int = 400) -> pd.DataFrame | None:
        """获取单只股票的历史行情

        Args:
            stock_code: 股票代码（如 '600000'），必须为非空字符串
            days: 需要的数据天数，必须为正整数

        Returns:
            pd.DataFrame | None: K线数据，包含 date/open/high/low/close/volume/asset 列
                                 获取失败返回 None

        Raises:
            TypeError: stock_code 不是 str，或 days 不是 int
            ValueError: stock_code 为空字符串，或 days 不是正整数
        """
        # 入参基本校验：避免 None / 负数 / 错类型在深层抛出难以定位的异常
        if not isinstance(stock_code, str):
            raise TypeError(f"stock_code 必须是 str，实际类型: {type(stock_code).__name__}")
        if not stock_code:
            raise ValueError("stock_code 不能为空字符串")
        # bool 是 int 的子类（True == 1, False == 0），isinstance(True, int) 返回 True，
        # 因此必须用 isinstance(days, bool) 单独排除，否则 get_stock_history("600000", True) 会被误放行。
        # 维护时请勿删除此 bool 守卫。
        if not isinstance(days, int) or isinstance(days, bool):
            raise TypeError(f"days 必须是 int，实际类型: {type(days).__name__}")
        if days <= 0:
            raise ValueError(f"days 必须为正整数，实际: {days}")

        if self.use_local:
            return self._get_local_stock_history(stock_code, days)
        return self._get_api_stock_history(stock_code, days)

    def _get_local_stock_history(self, stock_code: str, days: int) -> pd.DataFrame | None:
        """从本地文件读取K线数据

        Args:
            stock_code: 股票代码
            days: 需要的数据天数

        Returns:
            pd.DataFrame | None: K线数据，文件不存在或读取失败返回 None
        """
        data_file = os.path.join(LOCAL_DATA_DIR, f"{stock_code}.csv")

        if not os.path.exists(data_file):
            self._logger.debug("本地数据文件不存在: %s", data_file)
            return None

        try:
            df = pd.read_csv(data_file)
            df["date"] = pd.to_datetime(df["date"])
            df["asset"] = stock_code

            required_cols = ["date", "open", "high", "low", "close", "volume", "asset"]
            df = df[required_cols]

            # 严格保证日志 rows 与 return 行数一致：先取 tail 结果，再用 len 打日志、再 return
            # （此前用 min(len(df), days) 推算的方式在某些边界下可能与 tail 实际行数不一致）
            result = df.tail(days)
            self._logger.debug(
                "本地数据读取成功: stock_code=%s, file=%s, rows=%s",
                stock_code,
                data_file,
                len(result),
            )
            return result
        except Exception as e:
            # CSV文件损坏、缺少必需列或列类型异常
            self._logger.warning(
                "[LocalDataError] 读取本地CSV失败: stock_code=%s, file=%s, error=%s", stock_code, data_file, e
            )
            return None

    def _get_api_stock_history(self, stock_code: str, days: int) -> pd.DataFrame | None:
        """从新浪财经API获取K线数据

        Args:
            stock_code: 股票代码（不带前缀，如 '600000'）
            days: 需要的数据天数

        Returns:
            pd.DataFrame | None: K线数据，获取失败返回 None

        Raises:
            PermanentFailureError: 不支持的股票代码前缀（仅60/00开头）

        Note:
            - 新浪API股票代码格式：sh600000（沪市）或 sz000001（深市）
            - 只支持主板股票（60/00开头）
        """
        try:
            # 新浪API股票代码格式
            if stock_code.startswith("60"):
                symbol = f"sh{stock_code}"
            elif stock_code.startswith("00"):
                symbol = f"sz{stock_code}"
            else:
                # 不支持的股票代码前缀，属于永久性失败
                self._logger.warning("[PermanentFailure] 不支持的股票代码前缀: %s", stock_code)
                raise PermanentFailureError(f"不支持的股票代码前缀: {stock_code}")

            params = {
                "symbol": symbol,
                "scale": KLINE_SCALE_DAILY,  # 日线
                "datalen": days + 50,
            }

            # 使用 session 级别 headers，不再重复设置
            response = self.session.get(KLINE_URL, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()

            # API 返回非列表可能是服务端临时故障，记录警告并返回 None 以触发重试
            if not data or not isinstance(data, list):
                self._logger.warning(
                    "[APIResponseError] API返回非列表数据: stock_code=%s, data_type=%s",
                    stock_code,
                    type(data),
                )
                return None

            rows = []
            for item in data:
                try:
                    rows.append(
                        {
                            "date": item.get("day", ""),
                            "open": float(item.get("open", 0)),
                            "close": float(item.get("close", 0)),
                            "high": float(item.get("high", 0)),
                            "low": float(item.get("low", 0)),
                            "volume": float(item.get("volume", 0)),
                        }
                    )
                except (ValueError, TypeError) as item_err:
                    # 单条 K 线字段类型异常时跳过，但必须记录 debug 日志
                    # 否则大量字段损坏会被静默丢弃，数据质量问题无法追踪
                    self._logger.debug(
                        "[ItemParseError] 跳过损坏的K线: stock_code=%s, item=%s, error_type=%s, error=%s",
                        stock_code,
                        item,
                        type(item_err).__name__,
                        item_err,
                    )
                    continue

            if len(rows) < MIN_VALID_ROWS:
                self._logger.debug(
                    "API返回有效数据不足: stock_code=%s, rows=%s, min_required=%s",
                    stock_code,
                    len(rows),
                    MIN_VALID_ROWS,
                )
                return None

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df["asset"] = stock_code

            cols = ["date", "open", "high", "low", "close", "volume", "asset"]
            df = df[cols].sort_values("date").reset_index(drop=True)

            return df.tail(days)

        except PermanentFailureError:
            # 永久性失败，向上传播，让调用方跳过重试
            raise

        except requests.RequestException as e:
            # 网络相关异常（超时、连接失败等）
            self._logger.warning("[NetworkError] 获取股票数据失败: stock_code=%s, error=%s", stock_code, e)
            return None

        except json.JSONDecodeError as e:
            # JSON 解析错误
            self._logger.warning("[JSONError] 解析响应失败: stock_code=%s, error=%s", stock_code, e)
            return None

        except Exception as e:
            # 其他未知异常
            self._logger.error("[UnexpectedError] 获取股票数据时发生未知错误: stock_code=%s, error=%s", stock_code, e)
            return None

    def _fetch_single_stock_with_retry(
        self, stock_info: dict, days: int, delay: float = 0.05
    ) -> tuple[str, pd.DataFrame | None]:
        """带重试机制获取单只股票数据

        Args:
            stock_info: 股票信息字典 {'code': str, 'name': str}
            days: 需要的数据天数
            delay: 请求延迟

        Returns:
            (股票代码, DataFrame | None)
        """
        code = stock_info["code"]

        with self._lock:
            self._request_count += 1
            request_id = self._request_count

        # 基于请求序号的轻微抖动：jitter_factor = 1 + (request_id % 20) * 0.005
        # → 抖动因子范围 [1.000, 1.095]，最大额外延迟 = delay * 0.095
        # 目的：错开高并发下的请求时序，降低瞬时请求峰值；幅度足够小不显著影响整体节流
        time.sleep(delay * (1 + (request_id % 20) * 0.005))

        for attempt in range(self.retries):
            try:
                df = self.get_stock_history(code, days=days)
                if df is not None and len(df) >= MIN_VALID_ROWS:
                    return (code, df)
                else:
                    # 数据不足（df 为 None 或行数 < MIN_VALID_ROWS），记录调试日志后重试
                    # 让"数据不足重试"和"异常重试"在日志中可区分，避免静默重试无法定位根因
                    self._logger.debug(
                        "数据不足，准备重试: code=%s, attempt=%s/%s, rows=%s, min_required=%s",
                        code,
                        attempt + 1,
                        self.retries,
                        0 if df is None else len(df),
                        MIN_VALID_ROWS,
                    )
                    if attempt < self.retries - 1:
                        time.sleep(0.3 * (attempt + 1))
            except PermanentFailureError as e:
                # 永久性失败，直接返回，跳过重试
                self._logger.debug("跳过重试（永久性失败）: %s, reason=%s", code, e)
                return (code, None)
            except Exception as e:
                # 其他临时异常，记录后重试
                # v2.1 修复初衷：异常不能静默吞掉；此处补 warning 日志，含 code/attempt/异常类型与内容
                self._logger.warning(
                    "[TransientError] 获取股票数据时发生临时异常: code=%s, attempt=%s/%s, error_type=%s, error=%s",
                    code,
                    attempt + 1,
                    self.retries,
                    type(e).__name__,
                    e,
                )
                if attempt < self.retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        self._logger.warning("重试 %s 次后放弃: %s", self.retries, code)
        return (code, None)

    def _fetch_stock_batch(
        self, stock_batch: list[dict], days: int, progress_callback: Callable | None = None
    ) -> list[tuple[str, pd.DataFrame | None]]:
        """获取一批股票的数据（串行获取，带延迟）

        Args:
            stock_batch: 股票信息列表 [{'code': str, 'name': str}, ...]
            days: 需要的数据天数
            progress_callback: 进度回调函数

        Returns:
            List[Tuple[str, Optional[pd.DataFrame]]]: [(股票代码, DataFrame), ...]
        """
        results = []
        for stock_info in stock_batch:
            result = self._fetch_single_stock_with_retry(stock_info, days, delay=0.1)
            results.append(result)
            if progress_callback:
                progress_callback(result[0], result[1] is not None)
        return results

    def _fetch_stock_batch_parallel(
        self,
        stocks: list[dict],
        days: int,
        progress_callback: Callable | None = None,
    ) -> list[tuple[str, pd.DataFrame | None]]:
        """使用2个线程并行获取股票数据

        Args:
            stocks: 待获取的股票列表 [{'code': str, 'name': str}, ...]，
                    内部按二等分自动分配给 2 个工作线程，调用方无需关心线程内部分配
            days: 需要的数据天数
            progress_callback: 进度回调函数

        Returns:
            List[Tuple[str, Optional[pd.DataFrame]]]: 所有股票的数据结果

        Note:
            - 内部将 stocks 二等分：前半部分交给 thread_a，后半部分交给 thread_b
            - 并发数固定为 2，避免触发 API 频率限制
            - 长度为奇数时，thread_b 多 1 只
            - **stocks 长度为 1 时，mid=0：thread_a 为空列表，仅 thread_b 工作**
              （此时实际为单线程串行，是边界场景下可接受的退化行为）
            - 空列表直接返回 []，不创建线程池
            - 任一分片为空时跳过提交对应线程任务，避免为空列表创建无意义的线程
        """
        if not stocks:
            return []

        # 内部二等分：将线程分配职责封装在方法内，调用方不应关心线程内部数据分配
        # 边界：len(stocks) == 1 时 mid=0 → thread_a=[]，thread_b=[stocks[0]]
        mid = len(stocks) // 2
        stocks_for_thread_a = stocks[:mid]
        stocks_for_thread_b = stocks[mid:]

        all_results: list[tuple[str, pd.DataFrame | None]] = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            # 仅对非空分片提交线程任务；空分片提交相当于让线程跑一次零长度循环，浪费调度开销
            futures: dict = {}
            if stocks_for_thread_a:
                futures[executor.submit(self._fetch_stock_batch, stocks_for_thread_a, days, progress_callback)] = (
                    "thread_a"
                )
            if stocks_for_thread_b:
                futures[executor.submit(self._fetch_stock_batch, stocks_for_thread_b, days, progress_callback)] = (
                    "thread_b"
                )

            # 使用 as_completed 避免顺序阻塞等待
            for future in as_completed(futures):
                thread_name = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception:
                    # 线程崩溃时必须保留完整堆栈，以便追溯根因
                    # 用 logger.exception 自动附带 traceback；不再用 %s 拼接异常对象丢失上下文
                    self._logger.exception("[ThreadError] %s 执行失败", thread_name)

        return all_results


# ============================================================================
# 导出
# ============================================================================

__all__ = [
    "RealDataLoader",
    "get_module_logger",
    "PermanentFailureError",
    "MIN_VALID_ROWS",
    "KLINE_SCALE_DAILY",
]
