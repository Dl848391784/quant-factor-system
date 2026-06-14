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
- v3.1 (2026-06-14): SW 数据源恢复 + 防覆盖 + 重试 - 1) 自实现 _download_sw_industry_xls 用系统 CA bundle 调用 swsresearch.com（绕开 certifi 缺中间 CA 问题），SW 重新作为可用降级；2) _write_backup_cache 加防覆盖检查（meta.source ∈ {em_category, sw_category} 时拒绝写 local_backup），避免 2026-06-13 类型事故（EM+SW 双失败时静默覆盖真实数据）；3) 新增 _get_sw_ca_bundle/_SW_XLS_URL/_SYSTEM_CA_CANDIDATES 等常量；4) ak.stock_info_a_code_name 增加 3 次重试（深交所偶发 ConnectionReset by peer）
- v3.2 (2026-06-14): 代码清理（4项） - 1) 删除冗余的 _SW_TO_EM_MAP（key==value 全部相同），fetch_stock_industry_em 改为从 SW_INDUSTRY_CODE_MAP 派生有效行业名（非'其他'去重）；2) 删除 get_industry_map 末尾不可达的 isinstance else 分支（锁双重检查保证退出锁时 _industry_cache 必为 dict），改用 cast 保留类型安全；3) infer_industry_from_name 的 industry_keywords 字典提取为模块级常量 _INDUSTRY_KEYWORDS（避免每次调用重建）；4) load_stock_industry 缓存损坏分支删除"不通过 refresh_industry_cache"误导性注释（实际逻辑与缓存不存在分支完全一致）
- v3.3 (2026-06-14): Bug修复（3项） - 1) fetch_stock_industry_sw 函数中部重复 import pandas as pd 合并到函数顶部 import akshare as ak 处；2) refresh_industry_cache SW 失败 except 捕获范围收窄（只 try fetch_stock_industry_sw() 调用本身），避免内部抛出的"返回空数据"RuntimeError 被自己的 except Exception 二次包装、污染异常链类型信息；3) _write_backup_cache 读取现有缓存失败时不再直接 return，改为继续执行写入——读失败可能是 JSON 损坏，此时不应保护一个已损坏的文件
- v3.4 (2026-06-14): 日志精度调优（4项） - 1) fetch_stock_industry_em 内层循环逐板块 info → debug（31条噪音降级，循环后汇总 info 已足够体现关键节点）；2) load_stock_industry "缓存无更新时间标记" info → warning（缺 updated_at 是数据异常而非正常流程）；3) _write_backup_cache 防覆盖 warning 精简为单行（source+count），事故背景下沉到注释；4) main 两处成功分支补 top3 行业分布 debug 摘要（新增 _format_top3_industries 辅助函数），便于从日志快速发现"75% 其他"这类污染
- v3.5 (2026-06-14): 代码顺序与异常语义（3项） - 1) _INDUSTRY_KEYWORDS 移到 infer_industry_from_name 之前，遵循"先定义后使用"原则（旧写法虽因模块完全加载后才调用而无运行时错误，仍属阅读隐患）；2) _EM_INDUSTRY_NAMES 补充顺序依赖注释，明确遍历顺序等同于 SW_INDUSTRY_CODE_MAP 中真实行业条目（非 '其他'）的插入顺序；3) load_local_industry_backup 解析失败分支由 warning+return {} 改为 raise，让调用方区分"文件不存在"与"文件损坏解析失败"两种降级原因，load_stock_industry 两处降级点加 try/except 记录具体失败原因后返回空 dict 保持对外行为不变
- v3.6 (2026-06-14): 代码组织与日志精度（4项） - 1) _format_top3_industries 嵌套到 main 函数内部（仅 main 使用，无独立测试需求），与模块核心 API 物理隔离；2) infer_industry_from_name docstring 失效示例修正——旧"中信银行→证券"自 v2.6 移除"中信"关键词后已不可达，改为"生物科技→医药"（"生物"提前匹配医药行业的实际歧义场景）；3) refresh_industry_cache 用独立 em_error_msg/em_error_detail 变量替代旧 em_error 三元（旧三元依赖"em_error 为 None ⟺ EM 返回空 dict"的隐式等价，语义混乱），在每个分支显式赋值；4) load_stock_industry 最外层 except 块补全降级链并 return，不再 fall through 到"缓存不存在"分支（修正"缓存损坏却日志说不存在"的误导）
- v3.7 (2026-06-14): 重复日志消除、契约文档化与 DRY 重构（5项） - 1) fetch_stock_industry_em 删除最外层 except 包装，避免与内层 RuntimeError + 调用方 refresh_industry_cache 三处重复 logger.error；2) load_local_industry_backup docstring Returns 明确"文件不存在→空 dict / 解析失败→raise"两种返回行为对比，与 v3.5 双层 try/except 实现呼应；3) load_stock_industry 三处雷同降级链（缓存损坏 / 加载异常 / 缓存不存在）抽取为 _fallback_to_remote_or_backup(reason) 私有函数，三处分别传 reason 字符串区分日志入口；4) get_industry_map 删除不可达的 except 兜底块（load_stock_industry 已通过 _fallback_to_remote_or_backup 保证不抛异常），docstring 显式记录"不抛异常"契约；5) _get_sw_ca_bundle 返回类型从 str | bool 收紧为 str | Literal[True]，并在 docstring 强调 True 是 requests 库的约定（"使用 certifi 默认验证"），本模块不控制该路径的 CA 选择
- v3.8 (2026-06-14): 日志级别校准与可操作性增强（2项） - 1) refresh_industry_cache 中 EM 返回空 dict 的日志由 warning 升级为 error，并附"fetch_stock_industry_em 应在空结果时 raise RuntimeError，此处返回空 dict 属内部逻辑错误"的说明（这条路径触发意味着内部契约破裂，warning 级别低于事件严重程度）；2) load_stock_industry 中"刷新失败降级旧缓存"日志的冗余括号文字（"旧缓存（旧缓存）"）改为"旧缓存（{days_old}天前）"，运维可据此判断旧缓存的可信度
- v3.9 (2026-06-14): 异常诊断维度恢复与降级路径契约统一（4项） - 1) fetch_stock_industry_sw 单独捕获 _download_sw_industry_xls 的 requests.RequestException 与 ValueError/OSError 并分别打 error，让 SW 失败诊断保留"HTTP/SSL 失败 vs Excel 解析失败"两个维度（旧实现仅外层一条统一日志丢失维度）；2) _fallback_to_remote_or_backup 显式传 write_cache=True 并 docstring 注明"降级路径下也写缓存避免下次重复走完整链"是有意为之，与 main 调用风格一致；3) _fallback_to_remote_or_backup 删除重叠的"akshare 获取失败" warning（refresh_industry_cache 内部已有 EM warning + SW error 详尽记录，本层重复反而稀释信号），并在 docstring 加日志契约说明；4) main 由 except RuntimeError 改为 except Exception + isinstance(e, RuntimeError) 区分，让 load_local_industry_backup 解析失败时抛出的 JSONDecodeError/OSError 也能落入"未预期错误"分支（旧实现仅 RuntimeError 入备用降级分支，丢失非 RuntimeError 路径的语义）

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 logger（PROJECT.md 日志规范）
"""

import io
import json
import logging
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast


# 公共模块导入（遵循 MODULE.md 约束 #4）
# 条件导入：脚本直接运行时可能路径未配置
try:
    from data_fetchers.common import get_module_result_dir, get_stock_list_file, setup_logger, write_json_cache
except ImportError:
    from common import get_module_result_dir, get_stock_list_file, setup_logger, write_json_cache

# 版本号常量（MODULE.md 约束 #16）
_OUTPUT_VERSION = "3.9"

# 日期格式常量（避免写入和解析格式不一致）
_DATE_FORMAT = "%Y-%m-%d"

logger = logging.getLogger(__name__)

# 使用公共模块路径函数（遵循 MODULE.md 约束 #62）
RESULT_DIR = get_module_result_dir()
STOCK_LIST_BACKUP_PATH = get_stock_list_file()

# 行业数据缓存路径（输出到 result 目录，MODULE.md 约束 #2）
INDUSTRY_CACHE_PATH = RESULT_DIR / "stock_industry.json"

# SW 数据源 SSL 修复（v3.1, 2026-06-14）
# ----------------------------------------------------------------------------
# 问题: certifi 默认 CA bundle 不含 GeoTrust G2 TLS CN RSA4096 SHA256 2022 CA1，
#       导致 Python requests 调用 swsresearch.com 报 SSL: CERTIFICATE_VERIFY_FAILED。
#       但系统 CA bundle (/etc/pki/tls/cert.pem) 完整，能正常验证。
# 方案: 检测系统 CA bundle，如存在则在自定义 SW 拉取函数中使用，否则回退到 certifi。
# 不影响其他 akshare 端点（如东方财富、申万行业代码映射），仅作用于 SW xls 下载。
_SYSTEM_CA_CANDIDATES = [
    "/etc/pki/tls/cert.pem",  # RHEL/CentOS/AliLinux
    "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
    "/etc/ssl/cert.pem",  # macOS/Alpine
]
_SW_XLS_URL = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"
_SW_HTTP_TIMEOUT = 30  # 秒

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


# 东方财富行业板块名称（申万一级 → 东方财富板块名）
# 申万31个一级行业与东方财富板块名称基本一致（1:1 同名映射），
# 因此直接从 SW_INDUSTRY_CODE_MAP 派生：取所有非 '其他' 的行业名并去重。
# 东方财富通过 stock_board_industry_cons_em(symbol=板块名) 获取成分股。
#
# ⚠ 顺序依赖（v3.5 注释）：
#   dict.fromkeys 保留每个 value 首次出现的顺序，因此 _EM_INDUSTRY_NAMES 的遍历顺序
#   等同于 SW_INDUSTRY_CODE_MAP 中**真实行业条目**（非 '其他'）的插入顺序。
#   若调整 SW_INDUSTRY_CODE_MAP 中真实行业条目的相对位置，会同步改变 EM 板块的
#   遍历顺序，并影响 fetch_stock_industry_em 的拉取顺序与日志输出顺序。
#   '其他' 条目的位置（无论开头/中间/结尾）不影响结果，因为已被过滤。
_EM_INDUSTRY_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(name for name in SW_INDUSTRY_CODE_MAP.values() if name != "其他")
)

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
        - 东方财富板块名称与申万一级名称基本一致（见 _EM_INDUSTRY_NAMES，从 SW_INDUSTRY_CODE_MAP 派生）
        - 遍历31个板块约耗时30秒，每个板块间隔0.3秒防反爬
        - 返回的行业名称为申万一级标准（31个行业）
        - stock_board_industry_cons_em 不受 SSL 证书问题影响

    Raises:
        RuntimeError: 31 个板块全部失败时抛出
        其他异常: import / akshare 初始化错误等直接向上传递
            （v3.7 移除外层 except 包装：旧实现内层 raise RuntimeError 后又被外层
            except 捕获并 logger.error，与调用方 refresh_industry_cache 的日志合计
            会产生 3 条同类错误日志；现交由调用方统一记录）
    """
    import time

    import akshare as ak

    logger.info(f"[行业数据 v{_OUTPUT_VERSION}] 开始获取东方财富行业分类（31个板块）...")

    industry_map: dict = {}
    success_count = 0
    fail_count = 0

    for sw_name in _EM_INDUSTRY_NAMES:
        # SW 与 EM 同名，板块名 == 行业名（见 _EM_INDUSTRY_NAMES 定义注释）
        em_name = sw_name
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
            # v3.4: 逐板块降级为 debug——31 条 info 噪音过大，
            # 循环后的"获取完成"汇总 info 已足够体现关键节点
            logger.debug(f"[行业数据] EM板块 '{em_name}': {len(df)} 只股票")
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


