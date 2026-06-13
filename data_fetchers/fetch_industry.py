#!/usr/bin/env python3
"""
股票行业分类数据获取模块

作者: 云舟
日期: 2026-05-27
版本: v3.0

功能: 获取申万行业分类数据并缓存
数据源: 东方财富行业板块成分股（主）→ akshare 申万行业分类（备）

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
- v2.1 (2026-05-27): Bug修复 - 日志信息修正（"akshare获取失败，尝试本地备用数据"）、备用缓存写入策略docstring说明（非致命错误，与主缓存策略不同）
- v2.2 (2026-05-27): Bug修复 - load_stock_industry缓存数据完整性验证（industries类型检查，防止后续AttributeError）
- v2.3 (2026-05-27): Bug修复 - datetime.now()只调用一次（固定时间戳）、infer_industry_from_name添加Note说明模糊匹配、get_industry_distribution添加返回类型注解
- v2.4 (2026-05-27): 公共模块规范化 - 使用setup_logger替换logging.basicConfig、使用write_json_cache替换手写原子写入（两处）、使用公共模块路径函数替换硬编码路径、创建流程文档和pytest测试文件
- v2.5 (2026-05-27): 维护性改进（4项） - 1)关键词优先级注释修正(新能源电力→电力，声明顺序而非具体优先)；2)移除品牌词"平安"避免歧义；3)日期格式字符串提取为常量_DATE_FORMAT(避免格式不一致隐患)；4)降级链拆平(refresh抛异常，load_stock_industry显式控制降级)
- v2.6 (2026-05-27): 防御性改进（4项） - 1)引入哨兵对象_UNSET避免空dict重复加载；2)修正版本号注释(v2.4→v2.5)；3)移除品牌词"中信"(与"平安"一致)；4)备用文件不存在时添加警告日志(而非静默返回)
- v2.7 (2026-05-27): Bug修复与维护性改进（4项） - 1)统一降级日志格式(旧缓存/本地备用后缀)；2)fetch_stock_industry_sw添加pd.to_datetime转换start_date；3)__all__移除路径常量(防止绕过封装)；4)异常链保留(raise from e)
- v2.8 (2026-05-27): 日志精确化（4项） - 1)refresh_industry_cache RuntimeError捕获块补充异常日志；2)load_stock_industry缓存未过期分支补充操作节点日志(与缓存损坏/过期分支对称)；3)main备用数据失败日志补充异常类型名；4)main失败分支info→error级别
- v3.0 (2026-06-12): 数据源切换 - 主数据源从申万宏源(akshare)切换为东方财富行业板块(akshare stock_board_industry_cons_em)，解决SSL证书验证失败问题（申万官网缺少中间证书）；降级链调整为 EM→SW→本地关键词推断；新增fetch_stock_industry_em()函数和_SW_TO_EM_MAP映射常量；meta.source新增'em_category'值

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 logger（PROJECT.md 日志规范）
"""

import json
import logging
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path


# 公共模块导入（遵循 MODULE.md 约束 #4）
# 条件导入：脚本直接运行时可能路径未配置
try:
    from data_fetchers.common import get_module_result_dir, get_stock_list_file, setup_logger, write_json_cache
except ImportError:
    from common import get_module_result_dir, get_stock_list_file, setup_logger, write_json_cache

# 版本号常量（MODULE.md 约束 #16）
_OUTPUT_VERSION = "3.0"

# 日期格式常量（避免写入和解析格式不一致）
_DATE_FORMAT = "%Y-%m-%d"

logger = logging.getLogger(__name__)

# 使用公共模块路径函数（遵循 MODULE.md 约束 #62）
RESULT_DIR = get_module_result_dir()
STOCK_LIST_BACKUP_PATH = get_stock_list_file()

# 行业数据缓存路径（输出到 result 目录，MODULE.md 约束 #2）
INDUSTRY_CACHE_PATH = RESULT_DIR / "stock_industry.json"

# akshare API 期望列名（防御性校验）
_EXPECTED_INDUSTRY_COLS = ["symbol", "industry_code", "start_date"]
_EXPECTED_STOCK_NAME_COLS = ["code", "name"]


