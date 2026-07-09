"""web_ui/common/segment_ai_db.py

v0.4.8 R49 (Stage 6 用户原话 2026-07-08 "web_ui 资产值图组件下方展示"):
读 30 段 AI 客观分析师角色决策数据 (segment_ai_simulation.parquet) 给 web_ui 渲染用.

H1.1 严守 + §18 fork pattern (跟 web_ui/common/segment_win_db.py R38 同模式):
  - web_ui 内部读 parquet, **不**直接 import summary 模块
  - **不**修改 summary/report/segment_ai_db.py (公共数据加载层, 由 summary 维护)

数据源: summary/result/<weight_method>/segment_ai_simulation.parquet
  schema: pipeline, selection_date, trade_date, weight_method, segment_label,
          decision, confidence, reasoning_text, data_observations_json,
          history_window, past_decisions_json, reflection_text, reflection_k_days,
          model_name, provider_endpoint, created_at
  写入: summary/report/segment_ai_db.py:save_segment_ai_simulation() 在
        generate_factor_summary_report.py main() 跑时一并 (R49a-2 调度)

数据契约:
  返回 dict 含 dates/segments[]/source 字段, 跟 R38/R39a/R44 渲染层一致
  字段 (跟 asset_value_db / segment_win_db / pl_ratio_db 风格统一):
    - dates: ["MM-DD", ...] 选股日序列 (mm-dd 格式)
    - segments[]: 每段 1 个 dict, 字段:
        - label: 'S1' ~ 'S30'
        - decisions[]: ['operate'|'skip', ...] 逐日决策
        - confidences[]: [0.0-1.0, ...] 逐日 confidence
        - reasoning_samples[]: [str, ...] 决策理由 (最新 3 条)
        - latest_decision: 'operate'|'skip'  (最新 1 条)
        - latest_confidence: float
        - latest_reasoning: str
    - source: 'parquet' / 'missing'
    - fallback_warning: str | None ([⚠️ ...] 标记, R47 silent fallback 防御)

失败处理 (R47 silent fallback 实战锚点):
  - parquet 不存在 → return None (跟 asset_value_db.load_asset_value_trend 一致)
  - 数据为空 → source='missing', fallback_warning='[⚠️ R49 AI 决策数据尚未生成]'
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from paths import PROJECT_ROOT


# 路径: 复用 paths 模块定义 (AGENTS.md §硬规则 #11)
# R49e (用户原话 2026-07-08 "移动到 summary/result/, 而不是 summary/result/ob_quality/"):
# 完全扁平到顶层, 不嵌 PIPELINE_ALIAS 子目录 (跟 web_ui/common/segment_win_db.py:33 同模式:
# `PROJECT_ROOT / "summary" / "result" / "segment_win_rates.parquet"`). 跟既有 3 段段落布局
# 100% 对齐. v1.5.14 §18.1a paths.py 路径常量命名陷阱: 不应该凭印象嵌额外子目录.
_PARQUET_PATH: Path = PROJECT_ROOT / "summary" / "result" / "segment_ai_simulation.parquet"
logger = logging.getLogger(__name__)

# R49-off (B 方案 minimal disable): 全局开关 R49_ENABLED 控制 web_ui 渲染层短路
# v2.0.21 v1.5.22 实战: web_ui/common module 顶层 import R49_ENABLED**冻结**模块级变量,
#   fixture (monkeypatch.test) 改 sa_module.R49_ENABLED **不**同步到 ui module 顶层变量.
#   修复: 不用模块级 from-import, **直接** import module + 读其 .R49_ENABLED 属性, 永远 fresh.
import summary.report.segment_ai_db as _sa_module_for_r49_enabled  # noqa: E402, F401


def load_segment_ai_decisions(
    pipeline: str = "ob_quality",
    weight_method: str = "rolling_icir_weight",
    logger: logging.Logger | None = None,
) -> dict | None:
    """读 segment_ai_simulation.parquet, 构造 web_ui 渲染 dict.

    R49-off (B 方案): 全局开关 R49_ENABLED=False → 短路 return None (段数=0 web_ui 不渲染)

    Args:
        pipeline: 管线名 (默认 ob_quality)
        weight_method: 权重方法 (默认 rolling_icir_weight)
        logger: 日志 (可选)

    Returns:
        {
            "dates": ["06-15", "06-16", ...],   # 选股日 mm-dd
            "segments": [
                {
                    "label": "S1",
                    "decisions": ["operate", "skip", ...],
                    "confidences": [0.85, 0.42, ...],
                    "reasoning_samples": ["...", "...", ...],   # 最新 3 条
                    "latest_decision": "operate",
                    "latest_confidence": 0.85,
                    "latest_reasoning": "4 项信号全正...",
                },
                ...
            ],
            "source": "parquet",
            "fallback_warning": None,
        }
        None: parquet 不存在 / 读失败 / 数据为空
    """
    # R49-off (B 方案 minimal disable): 全局开关 R49_ENABLED=False -> 短路 return None (段数=0)
    # v2.0.21 v1.5.22 实战: 读 module .R49_ENABLED 属性, **不**读模块级 R49_ENABLED 冻结值
    #   web_ui/common 顶层 from-import R49_ENABLED 会冻结**模块加载时**的值,
    #   fixture (test 改 sa_module.R49_ENABLED) 后**不**同步 → 必须用 module.<attr> fresh read
    if not _sa_module_for_r49_enabled.R49_ENABLED:
        if logger:
            logger.warning("R49-off: load_segment_ai_decisions 被 disabled (R49_ENABLED=False), return None (段数=0)")
        return None

    if not _PARQUET_PATH.exists():
        if logger:
            logger.warning("segment_ai_simulation.parquet 不存在: %s", _PARQUET_PATH)
        return None

    try:
        df = pd.read_parquet(_PARQUET_PATH)
    except Exception as e:
        if logger:
            logger.warning("读 segment_ai_simulation.parquet 失败: %s (%s)", _PARQUET_PATH, e)
        return None

    df = df.loc[(df["pipeline"] == pipeline) & (df["weight_method"] == weight_method)]
    if df.empty:
        if logger:
            logger.warning(
                "segment_ai_simulation 无 %s/%s 数据 (脚本未跑过)",
                pipeline,
                weight_method,
            )
        return {
            "dates": [],
            "segments": [],
            "source": "missing",
            "fallback_warning": (
                "[⚠️ R49 AI 决策数据尚未生成 — 跑 generate_factor_summary_report.py 触发 30 段 LLM 决策]"
            ),
        }

    df = df.sort_values(["segment_label", "selection_date"])

    dates_mmdd = sorted({d[5:] for d in df["selection_date"].unique()})

    # 是否有 [⚠️ fallback] 标记 (R47 silent fallback 防御)
    has_fallback = df["reasoning_text"].str.contains(r"\[⚠️", regex=True, na=False).any()
    fallback_warning = (
        "[⚠️ 部分 AI 决策为 fallback (上游数据缺失/LLM 失败), 见 reasoning_text]" if has_fallback else None
    )

    segments = []
    for label, g in df.groupby("segment_label"):
        decisions = g["decision"].tolist()
        confidences = g["confidence"].astype(float).tolist()
        reasonings = g["reasoning_text"].astype(str).tolist()

        segments.append(
            {
                "label": str(label),
                "decisions": decisions,
                "confidences": [round(c, 2) for c in confidences],
                "reasoning_samples": reasonings[-3:] if len(reasonings) >= 3 else reasonings,
                "latest_decision": decisions[-1] if decisions else None,
                "latest_confidence": round(confidences[-1], 2) if confidences else None,
                "latest_reasoning": reasonings[-1] if reasonings else "",
            }
        )

    segments.sort(key=lambda s: int(s["label"][1:]))

    if logger:
        logger.info(
            "segment_ai_decisions 加载完成: %d 段 × %d 选股日 (来源=%s/%s, fallback=%s)",
            len(segments),
            len(dates_mmdd),
            pipeline,
            weight_method,
            has_fallback,
        )

    return {
        "dates": dates_mmdd,
        "segments": segments,
        "source": "parquet",
        "fallback_warning": fallback_warning,
    }
