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


def _find_latest_txt() -> Path | None:
    """查找最新的 ob_quality txt 报告"""
    txt_root = _get_obq_txt_root()
    if not txt_root.exists():
        return None
    txt_files = sorted(txt_root.glob("factor_summary_report_*.txt"), reverse=True)
    return txt_files[0] if txt_files else None


def parse_obq_section_8_meta(logger: logging.Logger) -> dict:
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
    latest = _find_latest_txt()
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


def parse_obq_section_9_matrix(logger: logging.Logger) -> dict | None:
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
    latest = _find_latest_txt()
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
    segments = []
    for line_match in re.finditer(
        r"(S\d+)\s+((?:\d+%\s+)+)(\d+\.\d+)%\s*$", section9_text, re.MULTILINE
    ):
        label = line_match.group(1)
        win_rates = [
            float(r.rstrip("%")) for r in line_match.group(2).split()
        ]
        merged = float(line_match.group(3))
        segments.append(
            {"label": label, "win_rates": win_rates, "merged": merged}
        )

    # 最佳段: "最佳段: S7 (合并胜率 59.6%)"
    best_match = re.search(r"最佳段[::]\s*(S\d+).*?(\d+\.\d+)\s*%", section9_text)
    best_segment = None
    if best_match:
        best_segment = {
            "label": best_match.group(1),
            "merged": float(best_match.group(2)),
        }

    # 逐日胜率: 找 "S7 逐日胜率:" 段
    best_label_pattern = (
        re.escape(best_match.group(1)) if best_match else r"S\d+"
    )
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