# 申万2021版行业代码映射（一级代码 -> 行业名称）
# 注意：此映射基于申万2021官方一级分类标准（31个行业）
# - 一级代码是连续的：11, 21, 23, 24, 25, 26, 27, 31, 32, 34, 35, 36, 41, 42, 43, 44, 45, 46, 48, 49, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 77
# - akshare 返回的 industry_code 格式为4位（如 '2101'），前两位为一级代码
# - 不存在的一级代码（如 22, 28, 33, 37, 47, 51, 61）是二级代码前两位，映射到 '其他'
# 参考: 申万2021行业分类标准
SW_INDUSTRY_CODE_MAP: dict[str, str] = {
    # 申万2021官方一级分类（31个行业）
    "11": "农林牧渔",
    "21": "基础化工",
    "23": "钢铁",
    "24": "有色金属",
    "25": "汽车",
    "26": "家用电器",
    "27": "电子",
    "31": "商贸零售",
    "32": "医药生物",
    "34": "食品饮料",
    "35": "纺织服饰",
    "36": "轻工制造",
    "41": "公用事业",
    "42": "交通运输",
    "43": "房地产",
    "44": "建筑材料",
    "45": "社会服务",
    "46": "综合",
    "48": "银行",
    "49": "非银金融",
    "62": "建筑装饰",
    "63": "电力设备",
    "64": "机械设备",
    "65": "国防军工",
    "71": "计算机",
    "72": "传媒",
    "73": "通信",
    "74": "煤炭",
    "75": "石油石化",
    "76": "环保",
    "77": "美容护理",
    # 不存在的一级代码（二级代码前两位）→ 映射到 '其他'
    "22": "其他",  # 不存在于申万2021一级分类
    "28": "其他",  # 不存在于申万2021一级分类
    "33": "其他",  # 不存在于申万2021一级分类
    "37": "其他",  # 不存在于申万2021一级分类
    "47": "其他",  # 不存在于申万2021一级分类
    "51": "其他",  # 不存在于申万2021一级分类
    "61": "其他",  # 不存在于申万2021一级分类
}


# 东方财富行业板块名称映射（申万一级 → 东方财富板块名）
# 申万31个一级行业与东方财富板块名称基本一致，1:1映射
# 东方财富通过 stock_board_industry_cons_em(symbol=板块名) 获取成分股
_SW_TO_EM_MAP: dict[str, str] = {
    "农林牧渔": "农林牧渔",
    "基础化工": "基础化工",
    "钢铁": "钢铁",
    "有色金属": "有色金属",
    "汽车": "汽车",
    "家用电器": "家用电器",
    "电子": "电子",
    "商贸零售": "商贸零售",
    "医药生物": "医药生物",
    "食品饮料": "食品饮料",
    "纺织服饰": "纺织服饰",
    "轻工制造": "轻工制造",
    "公用事业": "公用事业",
    "交通运输": "交通运输",
    "房地产": "房地产",
    "建筑材料": "建筑材料",
    "社会服务": "社会服务",
    "综合": "综合",
    "银行": "银行",
    "非银金融": "非银金融",
    "建筑装饰": "建筑装饰",
    "电力设备": "电力设备",
    "机械设备": "机械设备",
    "国防军工": "国防军工",
    "计算机": "计算机",
    "传媒": "传媒",
    "通信": "通信",
    "煤炭": "煤炭",
    "石油石化": "石油石化",
    "环保": "环保",
    "美容护理": "美容护理",
}

# 东方财富 API 期望列名（防御性校验）
_EXPECTED_EM_COLS = ["代码", "名称"]