def _get_sw_ca_bundle() -> str | Literal[True]:
    """选择 SW 数据源使用的 CA bundle（v3.1, 2026-06-14；v3.7 类型注解收紧）

    Returns:
        str: 系统 CA bundle 的绝对路径（如存在），requests.get(verify=<path>)
             直接使用该文件做证书校验
        True: 系统 CA 都不存在时回退——**这是 requests 库的约定**：
             requests.get(verify=True) ≡ "用 requests/certifi 的默认 CA"，
             此时 CA 选择由 requests/certifi 接管，**本模块不再控制**
             （在缺中间 CA 的环境下大概率失败但不会静默）

    Why:
        certifi 缺 GeoTrust G2 TLS CN 中间 CA，系统 CA 完整。优先用系统 CA。

    Note:
        v3.7 类型注解从 `str | bool` 收紧为 `str | Literal[True]`：
        强调 False 不在合法返回值集合内，使类型检查器（pyright/mypy）
        在调用方误判时能给出更准确的提示。
    """
    for path in _SYSTEM_CA_CANDIDATES:
        if Path(path).is_file():
            return path
    logger.warning("[行业数据] 未找到系统 CA bundle (%s)，回退 certifi（可能 SSL 失败）", _SYSTEM_CA_CANDIDATES)
    return True


