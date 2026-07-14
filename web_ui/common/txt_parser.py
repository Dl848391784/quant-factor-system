"""web_ui/common/txt_parser.py

v0.4.8 R4: 解析 ob_quality txt 报告, 补全 web_ui 字段
H1.1 严守: 不修改 data_loaders / sections.py, web_ui 内部读 txt 报告
          (txt 是 summary 已生成的展示产物, 不是 Parquet/JSON 数据源)

数据源: summary/result/ob_quality/factor_summary_report_<latest>.txt

字段:
  - 权重综合得分 (composite_score)
  - 选出股票数 (top_n) + 候选池 (stocks_on_date)
  - 振幅过滤 (excluded_by_amplitude)
  - 覆盖率过滤 (excluded_by_coverage)
  - 方向处理说明 / 反向因子列表 (flipped_factors)
  - 第九节: 30 段 × 12 选股日 胜率矩阵
  - 最佳段 + 逐日胜率
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from paths import PROJECT_ROOT


# 路径: 复用 paths 模块定义 (H7 路径导入规则)
def _get_obq_txt_root() -> Path:
    """web_ui 内部从 paths 模块获取 ob_quality txt 报告根目录"""
    return PROJECT_ROOT / "summary" / "result" / "ob_quality"


def _find_latest_txt(date: str | None = None) -> Path | None:
    """查找 ob_quality txt 报告.

    Args:
        date: YYYY-MM-DD 日期. 若指定, 优先返回该日期的报告文件;
              若该日期不存在则 fallback 到最新文件 (保持旧行为兼容).
              None = 返回最新文件 (旧行为).
    """
    txt_root = _get_obq_txt_root()
    if not txt_root.exists():
        return None
    if date:
        exact = txt_root / f"factor_summary_report_{date}.txt"
        if exact.exists():
            return exact
        # date 指定的报告不存在, fallback 到最新 (保持旧行为兼容)
    txt_files = sorted(txt_root.glob("factor_summary_report_*.txt"), reverse=True)
    return txt_files[0] if txt_files else None


def parse_obq_section_8_meta(logger: logging.Logger, date: str | None = None) -> dict:
    """v0.4.8 R4: 解析第八节 meta 字段 (权重综合得分/选出股票数/振幅过滤/覆盖率过滤/反向因子)

    Returns:
        {
            "composite_score": float,
            "top_n": int,
            "stocks_on_date": int,
            "excluded_by_amplitude": int,
            "excluded_by_coverage": int,
            "flipped_factors": list[str],
        }
        任意字段缺失时该字段为 None
    """
    latest = _find_latest_txt(date)
    if latest is None:
        logger.debug("ob_quality txt 报告不存在")
        return {}

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return {}

    result: dict = {}

    # 权重综合得分: 0.5714
    m = re.search(r"权重综合得分[::]\s*([\d.]+)", content)
    if m:
        result["composite_score"] = float(m.group(1))

    # 选出股票数: 30 只（共 61 只股票）
    m = re.search(r"选出股票数[::]\s*(\d+)\s*只.*?(\d+)\s*只", content)
    if m:
        result["top_n"] = int(m.group(1))
        result["stocks_on_date"] = int(m.group(2))

    # 振幅过滤: 排除 0 只股票（振幅 < 1.00%，不可交易的一字板涨停股）
    m = re.search(r"振幅过滤[::]\s*排除\s*(\d+)\s*只股票?（([^）]+)）", content)
    if m:
        result["excluded_by_amplitude"] = int(m.group(1))
        result["amplitude_detail"] = m.group(2).strip()

    # 覆盖率过滤: 排除 15 只股票（覆盖率 < 50%，缺失高权重因子导致综合因子值不可信）
    m = re.search(r"覆盖率过滤[::]\s*排除\s*(\d+)\s*只股票?（([^）]+)）", content)
    if m:
        result["excluded_by_coverage"] = int(m.group(1))
        result["coverage_detail"] = m.group(2).strip()

    # 反向因子列表: ['amplitude', 'interaction_amplitude__ret3d_abs']
    m = re.search(r"反向因子.*?\[([^\]]+)\]", content)
    if m:
        # 解析 ['amplitude', 'interaction_amplitude__ret3d_abs'] 格式
        factors_str = m.group(1)
        flipped = re.findall(r"'([^']+)'", factors_str)
        if flipped:
            result["flipped_factors"] = flipped

    logger.info("ob_quality txt 第八节 meta 解析: %s", result)
    return result


def parse_obq_section_9_matrix(logger: logging.Logger, date: str | None = None) -> dict | None:
    """v0.4.8 R4: 解析第九节 30 段 × 12 选股日 胜率矩阵

    Returns:
        {
            "dates": [str, ...],  # 12 选股日 (06-15, 06-16, ...)
            "segments": [
                {
                    "label": "S1", "win_rates": [46.3, ...],  # 12 选股日胜率
                    "merged": 46.3,  # 合并胜率
                },
                ...
            ],
            "best_segment": {"label": "S7", "merged": 59.6},
        }
        None: 解析失败
    """
    latest = _find_latest_txt(date)
    if latest is None:
        return None

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return None

    # 找到九节起始
    section9_match = re.search(
        r"九、ob_quality 全管线 30分段胜率汇总.*?\n(.*?)(?=^十、|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section9_match:
        logger.debug("ob_quality txt 第九节未找到")
        return None

    section9_text = section9_match.group(1)

    # 日期行: "段 06-15 06-16 ... 合并"
    date_match = re.search(r"段\s+((?:\d{2}-\d{2}\s+)+)\S*合并", section9_text)
    if not date_match:
        return None
    dates = date_match.group(1).split()

    # 段行: "S1 0% 75% 40% ... 46.3%"  30 行
    # 注: txt 第九节每行以 "  S1" 前导空格开头, 不能用 ^ (默认匹配字符串开头, 不是行首)
    # 修复: 原正则 (?:\d+%\s+)+ 不匹配 "--" 占位符 (某选股日该段无股票时 txt 输出 --),
    #   导致含 -- 的整行被丢弃 (2026-07-14 报告 11/30 段丢失). 改为 (?:\d+%|--)\s+ 同时匹配
    segments = []
    for line_match in re.finditer(r"(S\d+)\s+((?:(?:\d+%|--)\s+)+)(\d+\.\d+)%\s*$", section9_text, re.MULTILINE):
        label = line_match.group(1)
        raw_rates = line_match.group(2).split()
        # "--" = 无数据, 用 None 表示 (Chart.js parseFloat(null)->NaN->0, 不丢段)
        win_rates = [float(r.rstrip("%")) if r != "--" else None for r in raw_rates]
        merged = float(line_match.group(3))
        segments.append({"label": label, "win_rates": win_rates, "merged": merged})

    # 最佳段: "最佳段: S7 (合并胜率 59.6%)"
    best_match = re.search(r"最佳段[::]\s*(S\d+).*?(\d+\.\d+)\s*%", section9_text)
    best_segment = None
    if best_match:
        best_segment = {
            "label": best_match.group(1),
            "merged": float(best_match.group(2)),
        }

    # 逐日胜率: 找 "S7 逐日胜率:" 段
    best_label_pattern = re.escape(best_match.group(1)) if best_match else r"S\d+"
    daily_match = re.search(
        rf"{best_label_pattern} 逐日胜率[::].*?(?=\n\n|\Z)",
        section9_text,
        re.DOTALL,
    )
    daily_rates: dict[str, str] = {}
    if daily_match:
        for line in daily_match.group(0).split("\n"):
            m = re.match(r"\s*(\d{2}-\d{2}):\s*(\d+/\d+\s*=\s*[\d.]+%)", line)
            if m:
                daily_rates[m.group(1)] = m.group(2).strip()

    result = {
        "dates": dates,
        "segments": segments,
        "best_segment": best_segment,
        "daily_rates": daily_rates,
    }
    logger.info(
        "ob_quality txt 第九节矩阵解析: %d 段 × %d 日, 最佳段 %s",
        len(segments),
        len(dates),
        best_segment,
    )
    return result


def parse_obq_intraday_fallback(logger: logging.Logger, date: str | None = None) -> dict:
    """v0.4.8 R6: 解析 ob_quality txt 十·fallback 段 (操作规则 + 历史胜率参考)

    Returns:
        {
            "operation_rules": [
                {"scenario": "高开 (gap > +0.5%)", "action": "9:25 集合竞价直接卖出 ...", "hit_rate": "23/28 = 82.1%"},
                ...
            ],
            "history_stats": [
                {"scenario": "高开开盘卖", "win_rate": "23/28 = 82.1%", "avg_ret": "+1.75%", "delta": "增厚 -1.15pp"},
                ...
            ],
            "sample_size": "122 只",
            "confidence": "统计置信度较高",
        }
        解析失败 → {}
    """
    latest = _find_latest_txt(date)
    if latest is None:
        return {}

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return {}

    result: dict = {}

    # 找到十·fallback 段
    # 修复: 原正则硬编码 "S7", 但最佳段不总是 S7 (历史报告有 S9),
    #   导致 S9 报告此函数返回空 {}. 改为 S\d+ 通配
    fallback_match = re.search(
        r"^十、S\d+ 段日内操作建议.*?【操作规则】(.*?)【历史胜率参考(.*?)\Z",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not fallback_match:
        logger.debug("ob_quality txt 十·fallback 段未找到")
        return {}

    rules_text = fallback_match.group(1)
    history_text = fallback_match.group(2)

    # 操作规则: 4 行格式 "  场景 (条件): 行动 + 历史胜率 (n=N)"
    # 例: "  高开 (gap > +0.5%): 9:25 集合竞价直接卖出 — D+1 开盘价 > 前一日收盘价, 历史 23/28 = 82.1% 命中 (n=28)"
    operation_rules = []
    for line in rules_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("【"):
            continue
        # 解析: "场景 (条件): 行动 ... 胜率 (n=N)"
        # 注: txt 实际用半角 "(" 而非全角 "（", 正则同时支持
        m = re.match(
            r"^([^:(（(]+)[\(（]([^\)）]+)[\)）][::]\s*(.+?)(?:\s+历史\s*([\d./%\s]+?))?\s*(?:\(n\s*=\s*(\d+)\))?\s*$",
            line,
        )
        if m:
            operation_rules.append(
                {
                    "scenario": m.group(1).strip(),
                    "condition": m.group(2).strip(),
                    "action": m.group(3).strip(),
                    "hit_rate": m.group(4).strip() if m.group(4) else None,
                    "sample_n": int(m.group(5)) if m.group(5) else None,
                }
            )
    result["operation_rules"] = operation_rules

    # 历史胜率: 简单行 "  场景: 胜率, 详情 ..."
    # 例: "  高开开盘卖: 23/28 = 82.1% 胜率, 均收 +1.75% (vs 死等尾盘 +2.89%, 增厚 -1.15pp)"
    history_stats = []
    for line in history_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("【") or "样本量" in line or "✅" in line:
            continue
        m = re.match(r"^([^:：]+)[:：]\s*(.+)$", line)
        if m:
            history_stats.append(
                {
                    "scenario": m.group(1).strip(),
                    "detail": m.group(2).strip(),
                }
            )
    result["history_stats"] = history_stats

    # 样本量 + 置信度
    sample_match = re.search(r"样本量\s*(\d+)\s*只", history_text)
    if sample_match:
        result["sample_size"] = f"{sample_match.group(1)} 只"
    confidence_match = re.search(r"(统计置信度.+)", history_text)
    if confidence_match:
        result["confidence"] = confidence_match.group(1).strip()

    logger.info(
        "ob_quality txt 十·fallback 解析: %d 操作规则, %d 历史胜率",
        len(operation_rules),
        len(history_stats),
    )
    return result


def parse_obq_correlation(logger: logging.Logger, date: str | None = None) -> dict | None:
    """v0.4.8 R9: 解析 ob_quality txt 第 3 节 因子相关性矩阵

    Returns:
        {
            "selected_factors": ["amplitude", "interaction_amplitude__ret3d_abs", ...],
            "matrix": {
                "amplitude": {"amplitude": 1.00, "interaction_amplitude__ret3d_abs": 0.80},
                "interaction_amplitude__ret3d_abs": {"amplitude": 0.80, "interaction_amplitude__ret3d_abs": 1.00},
            },
            "abbrev": {"amp": "amplitude", ...},
            "high_corr_pairs": [{"factor1": "amplitude", "factor2": "...", "corr": 0.80, "dim1": "volatility", "dim2": "..."}],
        }
        None: 解析失败
    """
    latest = _find_latest_txt(date)
    if latest is None:
        return None

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return None

    # 找到第三节起始
    section3_match = re.search(
        r"三、因子相关性矩阵.*?\n(.*?)(?=^四、|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section3_match:
        logger.debug("ob_quality txt 第三节未找到")
        return None

    section3_text = section3_match.group(1)

    # 选中因子: "(选中因子相关性矩阵, 共 N 个因子)"
    factors_match = re.search(r"共\s*(\d+)\s*个因子", section3_text)
    if not factors_match:
        return None

    lines = section3_text.split("\n")
    # 矩阵行: 第一行是列名, 数据行第一列是因子名 (其余是数字)
    # 跳过 ( 共 N 个因子) 注释
    # 跳过 "------" 分隔线
    col_names: list[str] = []
    matrix: dict[str, dict[str, float]] = {}
    in_matrix = False  # 进入矩阵数据区标志
    for i, line in enumerate(lines):
        if "共" in line and "个因子" in line:
            continue
        if "------" in line:
            in_matrix = True  # 第一个 "------" 之后是列名行
            continue
        if not in_matrix:
            continue
        tokens = line.split()
        if not tokens:
            continue
        if not col_names:
            # 列名行: 全部 a-z A-Z 0-9 短词 (skip 中文 "因子")
            col_tokens = [t for t in tokens if t != "因子"]
            if len(col_tokens) > 0 and all(re.match(r"^[a-zA-Z0-9_]+$", t) for t in col_tokens):
                col_names = col_tokens
        else:
            # 数据行: 第一列因子名, 后面是数字
            # 注: 因子名可能含数字 (interaction_amplitude__ret3d_abs)
            row_name = tokens[0]
            if not re.match(r"^[a-zA-Z0-9_]+$", row_name):
                continue
            row_values = []
            for t in tokens[1:]:
                try:
                    row_values.append(float(t))
                except ValueError:
                    break
            if len(row_values) == len(col_names):
                matrix[row_name] = dict(zip(col_names, row_values))

    selected_factors = list(matrix.keys())

    # 缩写对照表
    abbrev: dict[str, str] = {}
    in_abbrev = False
    for line in lines:
        if line.strip().startswith("【缩写对照表】"):
            in_abbrev = True
            continue
        if in_abbrev:
            if line.strip().startswith("【") or line.strip().startswith("-"):
                break
            m = re.match(r"^\s+(\S+)\s+=\s+(\S+)\s*$", line)
            if m:
                abbrev[m.group(1)] = m.group(2)

    # 跨维度高相关因子对
    high_corr_pairs: list[dict] = []
    in_pairs = False
    for line in lines:
        if "跨维度高相关因子对" in line:
            in_pairs = True
            continue
        if in_pairs:
            if "------" in line or "【" in line:
                break
            m = re.match(
                r"^\s*-\s*(\S+?)\[([^\]]+)\]\s+vs\s+(\S+?)\[([^\]]+)\]:\s*([\d.-]+)\s*$",
                line,
            )
            if m:
                high_corr_pairs.append(
                    {
                        "factor1": m.group(1),
                        "dim1": m.group(2),
                        "factor2": m.group(3),
                        "dim2": m.group(4),
                        "corr": float(m.group(5)),
                    }
                )

    if not matrix:
        return None
    return {
        "selected_factors": selected_factors,
        "matrix": matrix,
        "abbrev": abbrev,
        "high_corr_pairs": high_corr_pairs,
    }


def parse_obq_filter(logger: logging.Logger, date: str | None = None) -> dict | None:
    """v0.4.8 R9: 解析 ob_quality txt 第 4 节 因子筛选结果

    Returns:
        {
            "selected_factors": [{"name": "amplitude", "icir": 0.65, "weight": 75.0}, ...],
            "note": "权重来自...",
            "high_corr_threshold": 0.7,
            "excluded": [{"name": "rsi", "reasons": ["long_return=-27.3%<3%", ...]}, ...],
        }
        None: 解析失败
    """
    latest = _find_latest_txt(date)
    if latest is None:
        return None

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return None

    section4_match = re.search(
        r"四、因子筛选结果.*?\n(.*?)(?=^五、|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section4_match:
        return None

    section4_text = section4_match.group(1)
    result: dict = {}

    # 选中因子: "- 选中因子: amplitude(ICIR=0.65,权重=75.0%), ..."
    sel_match = re.search(r"选中因子[::]\s*(.+?)(?=\n  -|\n  高相关|\n  剔除|\Z)", section4_text, re.DOTALL)
    if sel_match:
        selected = []
        for m in re.finditer(r"(\S+?)\(ICIR=([\d.-]+),权重=([\d.]+)%\)", sel_match.group(1)):
            selected.append(
                {
                    "name": m.group(1),
                    "icir": float(m.group(2)),
                    "weight": float(m.group(3)),
                }
            )
        result["selected_factors"] = selected

    # 注 + 阈值
    note_match = re.search(r"注[::]\s*(.+?)(?=\n|\Z)", section4_text)
    if note_match:
        result["note"] = note_match.group(1).strip()
    thresh_match = re.search(r"高相关阈值[::]\s*([\d.]+)", section4_text)
    if thresh_match:
        result["high_corr_threshold"] = float(thresh_match.group(1))

    # 剔除因子
    excluded = []
    in_excluded = False
    for line in section4_text.split("\n"):
        if "剔除因子" in line:
            in_excluded = True
            continue
        if in_excluded:
            if not line.strip():
                break
            if "------" in line:
                continue
            # "· factor(reason1; reason2)"
            m = re.match(r"^\s*·\s*(\S+)\((.+)\)\s*$", line)
            if m:
                excluded.append(
                    {
                        "name": m.group(1),
                        "reasons": [r.strip() for r in m.group(2).split(";")],
                    }
                )
    result["excluded"] = excluded

    if "selected_factors" not in result:
        return None
    return result


def parse_obq_section_10_segments(logger: logging.Logger, date: str | None = None) -> dict | None:
    """v0.4.8 R16: 解析 ob_quality txt 第十节 (今日三十分段候选明细)

    数据格式: 每段 [Sn] 标头 + 合并胜率 + 1-3 只股票 (排名/代码/名称/composite)
    段号不连续 (S1~S30 共 30 段, 跳过中间无股票的段)

    Returns:
        {
            "selection_date": str,
            "pool_size": int,
            "weight_method": str,
            "operation": str,
            "segments": [
                {
                    "label": "S1",
                    "n_stocks": 2,
                    "win_rate": 42.0,  # 合并胜率 %
                    "stocks": [
                        {"rank": 1, "code": "002303", "name": "美盈森", "composite": 1.569},
                        ...
                    ],
                },
                ...30 段
            ],
            "best_segment": {"label": "S7", "win_rate": 61.4},
        }
        None: 解析失败
    """
    latest = _find_latest_txt(date)
    if latest is None:
        return None

    try:
        content = latest.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("读 ob_quality txt 失败: %s (%s)", latest, e)
        return None

    # 找到第十节范围: 从"十、今日三十分段候选明细"到下一个"十、S<n> 段日内操作建议"或文件结尾
    # 修复: 原正则硬编码 "S7" 作为边界, 但最佳段不总是 S7 (历史报告有 S9),
    #   导致 S9 报告的 §10 边界泄漏整个 intraday section. 改为 S\d+ 通配
    section10_match = re.search(
        r"^十、今日三十分段候选明细.*?\n(.*?)(?=^十、S\d+ 段日内操作建议|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if not section10_match:
        logger.debug("ob_quality txt 第十节 (今日三十分段) 未找到")
        return None

    section10_text = section10_match.group(1)

    # 选股日 + 候选池 (第一行元信息)
    # 选股日格式 "2026-07-03" — 用 lookahead 避免 greedy 抓到后随逗号
    date_match = re.search(r"选股日:\s*(\d{4}-\d{2}-\d{2})", section10_text)
    pool_match = re.search(r"候选池共\s*(\d+)\s*只", section10_text)
    wm_match = re.search(r"权重方法:\s*(\S+)", section10_text)
    op_match = re.search(r"操作:\s*(.+?)(?=\n\n|\n\[|\Z)", section10_text, re.DOTALL)

    segments: list[dict] = []
    best_segment = None

    # 段行格式: "[S1] 2 只 合并胜率: 42.0%"
    # 后面紧跟 "    排名 代码         名称        composite"
    # 然后是 dash line, 然后 1-3 行股票数据 (rank code name composite)
    for seg_match in re.finditer(
        r"\[(S\d+)\]\s+(\d+)\s+只\s+合并胜率:\s+([\d.]+)%",
        section10_text,
    ):
        label = seg_match.group(1)
        n_stocks = int(seg_match.group(2))
        win_rate = float(seg_match.group(3))

        # 找到该段股票数据区域: 从 [Sn] 行后到下一个 [S(n+1)] 段标头 (段间有空行)
        seg_start = seg_match.end()
        after_header = section10_text[seg_start:]
        # 段间有空行 — 用更宽松的 pattern: 新行 + 可选空白行 + [S数字]
        # 锚定正则要避免回溯灾难, 用顺序扫描 next_seg
        next_seg_match = re.search(r"\n\s*\[S\d+\]", after_header)
        seg_block = after_header[: next_seg_match.start()] if next_seg_match else after_header

        # 解析股票行: "    1 002303     美盈森           1.569"
        # rank(数字) code(6位数字) name(composite 前的中文名) composite(浮点数)
        stocks: list[dict] = []
        for stock_match in re.finditer(
            r"^\s*(\d+)\s+(\d{6})\s+(\S+)\s+(-?\d+\.\d+)\s*$",
            seg_block,
            re.MULTILINE,
        ):
            stocks.append(
                {
                    "rank": int(stock_match.group(1)),
                    "code": stock_match.group(2),
                    "name": stock_match.group(3),
                    "composite": float(stock_match.group(4)),
                }
            )

        # 校验股票数一致性 (txt 里 S16=1, S29=3 等不规则情况)
        if len(stocks) != n_stocks:
            logger.debug(
                "txt §10 %s: 期望 %d 只, 实际解析到 %d 只",
                label,
                n_stocks,
                len(stocks),
            )

        segments.append(
            {
                "label": label,
                "n_stocks": n_stocks,
                "win_rate": win_rate,
                "stocks": stocks,
            }
        )

        # 跟踪最佳段 (胜率最高)
        if best_segment is None or win_rate > best_segment["win_rate"]:
            best_segment = {"label": label, "win_rate": win_rate}

    if not segments:
        logger.debug("ob_quality txt 第十节 0 段 (regex 未匹配)")
        return None

    result = {
        "selection_date": date_match.group(1) if date_match else "",
        "pool_size": int(pool_match.group(1)) if pool_match else 0,
        "weight_method": wm_match.group(1) if wm_match else "",
        "operation": op_match.group(1).strip() if op_match else "",
        "segments": segments,
        "best_segment": best_segment,
    }
    logger.info(
        "ob_quality txt 第十节 30 分段候选明细解析: %d 段, 最佳段 %s",
        len(segments),
        best_segment,
    )
    return result