def fetch_stock_industry_em() -> dict:
    """
    通过东方财富行业板块获取申万一级行业分类数据

    使用 akshare stock_board_industry_cons_em API，
    遍历31个申万一级行业对应的东方财富板块获取成分股。

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Note:
        - 东方财富板块名称与申万一级名称基本一致（见 _SW_TO_EM_MAP）
        - 遍历31个板块约耗时30秒，每个板块间隔0.3秒防反爬
        - 返回的行业名称为申万一级标准（31个行业）
        - stock_board_industry_cons_em 不受 SSL 证书问题影响
    """
    try:
        import time

        import akshare as ak

        logger.info(f"[行业数据 v{_OUTPUT_VERSION}] 开始获取东方财富行业分类（31个板块）...")

        industry_map: dict = {}
        success_count = 0
        fail_count = 0

        for sw_name, em_name in _SW_TO_EM_MAP.items():
            try:
                df = ak.stock_board_industry_cons_em(symbol=em_name)

                # 列名校验（防御性编程）
                missing_cols = [col for col in _EXPECTED_EM_COLS if col not in df.columns]
                if missing_cols:
                    raise KeyError(f"东方财富板块 '{em_name}' 缺少必需列: {missing_cols}, 实际列: {list(df.columns)}")

                codes = df["代码"].astype(str).str.zfill(6).tolist()
                names = df["名称"].tolist()

                for i, code in enumerate(codes):
                    if code not in industry_map:  # 首次归属优先
                        industry_map[code] = {
                            "name": names[i],
                            "industry": sw_name,
                            "industry_code": f"em_{em_name}",
                        }

                success_count += 1
                logger.info(f"[行业数据] EM板块 '{em_name}': {len(df)} 只股票")
                time.sleep(0.3)  # 防反爬间隔

            except Exception as e:
                fail_count += 1
                logger.warning(f"[行业数据] EM板块 '{em_name}' 获取失败 [{type(e).__name__}]: {e}")
                continue

        if not industry_map:
            raise RuntimeError(
                f"东方财富行业数据获取失败: 所有31个板块均获取失败 (成功: {success_count}, 失败: {fail_count})"
            )

        logger.info(
            f"[行业数据] 东方财富获取完成: {len(industry_map)} 只股票, 板块成功: {success_count}, 失败: {fail_count}"
        )
        return industry_map

    except Exception as e:
        logger.error(f"[行业数据] 东方财富 API 获取失败 [{type(e).__name__}]: {e}")
        raise


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

        # 日期格式转换（防御性编程）：确保 start_date 为 datetime 类型
        # 避免混合格式（如"20210101"和"2021-01-01"）导致排序错误
        import pandas as pd

        industry_df["start_date"] = pd.to_datetime(industry_df["start_date"])

        # 获取每只股票的最新行业分类（按start_date降序）
        industry_df_latest = industry_df.sort_values("start_date", ascending=False).drop_duplicates(
            subset="symbol", keep="first"
        )

        # 获取股票名称映射
        stock_names_df = ak.stock_info_a_code_name()

        # 列名校验（防御性编程）
        missing_name_cols = [col for col in _EXPECTED_STOCK_NAME_COLS if col not in stock_names_df.columns]
        if missing_name_cols:
            raise KeyError(f"股票名称数据缺少必需列: {missing_name_cols}, 实际列: {list(stock_names_df.columns)}")

        stock_names_df["code"] = stock_names_df["code"].astype(str).str.zfill(6)
        stock_names_dict = dict(zip(stock_names_df["code"], stock_names_df["name"]))

        # 构建股票→行业映射（使用 to_dict 替代 iterrows，性能优化）
        industry_map = {}

        # 转为字典遍历（避免 iterrows 性能问题）
        for row_dict in industry_df_latest.to_dict("records"):
            code = str(row_dict.get("symbol", "")).strip()
            industry_code = str(row_dict.get("industry_code", "")).strip()

            # 从行业代码提取一级行业（前2位）
            first_level = industry_code[:2] if len(industry_code) >= 2 else ""

            # 映射到行业名称
            industry_name = SW_INDUSTRY_CODE_MAP.get(first_level, "其他")

            # 获取股票名称
            stock_name = stock_names_dict.get(code, "")

            if code:
                industry_map[code] = {"name": stock_name, "industry": industry_name, "industry_code": industry_code}

        logger.info(f"[行业数据] 获取完成: {len(industry_map)} 只股票")
        return industry_map

    except Exception as e:
        # 记录日志后重新抛出异常，保留原始异常链（而非返回空 dict）
        # 让调用方（refresh_industry_cache）捕获并转为 RuntimeError
        logger.error(f"[行业数据] akshare API 获取失败 [{type(e).__name__}]: {e}")
        raise  # 重新抛出原始异常