def _download_sw_industry_xls() -> "Any":
    """直接下载 SW 行业分类 xls（绕开 akshare 内部 SSL 限制，v3.1, 2026-06-14）

    Returns:
        pd.DataFrame: 列与 ak.stock_industry_clf_hist_sw() 兼容
                     （symbol, industry_code, start_date, update_time）

    Raises:
        requests.RequestException: HTTP 错误或 SSL 失败
        ValueError: xls 解析失败

    Note:
        akshare.stock_industry_clf_hist_sw 内部用 requests.get(url) 默认 verify=certifi，
        在缺中间 CA 的环境下抛 SSLError。本函数用系统 CA bundle 重新实现下载，
        其余逻辑（pd.read_excel + rename）与 akshare 1.18 行为一致。
    """
    import pandas as pd
    import requests
    from akshare.utils.cons import headers as ak_headers

    ca_bundle = _get_sw_ca_bundle()
    logger.info("[行业数据] SW xls 下载中: %s (verify=%s)", _SW_XLS_URL, ca_bundle)
    response = requests.get(_SW_XLS_URL, headers=ak_headers, timeout=_SW_HTTP_TIMEOUT, verify=ca_bundle)
    response.raise_for_status()

    df = pd.read_excel(io.BytesIO(response.content), dtype={"股票代码": "str", "行业代码": "str"})
    df.rename(
        columns={
            "股票代码": "symbol",
            "计入日期": "start_date",
            "行业代码": "industry_code",
            "更新日期": "update_time",
        },
        inplace=True,
    )
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce").dt.date
    df["update_time"] = pd.to_datetime(df["update_time"], errors="coerce").dt.date
    return df


