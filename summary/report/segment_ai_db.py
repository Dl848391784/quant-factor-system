"""v0.4.8 R49 (用户原话 2026-07-08): 30 段 AI 客观分析师角色 — 持久化 + 决策调度 + 反思.

设计模式 (跟 summary/report/segment_win_db.py 同源 — R38/R44 实战锚点):
   - compute_* 函数: 纯算法 (接受 4 曲线数据 dict), 易于测试
   - save_/load_* 函数: IO 函数 (parquet 持久化), 跟 paths.py 集成
   - 两个角色: compute 函数可 mock upstream / save-load round-trip 真实 parquet

数据流 (R49):
   1. main pipeline 调度 (_run_segment_ai_simulation) → 调 compute_one_segment_decision(seg, date, ...)
   2. compute_one_segment_decision
      → load 4 曲线 (read_segment_data_for_decision)
      → build system prompt (segment_ai_prompts.build_role_prompt)
      → call LLM (llm_provider.MinMaxClient.call)
      → parse & validate result
      → return dict
   3. save_segment_ai_simulation(list[dict]) → 一次性写 parquet (跟 segment_stock_details 同模式)
   4. reflection T+1 (compute_reflection_for_segment)
      → 读过去 K 天 decision + 实测 forward_return_1d
      → 算 alignment 比例 → 反思文本

R47 v1.5.18 silent fallback 防御:
   - reflection_text 缺失/窗口不足 → NULL + [⚠️ 窗口不足] 标记 (vs 空字符串)
   - LLM call 失败 → fallback dict 已有 [⚠️] 标记
   - 写 parquet 失败 → logger.exception(...) (R48 修复实战锚点)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

# PROJECT.md H7 路径从 paths.py 导入
from paths import PROJECT_ROOT, SUMMARY_RESULT  # noqa: F401
from summary.report.llm_provider import MinMaxClient, _load_api_key, _load_base_url  # noqa: F401
from summary.report.segment_ai_prompts import (  # noqa: F401
    assert_no_personality_keywords,
    build_role_prompt,
)


logger = logging.getLogger(__name__)

# ── 列定义 (跟 segment_win_db.py SEGMENT_*_COLUMNS 一致) ─────────
SEGMENT_AI_COLUMNS = [
    "pipeline",
    "selection_date",
    "trade_date",
    "weight_method",
    "segment_label",
    "decision",  # 'operate' / 'skip'
    "confidence",  # 0.0-1.0
    "reasoning_text",  # 1-3 句中文
    "data_observations_json",  # list[str] (JSON-serialized)
    "history_window",  # 决策看的历史天数
    "past_decisions_json",  # 反思用 (JSON-serialized; nullable)
    "reflection_text",  # 反思 (nullable 启动期窗口不足)
    "reflection_k_days",  # 反思窗口
    "model_name",  # 'MiniMax-M3' (用于审计)
    "provider_endpoint",  # 'https://api.minimaxi.com/anthropic/v1/messages'
    "created_at",
]

# 默认参数
_DEFAULT_HISTORY_WINDOW = 5
_DEFAULT_REFLECTION_K_DAYS = 5
_DEFAULT_WEIGHT_METHOD = "rolling_icir_weight"
_DEFAULT_PIPELINE = "ob_quality"
_DEFAULT_MODEL = "MiniMax-M3"

# v0.4.8 R49-off (用户原话 2026-07-08 "先关闭 30 个 AI 分析师的功能吧"):
#   全局开关 — True=开放 (默认), False=关闭 (跳过 R49 调度 + web_ui 不渲染).
#   B 方案 minimal disable 实战锚点: 改 1 个常量 = 重启 = 极易.
#   关闭时:
#     - summary/report/segment_ai_db.run_segment_ai_simulation() → return [] (跳过 30 段 LLM)
#     - generate_factor_summary_report.main() R49v2 调度 → skip (不打 LLM)
#     - web_ui/app.py load_segment_ai_decisions() → return None (段数=0 不渲染)
# 跟 v1.5.22 调度入口层 silent fallback 防御协同 (R49v2 实战):
#   关闭时不让 R49 调度静默跳过 — 显式 logger.warning 让用户**看得见** 关了.
# R49-off commit `a786e37` v2.0.21 实践锚点 + 用户原话 2026-07-08 "立即改 R49_ENABLED=False" 改 = 关闭:
R49_ENABLED = False


# ════════════════════════════════════════════════════════════════════
# IO 函数 (parquet 落盘, 跟 segment_win_db.py 一致)
# ════════════════════════════════════════════════════════════════════


def _result_path(weight_method: str | None = None) -> Path:
    """Return parquet path: summary/result/segment_ai_simulation.parquet.

    R49e (用户原话 2026-07-08 "移动到 summary/result/, 而不是 summary/result/ob_quality/"):
      - 完全扁平到顶层, 不嵌 PIPELINE_ALIAS 子目录
      - 跟既有 3 段段落布局 100% 对齐 (segment_win_rates / segment_intraday_strategy /
        segment_stock_details 都在 summary/result/ 顶层, 不走 SUMMARY_RESULT)
      - 走 PROJECT_ROOT / "summary" / "result" 直挂顶层 (跟 web_ui/common/segment_win_db.py R38 同模式)
      - `weight_method` 参数保留向后兼容 (但**不**影响路径, PIPELINE_ALIAS 跟 weight_method 都不进路径)
      - v1.5.14 §18.1a paths.py 路径常量命名陷阱: 不应该凭印象嵌额外子目录
    """
    return PROJECT_ROOT / "summary" / "result" / "segment_ai_simulation.parquet"


def _read_parquet(fp: Path) -> pd.DataFrame:
    """Read parquet if exists, return empty DataFrame (with schema) otherwise.

    Returns pd.DataFrame (never Series) — type-narrowed for LSP safety.
    """
    if not fp.exists():
        return pd.DataFrame(columns=SEGMENT_AI_COLUMNS)
    try:
        result = pd.read_parquet(fp)
    except Exception:
        logger.exception("Failed to read parquet %s, returning empty", fp)
        return pd.DataFrame(columns=SEGMENT_AI_COLUMNS)
    # Defensive: pd.read_parquet overloads return DataFrame | Series,
    # but spec is always DataFrame (we control schema). Normalize to DataFrame.
    if not isinstance(result, pd.DataFrame):
        return pd.DataFrame(columns=SEGMENT_AI_COLUMNS)
    return result.astype(
        {col: str for col in SEGMENT_AI_COLUMNS if col not in ("confidence", "history_window", "reflection_k_days")},
        errors="ignore",
    )


def save_segment_ai_simulation(
    rows: list[dict[str, Any]],
    weight_method: str = _DEFAULT_WEIGHT_METHOD,
) -> Path:
    """Save 30 段 × 1 天的决策结果到 parquet.

    Args:
        rows: list of dict with keys = SEGMENT_AI_COLUMNS
        weight_method: parquet 写入的子目录

    Returns:
        最终 parquet 路径

    R47 silent fallback 防御:
        - write 失败 → logger.exception(...) (vs 静默)
        - rows 为空 → logger.warning + return fp (不报错, 但有日志)
    """
    fp = _result_path(weight_method)
    fp.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        logger.warning(
            "save_segment_ai_simulation: empty rows for %s/%s, skipping",
            weight_method,
            fp,
        )
        return fp

    new_df = pd.DataFrame(rows, columns=SEGMENT_AI_COLUMNS)

    existing: pd.DataFrame = _read_parquet(fp)
    # type narrow for LSP (LSP can't infer from isinstance(_read_parquet) return)
    if not isinstance(existing, pd.DataFrame):
        existing = pd.DataFrame(columns=SEGMENT_AI_COLUMNS)

    if not existing.empty and rows:
        # 去重: 删除同 (pipeline, selection_date, weight_method) 旧行
        first = rows[0]
        sel_date = first.get("selection_date", "")
        pipe = first.get("pipeline", "")
        if sel_date and pipe:
            mask = (
                (existing["pipeline"] == pipe)
                & (existing["selection_date"] == sel_date)
                & (existing["weight_method"] == weight_method)
            )
            existing = existing[~mask]

    try:
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined.to_parquet(fp, index=False)
        logger.info(
            "segment_ai_simulation: %s/%s 写入 %d 行 → %s (累计 %d 行)",
            rows[0].get("pipeline", "?") if rows else "?",
            rows[0].get("selection_date", "?") if rows else "?",
            len(rows),
            fp.name,
            len(combined),
        )
    except Exception:
        logger.exception("save_segment_ai_simulation: write failed for %s", fp)
        raise

    return fp


def load_segment_ai_simulation(
    pipeline: str = _DEFAULT_PIPELINE,
    selection_date: str | None = None,
    weight_method: str = _DEFAULT_WEIGHT_METHOD,
) -> pd.DataFrame:
    """Read 决策结果.

    Args:
        pipeline: 'ob_quality'
        selection_date: 选股日, None = 全部
        weight_method: 权重方法

    Returns:
        DataFrame with SEGMENT_AI_COLUMNS
    """
    fp = _result_path(weight_method)
    df = _read_parquet(fp)
    if df.empty:
        return df
    df = df[df["pipeline"] == pipeline]
    if selection_date:
        df = df[df["selection_date"] == selection_date]
    return df


# ════════════════════════════════════════════════════════════════════
# Compute 函数 (纯算法, 易测试)
# ════════════════════════════════════════════════════════════════════


def compute_one_segment_decision(
    segment_label: str,
    selection_date: str,
    trade_date: str,
    segment_data: dict[str, Any],
    weight_method: str = _DEFAULT_WEIGHT_METHOD,
    pipeline: str = _DEFAULT_PIPELINE,
    history_window: int = _DEFAULT_HISTORY_WINDOW,
    past_decisions: list[dict[str, Any]] | None = None,
    client: MinMaxClient | None = None,
) -> dict[str, Any]:
    """Compute 1 segment × 1 day 的 AI decision + 落盘 1 行数据.

    R49f: segment_data = read_segment_data_for_decision() 返回的 5 字段 dict:
      daily_win_rates, merged_win_rates, daily_return_pcts,
      merged_asset_values, today_stock_recommendations

    Args:
        segment_label: 'S1' ~ 'S30'
        selection_date: T 日
        trade_date: T+1 日
        segment_data: 5 字段 dict (R49f 新接口, 替代旧 daily_data + history_data)
        weight_method: 'rolling_icir_weight' (默认)
        pipeline: 'ob_quality' (默认)
        history_window: 决策看的历史天数
        past_decisions: 反思阶段用 (首次 = None)
        client: MinMaxClient 实例 (None = 默认构造)

    Returns:
        行 dict, keys = SEGMENT_AI_COLUMNS, ready for save_segment_ai_simulation
    """
    if client is None:
        client = MinMaxClient()

    # R49f: build_role_prompt 接收 5 字段 segment_data (替代旧 daily_data + history_data)
    system_prompt = build_role_prompt(
        segment_label=segment_label,
        selection_date=selection_date,
        trade_date=trade_date,
        segment_data=segment_data,
        past_decisions=past_decisions,
        history_window=history_window,
        past_k_days=_DEFAULT_REFLECTION_K_DAYS,
    )
    assert_no_personality_keywords(system_prompt)  # Round 3 约束

    # user message: 决策提示 (system prompt 已含所有数据, user 简短一句)
    user_message = (
        f"请基于 system prompt 提供的数据, 为 {segment_label} 段给出今天的 operate/skip 决策。"
        f"\n\n严格按要求的 JSON schema 输出, 不要任何额外文字。"
    )

    llm_result = client.call(
        system=system_prompt,
        user=user_message,
        max_tokens=500,
        json_mode=True,
    )

    now = datetime.now(timezone.utc).isoformat()
    return {
        "pipeline": pipeline,
        "selection_date": selection_date,
        "trade_date": trade_date,
        "weight_method": weight_method,
        "segment_label": segment_label,
        "decision": llm_result["decision"],
        "confidence": llm_result["confidence"],
        "reasoning_text": llm_result["reasoning"],
        "data_observations_json": json.dumps(llm_result["data_observations"], ensure_ascii=False),
        "history_window": history_window,
        "past_decisions_json": json.dumps(past_decisions, ensure_ascii=False) if past_decisions else None,
        "reflection_text": None,  # 反思阶段另算 (compute_reflection_for_segment)
        "reflection_k_days": _DEFAULT_REFLECTION_K_DAYS,
        "model_name": _DEFAULT_MODEL,
        "provider_endpoint": f"{client.base_url}/v1/messages",
        "created_at": now,
    }


def compute_reflection_for_segment(
    past_decisions_with_actual: list[dict[str, Any]],
    k: int = _DEFAULT_REFLECTION_K_DAYS,
) -> tuple[str | None, str | None]:
    """Compute 反思文本 (T+1 实测收益回来后回放).

    Args:
        past_decisions_with_actual: [{date, decision, actual_return}, ...]
        k: 反思窗口 (默认 5)

    Returns:
        (reflection_text, warning_text):
            - reflection_text: 反思文本 (None = 窗口不足)
            - warning_text: [⚠️ ...] 标记 (None = 窗口充足)

    R47 v1.5.18 silent fallback 防御:
        - 窗口不足 → reflection_text=None (NOT empty string) + warning_text 含 [⚠️]
        - 实际操作 (operate+正) 或 (skip+负) 算 correct, 反之算 incorrect
        - 跟 R47 ob_quality §10 错位实战同源模式
    """
    if len(past_decisions_with_actual) < k:
        return None, f"[⚠️ 反思窗口不足 ({len(past_decisions_with_actual)}/{k})]"

    correct = 0
    for d in past_decisions_with_actual:
        decision = d.get("decision")
        actual = d.get("actual_return")
        if actual is None:
            continue
        if decision == "operate" and actual > 0 or decision == "skip" and actual <= 0:
            correct += 1

    total = len(past_decisions_with_actual)
    accuracy = correct / total if total > 0 else 0.0
    return (
        f"过去 {k} 天 (T-1 数据 → T+1 实测): 决策 {correct}/{total} ({accuracy:.0%}) 对齐. "
        f"{'保持当前判断策略.' if accuracy >= 0.6 else '未来可考虑收紧决策标准.'}",
        None,
    )


# ════════════════════════════════════════════════════════════════════
# DataLoader (读 parquet → 算 4 曲线)
# ════════════════════════════════════════════════════════════════════


def read_segment_data_for_decision(
    segment_label: str,
    selection_date: str,
    trade_date: str,
    history_window: int = _DEFAULT_HISTORY_WINDOW,
    weight_method: str = _DEFAULT_WEIGHT_METHOD,
    pipeline: str = _DEFAULT_PIPELINE,
) -> dict[str, Any] | None:
    """R49f (用户原话 2026-07-08): 复用 web_ui 4 个组件同款函数 + segment_stock_details.

    5 步精确算法 (用户原话 "严格按我下面的步骤执行"):
      1. 每日胜率 = parse_obq_section_9_matrix() → segments[].win_rates[]
         (跟 web_ui【30 段胜率趋势概览】组件一样)
      2. 合并胜率 = load_merged_win_trend() → segments[].merged_running[]
         (跟 web_ui【30 段合并胜率趋势概览】组件一样)
      3. 每日收益率 = load_pl_ratio_trend() → segments[].pl_ratios[]
         (跟 web_ui【30 段每日合并收益率趋势概览】组件一样)
      4. 合并资产值 = load_asset_value_trend() → segments[].asset_values[]
         (跟 web_ui【30 段每日复合资产值趋势概览】组件一样)
      5. 今日股票推荐 = pd.read_parquet(segment_stock_details) filtered by seg + date
         (用户原话 "每日推荐不是在 segment_stock_details.parquet 里么?")

    Returns:
        {
            "daily_win_rates": [...],       # Step 1
            "merged_win_rates": [...],      # Step 2
            "daily_return_pcts": [...],     # Step 3
            "merged_asset_values": [...],   # Step 4
            "today_stock_recommendations": [...],  # Step 5
        }
        None: 任一步数据缺失 (R47 silent fallback: logger.warning + return None)
    """
    import logging

    _logger = logging.getLogger(__name__)

    # Step 1: 每日胜率 — 复用 parse_obq_section_9_matrix (跟 web_ui segOverviewChart 一样)
    try:
        from web_ui.common.txt_parser import parse_obq_section_9_matrix

        s9 = parse_obq_section_9_matrix(_logger)
        if not s9 or not s9.get("segments"):
            _logger.warning("R49f Step 1: parse_obq_section_9_matrix 返回空")
            return None
        seg_s1 = next((s for s in s9["segments"] if s["label"] == segment_label), None)
        if not seg_s1:
            _logger.warning("R49f Step 1: %s 不在 txt_s9_matrix", segment_label)
            return None
        daily_win_rates = [float(v) for v in seg_s1.get("win_rates", [])]

    except Exception:
        _logger.exception("R49f Step 1: parse_obq_section_9_matrix 失败")
        return None

    # Step 2: 合并胜率 — 复用 load_merged_win_trend (跟 web_ui segMergedChart 一样)
    try:
        from web_ui.common.segment_win_db import load_merged_win_trend

        merged = load_merged_win_trend(pipeline=pipeline, weight_method=weight_method, logger=_logger)
        if not merged or not merged.get("segments"):
            _logger.warning("R49f Step 2: load_merged_win_trend 返回空")
            return None
        seg_m = next((s for s in merged["segments"] if s["label"] == segment_label), None)
        if not seg_m:
            _logger.warning("R49f Step 2: %s 不在 merged_win_trend", segment_label)
            return None
        merged_win_rates = [float(v) for v in seg_m.get("merged_running", [])]
    except Exception:
        _logger.exception("R49f Step 2: load_merged_win_trend 失败")
        return None

    # Step 3: 每日收益率 — 复用 load_pl_ratio_trend (跟 web_ui segReturnChart 一样)
    try:
        from web_ui.common.pl_ratio_db import load_pl_ratio_trend

        pl = load_pl_ratio_trend(weight_method=weight_method, logger=_logger)
        if not pl or not pl.get("segments"):
            _logger.warning("R49f Step 3: load_pl_ratio_trend 返回空")
            return None
        seg_p = next((s for s in pl["segments"] if s["label"] == segment_label), None)
        if not seg_p:
            _logger.warning("R49f Step 3: %s 不在 pl_ratio_trend", segment_label)
            return None
        daily_return_pcts = [float(v) for v in seg_p.get("pl_ratios", [])]
    except Exception:
        _logger.exception("R49f Step 3: load_pl_ratio_trend 失败")
        return None

    # Step 4: 合并资产值 — 复用 load_asset_value_trend (跟 web_ui assetValueChart 一样)
    try:
        from web_ui.common.asset_value_db import load_asset_value_trend

        av = load_asset_value_trend(weight_method=weight_method, logger=_logger)
        if not av or not av.get("segments"):
            _logger.warning("R49f Step 4: load_asset_value_trend 返回空")
            return None
        seg_a = next((s for s in av["segments"] if s["label"] == segment_label), None)
        if not seg_a:
            _logger.warning("R49f Step 4: %s 不在 asset_value_trend", segment_label)
            return None
        merged_asset_values = [float(v) for v in seg_a.get("asset_values", [])]
    except Exception:
        _logger.exception("R49f Step 4: load_asset_value_trend 失败")
        return None

    # Step 5: 今日股票推荐 — segment_stock_details.parquet (用户原话)
    try:
        ssd_path = PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
        if not ssd_path.exists():
            _logger.warning("R49f Step 5: segment_stock_details.parquet 不存在")
            return None
        ssd = pd.read_parquet(
            ssd_path,
            columns=[
                "pipeline",
                "weight_method",
                "selection_date",
                "segment_label",
                "asset",
                "composite_value",
                "rank",
            ],
        )
        today_stocks_df = ssd[
            (ssd["pipeline"] == pipeline)
            & (ssd["weight_method"] == weight_method)
            & (ssd["selection_date"] == selection_date)
            & (ssd["segment_label"] == segment_label)
        ].sort_values("rank")
        today_stock_recommendations = today_stocks_df.to_dict("records")
    except Exception:
        _logger.exception("R49f Step 5: segment_stock_details 读失败")
        return None

    _logger.info(
        "R49f read_segment_data_for_decision: %s 5 步全部成功 "
        "(win_rates=%d, merged=%d, return=%d, asset=%d, stocks=%d)",
        segment_label,
        len(daily_win_rates),
        len(merged_win_rates),
        len(daily_return_pcts),
        len(merged_asset_values),
        len(today_stock_recommendations),
    )

    return {
        "daily_win_rates": daily_win_rates,
        "merged_win_rates": merged_win_rates,
        "daily_return_pcts": daily_return_pcts,
        "merged_asset_values": merged_asset_values,
        "today_stock_recommendations": today_stock_recommendations,
    }


# ════════════════════════════════════════════════════════════════════
# Top-level 调度 (R49: generate_factor_summary_report.py main() 调)
# ════════════════════════════════════════════════════════════════════


def run_segment_ai_simulation(
    selection_date: str,
    trade_date: str,
    weight_method: str = _DEFAULT_WEIGHT_METHOD,
    pipeline: str = _DEFAULT_PIPELINE,
    history_window: int = _DEFAULT_HISTORY_WINDOW,
    n_segments: int = 30,
    client: MinMaxClient | None = None,
) -> list[dict[str, Any]]:
    """跑 30 段 × 1 天 AI 模拟, 返回行 list (ready for save_segment_ai_simulation).

    v0.4.8 R49v3 (用户原话 2026-07-08 "我不知道执行到哪一步了, 加下日志吧"):
      加 3 类显式进度日志让用户**看得见** 调度跑在哪:
        - L538 LOGGER.info 启动: "R49v3: 开始 30 段 AI 角色调度 (selection=X, trade=Y)..."
        - L548 LOGGER.warning 段进度 (每 5 段 + 最后一段 + 失败段): "[3/30] S3 调度..." etc
        - L566 LOGGER.warning 段耗时: "[5/30] S5 调度 done (ms3.2 / win=ok)..."
        - L582 LOGGER.warning 调度完成: "R49v3: 完成 30 段 (success=28, fallback=2, total=45.3s)"

    Args:
        selection_date: T 日
        trade_date: T+1 日
        weight_method: 'rolling_icir_weight' 默认
        pipeline: 'ob_quality' 默认
        history_window: 历史窗口
        n_segments: 30 段
        client: MinMaxClient 实例 (None = 默认)

    Returns:
        list of 30 dict rows; 失败的段以 [⚠️] fallback dict 形式落
    """
    # R49-off (B 方案): 全局开关 False → 跳过 30 段 LLM 调用
    if not R49_ENABLED:
        logger.warning("R49-off: run_segment_ai_simulation 被 disabled (R49_ENABLED=False), return [] (跳过 30 段 LLM)")
        return []

    if client is None:
        client = MinMaxClient()

    # R49v3 启动进度日志
    started_ts = time.time()
    logger.info(
        "R49v3 run_segment_ai_simulation 启动: pipeline=%s / weight_method=%s / "
        "selection_date=%s / trade_date=%s / n_segments=%d",
        pipeline,
        weight_method,
        selection_date,
        trade_date,
        n_segments,
    )
    rows: list[dict[str, Any]] = []
    n_success = 0
    n_data_fallback = 0
    n_decision_fallback = 0
    seg_durations: list[float] = []

    for i in range(1, n_segments + 1):
        seg_label = f"S{i}"
        seg_started = time.time()
        # R49v3 段进度日志: 每 5 段 + 最后一 + 首段报告 (用户能看见到第几段)
        if i == 1 or i % 5 == 0 or i == n_segments:
            logger.info(
                "[%d/%d] R49v3 调度中: %s (start_ts=%.1f)",
                i,
                n_segments,
                seg_label,
                seg_started - started_ts,
            )

        try:
            data = read_segment_data_for_decision(
                segment_label=seg_label,
                selection_date=selection_date,
                trade_date=trade_date,
                history_window=history_window,
                weight_method=weight_method,
                pipeline=pipeline,
            )
            if data is None:
                # 数据缺失 → silent fallback 行 (R47 防御)
                n_data_fallback += 1
                logger.warning(
                    "[%d/%d] R49v3 %s 数据缺失, 写 fallback row [⚠️ 数据缺失]",
                    i,
                    n_segments,
                    seg_label,
                )
                rows.append(
                    _empty_fallback_row(
                        seg_label,
                        selection_date,
                        trade_date,
                        weight_method,
                        pipeline,
                        client,
                        "[⚠️ 数据缺失]",
                    )
                )
                _log_seg_done(i, n_segments, seg_label, seg_started, started_ts, "data_fallback", seg_durations)
                continue

            row = compute_one_segment_decision(
                segment_label=seg_label,
                selection_date=selection_date,
                trade_date=trade_date,
                segment_data=data,  # R49f: 5 字段 dict 替代旧 daily_data + history_data
                weight_method=weight_method,
                pipeline=pipeline,
                history_window=history_window,
                client=client,
            )
            rows.append(row)
            n_success += 1
            _log_seg_done(
                i, n_segments, seg_label, seg_started, started_ts, f"decision={row['decision']}", seg_durations
            )
        except Exception as e:
            # 不让单段失败拖垮全跑 (R47 silent fallback)
            n_decision_fallback += 1
            logger.exception(
                "[%d/%d] R49v3 %s LLM 决策失败 (%s), 写 fallback row",
                i,
                n_segments,
                seg_label,
                type(e).__name__,
            )
            rows.append(
                _empty_fallback_row(
                    seg_label,
                    selection_date,
                    trade_date,
                    weight_method,
                    pipeline,
                    client,
                    f"[⚠️ 决策失败 ({type(e).__name__}): {e}]",
                )
            )
            _log_seg_done(
                i,
                n_segments,
                seg_label,
                seg_started,
                started_ts,
                f"decision_fallback ({type(e).__name__})",
                seg_durations,
            )

    # R49v3 调度完成汇总日志
    total_elapsed = time.time() - started_ts
    if seg_durations:
        avg_ms = (sum(seg_durations) / len(seg_durations)) * 1000
        max_ms = max(seg_durations) * 1000
        min_ms = min(seg_durations) * 1000
    else:
        avg_ms = max_ms = min_ms = 0.0
    logger.warning(
        "R49v3 run_segment_ai_simulation 完成: success=%d / data_fallback=%d / "
        "decision_fallback=%d / total=%d 段, 耗时=%.2fs (avg=%.0fms / max=%.0fms / min=%.0fms)",
        n_success,
        n_data_fallback,
        n_decision_fallback,
        n_segments,
        total_elapsed,
        avg_ms,
        max_ms,
        min_ms,
    )
    return rows


def _log_seg_done(
    idx: int,
    total: int,
    seg_label: str,
    seg_started: float,
    run_started: float,
    status: str,
    durations: list[float],
) -> None:
    """R49v3: 段调度完成耗时日志 (内部辅助)."""
    elapsed = time.time() - seg_started
    durations.append(elapsed)
    logger.info(
        "[%d/%d] R49v3 %s done: status=%s, seg_elapsed=%.2fs (total_run=%.1fs)",
        idx,
        total,
        seg_label,
        status,
        elapsed,
        time.time() - run_started,
    )


def _empty_fallback_row(
    seg_label: str,
    selection_date: str,
    trade_date: str,
    weight_method: str,
    pipeline: str,
    client: MinMaxClient,
    warning: str,
) -> dict[str, Any]:
    """构造 1 行 fallback row (数据缺失 / 决策失败时)。"""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "pipeline": pipeline,
        "selection_date": selection_date,
        "trade_date": trade_date,
        "weight_method": weight_method,
        "segment_label": seg_label,
        "decision": "skip",
        "confidence": 0.0,
        "reasoning_text": warning,
        "data_observations_json": "[]",
        "history_window": 0,
        "past_decisions_json": None,
        "reflection_text": None,
        "reflection_k_days": _DEFAULT_REFLECTION_K_DAYS,
        "model_name": _DEFAULT_MODEL,
        "provider_endpoint": f"{client.base_url}/v1/messages",
        "created_at": now,
    }