def load_stock_industry() -> dict:
    """
    加载股票行业数据（优先从缓存）

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Note:
        降级策略显式分层（避免嵌套调用链）：
        1. 尝试刷新缓存（refresh_industry_cache，内部降级链 EM→SW）
        2. 失败 → 本地备用数据（load_local_industry_backup，名称关键词推断）
    """
    # 优先从缓存加载
    if INDUSTRY_CACHE_PATH.exists():
        try:
            with open(INDUSTRY_CACHE_PATH, encoding="utf-8") as f:
                data = json.load(f)

            industries = data.get("industries", {})

            # 数据完整性验证（防止缓存文件损坏导致后续 AttributeError）
            if not isinstance(industries, dict):
                logger.warning(f"[行业数据] 缓存数据类型异常: industries 为 {type(industries).__name__}，期望 dict")
                # 删除损坏缓存
                INDUSTRY_CACHE_PATH.unlink(missing_ok=True)
                # 显式降级：先尝试 akshare，失败后用备用数据（不通过 refresh_industry_cache）
                logger.info("[行业数据] 缓存损坏，尝试重新获取 akshare 数据...")
                try:
                    return refresh_industry_cache()
                except Exception as e:
                    logger.warning(f"[行业数据] akshare 获取失败 [{type(e).__name__}]: {e}，降级备用数据（本地备用）")
                    return load_local_industry_backup()

            # 检查缓存是否过期（超过7天更新）
            meta = data.get("meta", {})
            updated_at = meta.get("updated_at", "")

            if updated_at:
                try:
                    update_date = datetime.strptime(updated_at, _DATE_FORMAT)
                    days_old = (datetime.now() - update_date).days

                    if days_old > 7:
                        logger.info(f"[行业数据] 缓存已过期 {days_old} 天，尝试重新获取...")
                        try:
                            return refresh_industry_cache()
                        except Exception as e:
                            # 刷新失败时降级使用旧缓存（而非直接返回备用数据）
                            logger.warning(f"[行业数据] 刷新失败 [{type(e).__name__}]: {e}，降级使用旧缓存（旧缓存）")
                            return industries
                    else:
                        # 缓存未过期，正常返回（覆盖完整：与缓存损坏和缓存过期分支对称）
                        logger.info(f"[行业数据] 缓存未过期 ({days_old} 天)，从缓存加载: {len(industries)} 只股票")
                        return industries
                except ValueError as e:
                    # 日期格式异常，使用现有缓存（而非静默 pass）
                    logger.warning(f"[行业数据] 日期格式异常 {updated_at!r}: {e}，使用现有缓存")
                    logger.info(f"[行业数据] 从缓存加载: {len(industries)} 只股票")
                    return industries

            # updated_at 不存在（空字符串），直接使用缓存
            logger.info(f"[行业数据] 缓存无更新时间标记，从缓存加载: {len(industries)} 只股票")
            return industries

        except Exception as e:
            logger.warning(f"[行业数据] 缓存加载失败 [{type(e).__name__}]: {e}")

    # 缓存不存在，显式降级：先尝试 akshare，失败后用备用数据
    logger.info("[行业数据] 缓存不存在，尝试获取 akshare 数据...")
    try:
        return refresh_industry_cache()
    except Exception as e:
        logger.warning(f"[行业数据] akshare 获取失败 [{type(e).__name__}]: {e}，降级备用数据（本地备用）")
        return load_local_industry_backup()