def fetch_stock_industry_sw() -> dict:
    """
    获取申万行业分类数据

    数据获取: _download_sw_industry_xls()（v3.1, 2026-06-14 起绕开 akshare SSL 问题）
    股票名称: ak.stock_info_a_code_name()（无 SSL 问题，仍用 akshare）

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Raises:
        requests.RequestException: SW xls HTTP/SSL 下载失败（v3.9 区分记录）
        ValueError / OSError: SW xls 解析失败（v3.9 区分记录）
        RuntimeError: 股票名称重试 3 次仍失败
        其他 Exception: 列校验等防御性失败，外层 except 兜底记录后 re-raise
    """
    try:
        import akshare as ak
        import pandas as pd
        import requests  # v3.9: 引入以便区分 _download_sw_industry_xls 的 RequestException

        logger.info(f"[行业数据 v{_OUTPUT_VERSION}] 开始获取申万行业分类...")

        # 获取申万行业分类历史数据（v3.1: 自实现 xls 下载, 系统 CA bundle 解决 SSL 问题）
        # v3.9: 单独捕获 _download_sw_industry_xls，区分 HTTP 错误（含 SSL 失败）
        # 与 Excel 解析错误，让 SW 失败诊断不再丢失维度（旧实现仅外层一条统一日志）
        try:
            industry_df = _download_sw_industry_xls()
        except requests.RequestException as http_e:
            # HTTP 失败（SSLError 是 RequestException 子类，会落到这里）
            logger.error(
                "[行业数据] SW xls 下载失败（HTTP/SSL）[%s]: %s",
                type(http_e).__name__,
                http_e,
            )
            raise
        except (ValueError, OSError) as parse_e:
            # pd.read_excel 解析失败（损坏 xls / IO 错误等）
            logger.error(
                "[行业数据] SW xls 解析失败 [%s]: %s",
                type(parse_e).__name__,
                parse_e,
            )
            raise

        # 列名校验（防御性编程）
        missing_cols = [col for col in _EXPECTED_INDUSTRY_COLS if col not in industry_df.columns]
        if missing_cols:
            raise KeyError(f"申万行业分类缺少必需列: {missing_cols}, 实际列: {list(industry_df.columns)}")

        # 日期格式转换（防御性编程）：确保 start_date 为 datetime 类型
        # 避免混合格式（如"20210101"和"2021-01-01"）导致排序错误
        industry_df["start_date"] = pd.to_datetime(industry_df["start_date"])

        # 获取每只股票的最新行业分类（按start_date降序）
        industry_df_latest = industry_df.sort_values("start_date", ascending=False).drop_duplicates(
            subset="symbol", keep="first"
        )

        # 获取股票名称映射（深交所偶发 ConnectionReset，重试 2 次）
        stock_names_df = None
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                stock_names_df = ak.stock_info_a_code_name()
                break
            except Exception as ne:
                last_err = ne
                logger.warning(
                    "[行业数据] stock_info_a_code_name 第%d次失败 [%s]: %s%s",
                    attempt + 1,
                    type(ne).__name__,
                    ne,
                    "，重试..." if attempt < 2 else "，放弃",
                )
                if attempt < 2:
                    import time as _t

                    _t.sleep(2 * (attempt + 1))
        if stock_names_df is None:
            raise RuntimeError("ak.stock_info_a_code_name 重试 3 次仍失败") from last_err

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
        # v3.9: 内层已对 HTTP/解析失败分别记录细粒度 error；这里再打一条
        # "akshare API 获取失败"作为 SW 整体失败标记，便于日志按"akshare API"
        # 关键字快速定位 SW 路径全部失败事件（非重复，提供不同抽象层视角）
        logger.error(f"[行业数据] akshare API 获取失败 [{type(e).__name__}]: {e}")
        raise  # 重新抛出原始异常


