#!/usr/bin/env python3
"""
真实 A股历史数据加载器

职责：从 API 获取股票历史数据（OHLCV K线）

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
            stock_code: 股票代码（如 '600000'）
            days: 需要的数据天数

        Returns:
            pd.DataFrame | None: K线数据，包含 date/open/high/low/close/volume/asset 列
                                 获取失败返回 None
        """
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

            return df.tail(days)
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
                "scale": 240,  # 日线
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
                except (ValueError, TypeError):
                    continue

            if len(rows) < 15:
                self._logger.debug("API返回有效数据不足: stock_code=%s, rows=%s", stock_code, len(rows))
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

        time.sleep(delay * (1 + (request_id % 20) * 0.005))

        for attempt in range(self.retries):
            try:
                df = self.get_stock_history(code, days=days)
                if df is not None and len(df) >= 15:
                    return (code, df)
                else:
                    # 数据不足，重试
                    if attempt < self.retries - 1:
                        time.sleep(0.3 * (attempt + 1))
            except PermanentFailureError as e:
                # 永久性失败，直接返回，跳过重试
                self._logger.debug("跳过重试（永久性失败）: %s, reason=%s", code, e)
                return (code, None)
            except Exception:
                # 其他临时异常，重试
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
        stocks_for_thread_a: list[dict],
        stocks_for_thread_b: list[dict],
        days: int,
        progress_callback: Callable | None = None,
    ) -> list[tuple[str, pd.DataFrame | None]]:
        """使用2个线程并行获取股票数据

        Args:
            stocks_for_thread_a: 线程A处理的股票列表 [{'code': str, 'name': str}, ...]
            stocks_for_thread_b: 线程B处理的股票列表
            days: 需要的数据天数
            progress_callback: 进度回调函数

        Returns:
            List[Tuple[str, Optional[pd.DataFrame]]]: 所有股票的数据结果

        Note:
            - 线程A处理前半部分，线程B处理后半部分
            - 每线程处理数量由调用方控制
            - 并发数固定为 2，避免触发 API 频率限制
        """
        all_results = []

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self._fetch_stock_batch, stocks_for_thread_a, days, progress_callback): "thread_a",
                executor.submit(self._fetch_stock_batch, stocks_for_thread_b, days, progress_callback): "thread_b",
            }

            # 使用 as_completed 避免顺序阻塞等待
            for future in as_completed(futures):
                thread_name = futures[future]
                try:
                    results = future.result()
                    all_results.extend(results)
                except Exception as e:
                    self._logger.error("[ThreadError] %s 执行失败: %s", thread_name, e)

        return all_results


# ============================================================================
# 导出
# ============================================================================

__all__ = ["RealDataLoader", "get_module_logger", "PermanentFailureError"]