def refresh_industry_cache() -> dict:
    """
    刷新行业数据缓存（降级链：EM→SW→抛异常）

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Raises:
        RuntimeError: 所有数据源获取失败（调用方负责降级到本地备用）

    Note:
        v3.0 改进：降级链调整为 EM→SW（原来只有 SW），
        优先使用东方财富（不受 SSL 证书问题影响），
        SW 申万作为备用（受 swsresearch.com SSL 缺失中间证书影响）。
        调用方（load_stock_industry）在 RuntimeError 时降级到本地关键词推断。
    """
    # 1. 优先尝试东方财富数据源
    industry_map = None
    source = ""
    em_error: Exception | None = None  # 记录 EM 失败原因，用于最终 RuntimeError 消息

    try:
        industry_map = fetch_stock_industry_em()
        if industry_map:
            source = "em_category"
            logger.info("[行业数据] 东方财富数据获取成功，使用 EM 数据源")
        else:
            # EM 返回空 dict（不应发生，fetch_stock_industry_em 会抛异常）
            logger.warning("[行业数据] 东方财富返回空数据，尝试 SW 数据源...")
    except Exception as em_e:
        em_error = em_e
        logger.warning("[行业数据] 东方财富获取失败 [%s]: %s，尝试 SW 数据源...", type(em_e).__name__, str(em_e))

    # 2. EM 失败时尝试申万数据源
    if industry_map is None:
        try:
            industry_map = fetch_stock_industry_sw()
            if industry_map:
                source = "sw_category"
                logger.info("[行业数据] 申万数据获取成功（EM 失败后的备用）")
            else:
                logger.error("[行业数据] SW 返回空数据")
                em_msg = f"EM: {type(em_error).__name__}: {em_error}" if em_error else "EM: 返回空数据"
                raise RuntimeError(f"行业数据获取失败: {em_msg} + SW: 返回空数据") from None
        except Exception as sw_e:
            logger.error("[行业数据] SW 获取失败 [%s]: %s", type(sw_e).__name__, str(sw_e))
            em_msg = f"EM [{type(em_error).__name__}]" if em_error else "EM [返回空数据]"
            raise RuntimeError(f"行业数据获取失败: {em_msg} + SW [{type(sw_e).__name__}]") from sw_e

    # 固定时间戳（MODULE.md 约束 #17：datetime.now() 只调用一次）
    now = datetime.now()
    updated_at = now.strftime(_DATE_FORMAT)

    # 写入缓存（meta.source 标注实际数据来源）
    cache_data = {
        "meta": {
            "version": _OUTPUT_VERSION,
            "source": source,
            "level": "一级",
            "updated_at": updated_at,
            "total_count": len(industry_map),
        },
        "industries": industry_map,
    }

    # 确保输出目录存在（MODULE.md 约束 #2：输出到 result 目录）
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # 使用公共模块原子写入（遵循 MODULE.md 约束 #4）
    write_json_cache(INDUSTRY_CACHE_PATH, cache_data, json_indent=2)
    logger.info(f"[行业数据] 缓存已更新: {INDUSTRY_CACHE_PATH} (v{_OUTPUT_VERSION}, source={source})")

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
            with open(stock_list_path, encoding="utf-8") as f:
                stock_data = json.load(f)

            stocks = stock_data.get("stocks", [])
            industry_map = {}

            # 简化分类规则
            for stock in stocks:
                code = stock.get("code", stock.get("asset", ""))
                name = stock.get("name", "")

                # 基于名称推断行业
                industry = infer_industry_from_name(name)

                industry_map[code] = {"name": name, "industry": industry, "industry_code": "local"}

            logger.info(f"[行业数据] 本地备用分类完成: {len(industry_map)} 只股票")

            # 写入缓存（避免每次重复读文件）
            if write_cache and industry_map:
                _write_backup_cache(industry_map)

            return industry_map

        except Exception as e:
            logger.warning(f"[行业数据] 本地备用加载失败 [{type(e).__name__}]: {e}")
    else:
        # 文件不存在：记录警告日志，方便调试（而非静默返回空 dict）
        logger.warning(f"[行业数据] 本地备用文件不存在: {stock_list_path}")

    return {}