def _fallback_to_remote_or_backup(reason: str) -> dict:
    """三处降级链共用的私有函数（v3.7 提取，DRY）

    降级链：refresh_industry_cache(akshare) → load_local_industry_backup → 空 dict

    Args:
        reason: 触发降级的原因描述（用于日志区分入口，例如 "缓存不存在" / "缓存损坏"
                / "缓存加载异常"），仅作日志前缀，不影响降级行为本身。

    Returns:
        dict: 行业映射；akshare 与本地备用都失败时返回空 dict（保持对外契约不变）

    Note:
        - 不抛异常：所有降级失败都吞掉并返回空 dict，下游调用方（get_industry_map）
          因此可以假设 load_stock_industry 不抛异常，简化其逻辑
        - 与 v3.5 的"备用文件不存在 vs 解析失败"语义保持一致：解析失败的异常通过
          load_local_industry_backup raise 上来，被这里的 except 吃掉记录 error
        - **write_cache=True 是有意为之**（v3.9 显式传参）：
          降级路径下也写入缓存，避免下次 load_stock_industry 又重复走完
          整条 EM→SW→backup 链；与 main 的 load_local_industry_backup(write_cache=True)
          调用一致，统一降级路径的副作用契约
        - **日志契约**（v3.9）：refresh_industry_cache 内部已对 EM/SW 各自失败
          打 warning/error，本函数不再补充重叠的 "akshare 获取失败" warning，
          仅在最终降级到空 dict 时补 error；这样同一次失败不会出现层级混乱的
          重复日志（旧实现：本函数 warning + refresh 内部 error，两层语义同
          一事件）
    """
    logger.info(f"[行业数据] {reason}，尝试重新获取 akshare 数据...")
    try:
        return refresh_industry_cache()
    except Exception:
        # v3.9: 不再补 "akshare 获取失败" warning——refresh_industry_cache 内部
        # 已有 EM warning + SW error 详尽记录，本层重复反而稀释信号
        try:
            # v3.9: write_cache=True 显式传参（虽与默认值相同），避免与 main 调用风格不一致
            return load_local_industry_backup(write_cache=True)
        except Exception as backup_e:
            # v3.5: 区分备用解析失败 vs 文件不存在，前者会 raise 到这里
            logger.error(
                f"[行业数据] 备用数据解析失败 [{type(backup_e).__name__}]: {backup_e}，"
                f"返回空 dict（下游需具备空数据兜底）"
            )
            return {}


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
                # v3.7: 三处共用的降级链抽取为 _fallback_to_remote_or_backup
                return _fallback_to_remote_or_backup(reason="缓存损坏")

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
                            # v3.8: 括号内"旧缓存"文字与前文重复，改为过期天数
                            # 提供更具可操作性的信息（运维可据此判断旧缓存可信度）
                            logger.warning(
                                f"[行业数据] 刷新失败 [{type(e).__name__}]: {e}，降级使用旧缓存（{days_old}天前）"
                            )
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

            # updated_at 不存在（空字符串）：缓存缺时间戳是数据异常，warning 而非 info（v3.4）
            logger.warning(f"[行业数据] 缓存无更新时间标记（数据异常），从缓存加载: {len(industries)} 只股票")
            return industries

        except Exception as e:
            # v3.6: 缓存加载异常时直接走降级链并 return，不再 fall through 到
            # "缓存不存在"分支（旧控制流会输出"缓存不存在，尝试获取 akshare..."的
            # 误导日志，实际情况是缓存文件存在但 JSON 解析失败）
            logger.warning(f"[行业数据] 缓存加载失败 [{type(e).__name__}]: {e}")
            # v3.7: 三处共用的降级链抽取为 _fallback_to_remote_or_backup
            return _fallback_to_remote_or_backup(reason="缓存加载异常")

    # 缓存不存在，显式降级：先尝试 akshare，失败后用备用数据
    # v3.7: 三处共用的降级链抽取为 _fallback_to_remote_or_backup
    return _fallback_to_remote_or_backup(reason="缓存不存在")


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
    # v3.6: 独立的 em_error_msg 变量替代"em_error is None ⟺ EM返回空"的隐式推理。
    # 旧三元 `f"EM [{type(em_error).__name__}]" if em_error else "EM [返回空数据]"`
    # 逻辑上正确（依赖"em_error 为 None ⟺ EM返回空dict"的隐含等价），但语义混乱：
    # 读者需推理两个分支是否真的互斥。改为在每个分支显式赋值，意图直观。
    em_error_msg = "EM [未执行]"  # 防御性默认（不应被读到，因 SW 失败前必经过 EM 分支）
    em_error_detail = "EM: 未执行"

    try:
        industry_map = fetch_stock_industry_em()
        if industry_map:
            source = "em_category"
            logger.info("[行业数据] 东方财富数据获取成功，使用 EM 数据源")
        else:
            # EM 返回空 dict（不应发生，fetch_stock_industry_em 会抛异常）
            # v3.8: warning → error，匹配事件严重程度——这条路径触发意味着
            # fetch_stock_industry_em 内部契约破裂（应在 industry_map 为空时
            # raise RuntimeError，参见该函数 L226-229），属于内部逻辑错误，
            # 不是预期的降级路径
            logger.error(
                "[行业数据] 东方财富返回空数据但未抛异常 —— "
                "fetch_stock_industry_em 应在空结果时 raise RuntimeError，"
                "此处返回空 dict 属内部逻辑错误；继续降级到 SW 数据源"
            )
            em_error_msg = "EM [返回空数据]"
            em_error_detail = "EM: 返回空数据（内部逻辑错误，应 raise RuntimeError）"
    except Exception as em_e:
        em_error_msg = f"EM [{type(em_e).__name__}]"
        em_error_detail = f"EM: {type(em_e).__name__}: {em_e}"
        logger.warning("[行业数据] 东方财富获取失败 [%s]: %s，尝试 SW 数据源...", type(em_e).__name__, str(em_e))

    # 2. EM 失败时尝试申万数据源
    if industry_map is None:
        # 异常捕获范围收窄（v3.3）：只 try fetch_stock_industry_sw() 本身，
        # 不把"返回空数据"的 RuntimeError 包到同一 except，
        # 避免它被自己的 except Exception 二次包装并污染异常链类型信息
        try:
            industry_map = fetch_stock_industry_sw()
        except Exception as sw_e:
            logger.error("[行业数据] SW 获取失败 [%s]: %s", type(sw_e).__name__, str(sw_e))
            raise RuntimeError(f"行业数据获取失败: {em_error_msg} + SW [{type(sw_e).__name__}]") from sw_e

        if industry_map:
            source = "sw_category"
            logger.info("[行业数据] 申万数据获取成功（EM 失败后的备用）")
        else:
            logger.error("[行业数据] SW 返回空数据")
            raise RuntimeError(f"行业数据获取失败: {em_error_detail} + SW: 返回空数据") from None

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
        dict: 基本的行业映射（主要行业分类）。**特殊返回**：
            - 文件不存在 → 返回空 dict（正常降级路径，write_cache 参数被忽略）
            - 文件存在但解析失败 → **不返回**，而是抛出原始异常（v3.5 引入，
              让调用方区分"文件不存在"与"文件损坏"两种降级原因，分别记录日志）

    Raises:
        json.JSONDecodeError / OSError 等: 文件存在但解析失败（v3.5）

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
            # v3.5: 改 raise，让调用方区分"文件不存在"vs"文件损坏解析失败"
            # 旧写法只 warning + return {} 会让两种完全不同的失败原因合流为同一行日志，
            # 调用方（load_stock_industry / main）无法准确记录降级原因。
            logger.warning(f"[行业数据] 本地备用文件解析失败 [{type(e).__name__}]: {e} (path={stock_list_path})")
            raise
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

        v3.1 防覆盖（2026-06-14）：
        如果现有缓存 meta.source ∈ {em_category, sw_category}（真实数据源），
        则拒绝用 local_backup 覆盖。这避免历史教训重演：
        2026-06-13 事故中，EM+SW 同时失败时本函数静默覆盖了 6-12 拉取的 5585 只
        真实数据，下游所有行业因子都污染成 75% 的"其他"。
    """
    # v3.1 防覆盖检查：现有缓存如果是真实数据源，拒绝写入 local_backup
    # 历史背景（仅注释，不进日志）：2026-06-13 事故中 EM+SW 同时失败，本函数静默
    # 覆盖了 6-12 拉取的 5585 只真实数据，下游所有行业因子被污染成 75% "其他"
    if INDUSTRY_CACHE_PATH.exists():
        try:
            with open(INDUSTRY_CACHE_PATH, encoding="utf-8") as f:
                existing = json.load(f)
            existing_source = existing.get("meta", {}).get("source", "")
            existing_count = existing.get("meta", {}).get("total_count", 0)
            if existing_source in {"em_category", "sw_category"}:
                logger.warning(
                    "[行业数据] 拒绝 local_backup 覆盖真实缓存 (source=%s, count=%d)",
                    existing_source,
                    existing_count,
                )
                return
        except Exception as e:
            # 读取失败（如 JSON 损坏）：不应保护一个已损坏的文件，
            # 继续走下面的写入逻辑，用本次 local_backup 数据覆盖损坏缓存（v3.3 修复）
            logger.warning(
                "[行业数据] 读取现有缓存失败 [%s]: %s，缓存可能已损坏，继续写入 local_backup 覆盖",
                type(e).__name__,
                e,
            )

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


# 名称关键词→行业映射（infer_industry_from_name 使用）
# 提取为模块级常量（v3.2，2026-06-14）：避免每次调用重建字典
# v3.5 (2026-06-14)：移到 infer_industry_from_name 之前，遵循"先定义后使用"原则
#   （旧写法虽因模块完全加载后函数才被调用而无运行时错误，仍属阅读隐患）
# 注意：关键词需避免歧义，遍历顺序决定匹配优先级
# - 已消除重复关键词：光伏/风电只在电力中，新能源使用锂电/电池/太阳能
# - 移除品牌词:"中信"（与证券歧义）、"平安"（与保险歧义）
_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
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


def infer_industry_from_name(name: str) -> str:
    """
    从股票名称推断行业（备用方案）

    Args:
        name: 股票名称

    Returns:
        str: 推断的行业名称

    Note:
        关键词匹配是**模糊匹配**（包含检测），优先级由 _INDUSTRY_KEYWORDS 字典遍历顺序决定：
        - "新能源电力" → "电力"（匹配"电力"而非"新能源"，电力在字典中先于新能源）
        - "生物科技" → "医药"（"生物"是医药关键词且医药行业先于科技遍历，
          虽然名称含"科技"二字也不会匹配到科技行业）
        - 推断准确性低于 akshare 数据，仅作备用
        - v3.6: 旧示例"中信银行→证券"已失效（v2.6 已从 _INDUSTRY_KEYWORDS 移除"中信"
          品牌词以避免歧义），改用当前实际存在的关键词冲突示例
    """
    # 使用模块级常量 _INDUSTRY_KEYWORDS（v3.2 提取，避免每次调用重建字典）
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
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
_industry_cache: Any = _UNSET
_cache_lock = threading.Lock()


def get_industry_map() -> dict:
    """
    获取行业映射（带模块级缓存，线程安全）

    Returns:
        dict: {股票代码: {name, industry, industry_code}}

    Note:
        使用哨兵对象 _UNSET 作为初始值，避免将空 dict 结果与未初始化状态混淆。

        线程安全保证：双重检查锁（DCL）+ Python GIL 保证赋值原子性。
        退出锁后 _industry_cache 必为 dict（要么 load 成功的 dict，要么空 dict），
        故无需额外的 isinstance 兜底分支（v3.2 移除）。

        v3.7: 删除原 except 兜底块（不可达代码）——load_stock_industry 内部所有
        失败路径已通过 _fallback_to_remote_or_backup 转为返回空 dict 不抛异常，
        此处的 try/except 永远不会进入 except 分支。契约：
        **load_stock_industry 必返回 dict（可能为空），不抛任何异常**。
        若未来该契约改变，此处必须同步加回 try/except。
    """
    global _industry_cache
    if _industry_cache is _UNSET:
        with _cache_lock:
            # 双重检查：锁内再次判断，避免重复加载
            if _industry_cache is _UNSET:
                # load_stock_industry 契约保证：返回 dict 或空 dict，不抛异常
                _industry_cache = load_stock_industry()
    # 退出 DCL 后 _industry_cache 必为 dict（_UNSET 已被替换为 dict 或 {}）
    return cast(dict, _industry_cache)


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

    # v3.6: _format_top3_industries 嵌套到 main 内部，与模块核心 API 物理隔离
    # （仅 main 使用，无独立测试需求；嵌套消除了模块级命名空间污染）
    def _format_top3_industries(industry_map: dict) -> str:
        """格式化 industry_map 的 top3 行业分布（数据质量摘要辅助）

        空 dict 返回 "(空)"，缺 industry 字段降级为 "未知"
        """
        if not industry_map:
            return "(空)"
        counter: Counter = Counter()
        for info in industry_map.values():
            counter[info.get("industry", "未知") if isinstance(info, dict) else "未知"] += 1
        return ", ".join(f"{name}({cnt})" for name, cnt in counter.most_common(3))

    cli_logger = _get_cli_logger()

    cli_logger.info("=" * 60)
    cli_logger.info(f"股票行业分类数据拉取 v{_OUTPUT_VERSION}")
    cli_logger.info("降级链: 东方财富(EM) → 申万(SW) → 本地关键词推断")
    cli_logger.info("=" * 60)

    try:
        # 尝试从 akshare 获取（refresh_industry_cache 内部 EM→SW 降级）
        industry_map = refresh_industry_cache()
        cli_logger.info(f"  ✓ 成功获取 {len(industry_map)} 只股票的行业分类")
        # v3.4: 行业 top3 分布摘要，便于从日志快速判断数据质量
        cli_logger.debug(f"  · top3 行业分布: {_format_top3_industries(industry_map)}")
        cli_logger.info(f"  ✓ 缓存路径: {INDUSTRY_CACHE_PATH}")
        cli_logger.info("执行完成，退出码: 0")
        return True

    except Exception as e:
        # v3.9: 由 except RuntimeError 改为 except Exception，配合 isinstance 区分。
        # 旧实现仅捕获 RuntimeError（refresh_industry_cache 的契约异常），
        # 但 load_local_industry_backup 的解析失败抛 json.JSONDecodeError /
        # OSError 等非 RuntimeError 异常会落入"未预期错误"分支，丢失"备用降级"
        # 的正确语义；现统一捕获后通过 isinstance 区分两类失败入口。
        if isinstance(e, RuntimeError):
            # EM + SW 均失败，尝试本地备用数据（refresh_industry_cache 契约异常）
            cli_logger.warning(f"  ⚠ akshare 获取失败: {e}")
            cli_logger.info("  尝试使用本地备用数据（名称关键词推断）...")

            try:
                backup_map = load_local_industry_backup(write_cache=True)
                cli_logger.info(f"  ✓ 备用数据加载成功: {len(backup_map)} 只股票")
                # v3.4: 备用数据同样补 top3 摘要——可立刻发现"75% 其他"这类污染
                cli_logger.debug(f"  · top3 行业分布: {_format_top3_industries(backup_map)}")
                cli_logger.info(f"  ✓ 缓存路径: {INDUSTRY_CACHE_PATH}")
                cli_logger.info("执行完成（使用备用数据），退出码: 0")
                return True

            except Exception as backup_e:
                cli_logger.error(f"  ✗ 备用数据也失败 [{type(backup_e).__name__}]: {backup_e}")
                cli_logger.error("执行失败，退出码: 1")
                return False
        else:
            # 非 RuntimeError：refresh_industry_cache 契约外的异常（import 错误、
            # KeyboardInterrupt 上层、未捕获的内部 bug 等），不应静默走备用路径
            cli_logger.exception(f"  ✗ 未预期的错误: {type(e).__name__}: {e}")
            cli_logger.error("执行失败，退出码: 1")
            return False


if __name__ == "__main__":
    # CLI 入口（遵循 MODULE.md 约束：无 --force-full 参数）
    success = main()
    import sys

    sys.exit(0 if success else 1)