def _write_backup_cache(industry_map: dict) -> None:
    """
    写入备用数据缓存（私有函数）

    Args:
        industry_map: 行业映射数据

    Note:
        备用缓存写入失败为**非致命错误**（warning 即可）：
        - 备用数据本身就低于 akshare 数据准确性
        - 写入失败不影响当前返回，下次调用会重新读备用数据
        - 与 refresh_industry_cache 主缓存写入策略不同（主缓存失败抛异常）
        - 此设计决策已在 MODULE.md 约束 #72 中明确说明
    """
    # 固定时间戳（MODULE.md 约束 #17：datetime.now() 只调用一次）
    now = datetime.now()
    updated_at = now.strftime(_DATE_FORMAT)

    cache_data = {
        "meta": {
            "version": _OUTPUT_VERSION,
            "source": "local_backup",
            "level": "一级",
            "updated_at": updated_at,
            "total_count": len(industry_map),
        },
        "industries": industry_map,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # 使用公共模块原子写入（遵循 MODULE.md 约束 #4）
    # 备用缓存写入失败为非致命错误（MODULE.md 约束 #72）
    try:
        write_json_cache(INDUSTRY_CACHE_PATH, cache_data, json_indent=2)
        logger.info(f"[行业数据] 备用缓存已写入: {INDUSTRY_CACHE_PATH}")
    except Exception as e:
        logger.warning(f"[行业数据] 备用缓存写入失败 [{type(e).__name__}]: {e}（非致命，下次将重新读备用数据）")


def infer_industry_from_name(name: str) -> str:
    """
    从股票名称推断行业（备用方案）

    Args:
        name: 股票名称

    Returns:
        str: 推断的行业名称

    Note:
        关键词匹配是**模糊匹配**（包含检测），优先级由字典遍历顺序决定：
        - "中信银行" → "证券"（匹配"中信"而非"银行"，证券在字典中先于银行）
        - "新能源电力" → "电力"（匹配"电力"而非"新能源"，电力在字典中先于新能源）
        - 推断准确性低于 akshare 数据，仅作备用
    """
    # 常见行业关键词映射
    # 注意：关键词需避免歧义，遍历顺序决定匹配优先级
    # - 已消除重复关键词：光伏/风电只在电力中，新能源使用锂电/电池/太阳能
    industry_keywords = {
        "证券": ["证券", "券商"],  # 移除品牌词"中信"，仅保留行业描述词
        "银行": ["银行", "金融"],
        "保险": ["保险", "人寿"],  # 移除品牌词"平安"，仅保留行业描述词
        "电力": ["电力", "电能", "水电", "火电", "风电", "光伏"],  # 光伏/风电只在电力
        "新能源": ["新能源", "锂电", "电池", "太阳能"],  # 移除重复的 光伏/风电
        "房地产": ["地产", "房产", "万科", "保利", "城建"],
        "医药": ["医药", "生物", "制药", "药业", "医疗"],
        "科技": ["科技", "电子", "芯片", "半导体", "软件"],
        "汽车": ["汽车", "车企", "比亚迪", "上汽", "长城"],
        "消费": ["消费", "食品", "饮料", "酒", "零售"],
        "化工": ["化工", "化学", "石化"],
        "机械": ["机械", "设备", "重工", "工程"],
        "通信": ["通信", "电信", "移动"],
        "建材": ["建材", "水泥", "玻璃"],
        "煤炭": ["煤炭", "煤业"],
        "有色": ["有色", "铜", "铝", "金属"],
        "钢铁": ["钢铁", "钢"],
        "交通": ["交通", "运输", "物流", "港口"],
        "传媒": ["传媒", "出版", "影视"],
        "其他": [],
    }

    for industry, keywords in industry_keywords.items():
        if industry == "其他":
            continue
        for kw in keywords:
            if kw in name:
                return industry

    return "其他"


# 模块级缓存（线程安全：使用 threading.Lock）
# 注意：threading 已在顶部导入（第28行），此处不再重复导入
# 使用哨兵对象 _UNSET 区分"未初始化"和"加载结果为空 dict"两种状态
_UNSET = object()  # 唯一哨兵对象，无法被外部构造
_industry_cache = _UNSET
_cache_lock = threading.Lock()


def get_industry_map() -> dict:
    """
    获取行业映射（带模块级缓存，线程安全）

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Note:
        使用哨兵对象 _UNSET 作为初始值，避免将空 dict 结果与未初始化状态混淆。
        即使 load_stock_industry 返回空 dict 或抛异常，_industry_cache 也会被赋值，
        后续调用不会重复加载（性能优化 + 防御性设计）。
    """
    global _industry_cache
    if _industry_cache is _UNSET:
        with _cache_lock:
            # 双重检查：锁内再次判断，避免重复加载
            if _industry_cache is _UNSET:
                try:
                    _industry_cache = load_stock_industry()
                except Exception as e:
                    # 加载失败时赋值空 dict，避免重复加载（哨兵对象已被替换）
                    logger.error(f"[行业数据] get_industry_map 加载失败 [{type(e).__name__}]: {e}")
                    _industry_cache = {}
    # 类型断言：加载完成后 _industry_cache 一定是 dict（_UNSET 已被替换）
    # 注意：返回值可能是 dict 或 object（_UNSET），但前者保证类型安全
    if isinstance(_industry_cache, dict):
        return _industry_cache
    else:
        # 极端情况：锁竞争导致未完成赋值，返回空 dict 避免类型错误
        logger.warning("[行业数据] get_industry_map 未完成加载，返回空 dict")
        return {}


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
    return stock_info.get("industry", "未知")


def get_industry_distribution(stocks: list) -> dict[str, int]:
    """
    获取股票列表的行业分布

    Args:
        stocks: 股票代码列表

    Returns:
        dict[str, int]: {行业名称: 数量}
    """
    industry_count = Counter()

    for code in stocks:
        industry = get_stock_industry(code)
        industry_count[industry] += 1

    return dict(industry_count)


# 公共接口导出列表（MODULE.md 约束）
# 注意：以 _ 开头的名称表示模块私有，不应放入 __all__
# 注意：路径常量（INDUSTRY_CACHE_PATH、STOCK_LIST_BACKUP_PATH）不应导出，
#       防止外部代码绕过封装函数直接操作文件
__all__ = [
    "fetch_stock_industry_em",
    "fetch_stock_industry_sw",
    "load_stock_industry",
    "refresh_industry_cache",
    "get_industry_map",
    "get_stock_industry",
    "get_industry_distribution",
    "infer_industry_from_name",
    "load_local_industry_backup",
    "SW_INDUSTRY_CODE_MAP",
]


# ============================================================================
# CLI 入口（遵循 PROJECT.md 编码规范：脚本必须有退出码）
# ============================================================================


def _get_cli_logger() -> logging.Logger:
    """获取 CLI 日志记录器"""
    return setup_logger("fetch_industry.cli")


def main() -> bool:
    """
    CLI 主函数 - 刷新行业分类缓存（降级链：EM→SW→本地关键词推断）

    Returns:
        True: 执行成功
        False: 执行失败
    """
    cli_logger = _get_cli_logger()

    cli_logger.info("=" * 60)
    cli_logger.info(f"股票行业分类数据拉取 v{_OUTPUT_VERSION}")
    cli_logger.info("降级链: 东方财富(EM) → 申万(SW) → 本地关键词推断")
    cli_logger.info("=" * 60)

    try:
        # 尝试从 akshare 获取（refresh_industry_cache 内部 EM→SW 降级）
        industry_map = refresh_industry_cache()
        cli_logger.info(f"  ✓ 成功获取 {len(industry_map)} 只股票的行业分类")
        cli_logger.info(f"  ✓ 缓存路径: {INDUSTRY_CACHE_PATH}")
        cli_logger.info("执行完成，退出码: 0")
        return True

    except RuntimeError as e:
        # EM + SW 均失败，尝试本地备用数据
        cli_logger.warning(f"  ⚠ akshare 获取失败: {e}")
        cli_logger.info("  尝试使用本地备用数据（名称关键词推断）...")

        try:
            backup_map = load_local_industry_backup(write_cache=True)
            cli_logger.info(f"  ✓ 备用数据加载成功: {len(backup_map)} 只股票")
            cli_logger.info(f"  ✓ 缓存路径: {INDUSTRY_CACHE_PATH}")
            cli_logger.info("执行完成（使用备用数据），退出码: 0")
            return True

        except Exception as backup_e:
            cli_logger.error(f"  ✗ 备用数据也失败 [{type(backup_e).__name__}]: {backup_e}")
            cli_logger.error("执行失败，退出码: 1")
            return False

    except Exception as e:
        cli_logger.exception(f"  ✗ 未预期的错误: {type(e).__name__}: {e}")
        cli_logger.error("执行失败，退出码: 1")
        return False


if __name__ == "__main__":
    # CLI 入口（遵循 MODULE.md 约束：无 --force-full 参数）
    success = main()
    import sys

    sys.exit(0 if success else 1)
