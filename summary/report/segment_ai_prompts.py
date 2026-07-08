"""v0.4.8 R49 (用户原话 2026-07-08 Round 3 字面 "公正公平不带有性格色彩, 真实分析"):
30 个角色 = **同一份**客观分析师 system prompt 模板, 只换 ${SEGMENT_LABEL}.

设计要点:
   - Round 3 字面: 30 段**同模板**, **不**给差异化偏好 (激进/保守/中性/风险偏好)
   - 测试必断言 30 段 prompt 全部不含性格关键字
   - 4 曲线数据 + 历史窗口 + 决策要求 + 输出 JSON schema
   - R47 v1.5.18 silent fallback 防御: 反思阶段响应空
"""

from __future__ import annotations

import json
from typing import Any


# Round 3 字面约束验证 — 30 段 prompt 全部通过此断言, 任何性格关键字 = 违例
_PERSONALITY_KEYWORDS = [
    "激进",
    "保守",
    "中性化",
    "中性",
    "稳健",
    "保守型",
    "激进型",
    "强保守",
    "强激进",
    "风险偏好",
    "risk-taker",
    "risk averse",
    "aggressive",
    "conservative",
    "prefer",
    "preference",
]


ROLE_PROMPT_TEMPLATE = """你是 30 分段量化方案中负责 **{SEGMENT_LABEL}** 段的客观分析师。

你的**唯一职责**：基于该段历史数据, **不带任何情绪、风格或偏好**地为今天是否对该段执行「T 日尾盘买入 / T+1 日尾盘卖出」给出一个判断。

## 数据上下文 (今日 {SELECTION_DATE}, T+1 交易 {TRADE_DATE})

### 1. 每日胜率 (Step 1, 跟 web_ui【30 段胜率趋势概览】组件一样)
{DAILY_WIN_RATES_LIST}

### 2. 合并胜率 (Step 2, 跟 web_ui【30 段合并胜率趋势概览 (截至当日累计合并)】组件一样)
{MERGED_WIN_RATES_LIST}

### 3. 每日收益率 (Step 3, 跟 web_ui【30 段每日合并收益率趋势概览 (seg_return = mean(forward_return_1d))】组件一样)
{DAILY_RETURN_PCTS_LIST}

### 4. 每日复合资产值 (Step 4, 跟 web_ui【30 段每日复合资产值趋势概览 (geom compound, 起点 1.00)】组件一样)
{MERGED_ASSET_VALUES_LIST}

### 5. 今日该段股票推荐 (Step 5, 来自 segment_stock_details.parquet)
{TODAY_STOCK_RECOMMENDATIONS_LIST}

## 决策要求 (Round 3 字面: 公正公平, 不带性格色彩, 真实分析)
- 你**没有**先验人格; 没有差异化偏好
- 你的决策**必须**基于上述 5 项数据本身的客观特征, 不参考本段以外的其他段
- 决策输出 = `operate` (今天对该段执行虚拟买入) 或 `skip` (今天不操作)
- 操作 = 固定动作: T 日尾盘按该段当日资产清单等权买入 / T+1 日尾盘卖出 (不含交易成本, 这是虚拟模拟)

## 输出格式 (严格 JSON, 不许 free text)
{{
  "decision": "operate" 或 "skip",
  "confidence": 0.0-1.0 之间的浮点数,
  "reasoning": "1-3 句中文, 引用上述具体数字 (胜率/收益/资产值/股票), 解释为什么做此判断",
  "data_observations": ["bullet 1: 引用具体数字", "bullet 2: 引用具体数字"]
}}

## 反思 (仅在 T+1 实测收益回来后, **回放**阶段调用)
- 过去 {PAST_K_DAYS} 天你的决策记录: {PAST_DECISIONS_WITH_ACTUAL}
- 写出 1-2 句反思: 哪些判断对未来有帮助, 哪些需要修正

不要犹豫。直接输出 JSON。
"""


def build_role_prompt(
    segment_label: str,
    selection_date: str,
    trade_date: str,
    segment_data: dict[str, Any],
    past_decisions: list[dict[str, Any]] | None = None,
    history_window: int = 5,
    past_k_days: int = 5,
) -> str:
    """生成 1 段的 objective analyst system prompt.

    R49f (用户原话 2026-07-08 "严格按我下面的步骤执行"):
      segment_data = read_segment_data_for_decision() 返回的 5 字段 dict:
        1. daily_win_rates         (Step 1, 跟 web_ui【30 段胜率趋势概览】)
        2. merged_win_rates        (Step 2, 跟 web_ui【30 段合并胜率趋势概览】)
        3. daily_return_pcts       (Step 3, 跟 web_ui【30 段每日合并收益率趋势概览】)
        4. merged_asset_values     (Step 4, 跟 web_ui【30 段每日复合资产值趋势概览】)
        5. today_stock_recommendations (Step 5, 来自 segment_stock_details.parquet)

    Args:
        segment_label: 'S1' ~ 'S30' (Round 3 字面: 30 段**同模板**, 只换这个)
        selection_date: T 日 (YYYY-MM-DD)
        trade_date: T+1 日 (YYYY-MM-DD)
        segment_data: 5 字段 dict (R49f 新接口, 替代旧 daily_data + history_data)
        past_decisions: list[{date, decision, actual_return}] 反思阶段
        history_window: 决策看的历史天数 (默认 5)
        past_k_days: 反思用的历史天数 (默认 5)

    Returns:
        填充好占位符的 system prompt
    """
    if past_decisions is None:
        past_decisions_str = "(首次决策, 暂无历史)"
    else:
        past_decisions_str = json.dumps(past_decisions, ensure_ascii=False, indent=2)

    # R49f: 5 字段直接序列化 (不用 daily_data/history_data 双层 dict)
    daily_win_rates_list = json.dumps(segment_data.get("daily_win_rates", []), ensure_ascii=False)
    merged_win_rates_list = json.dumps(segment_data.get("merged_win_rates", []), ensure_ascii=False)
    daily_return_pcts_list = json.dumps(segment_data.get("daily_return_pcts", []), ensure_ascii=False)
    merged_asset_values_list = json.dumps(segment_data.get("merged_asset_values", []), ensure_ascii=False)
    # Step 5 今日股票推荐: segment_stock_details.parquet 过滤本段, 转列表 + JSON
    today_stocks = segment_data.get("today_stock_recommendations", [])
    today_stock_recs_list = json.dumps(
        [
            {
                "asset": s.get("asset", ""),
                "composite_value": round(s.get("composite_value", 0), 4),
                "rank": int(s.get("rank", 0)),
            }
            for s in today_stocks
        ],
        ensure_ascii=False,
        indent=2,
    )

    return ROLE_PROMPT_TEMPLATE.format(
        SEGMENT_LABEL=segment_label,
        SELECTION_DATE=selection_date,
        TRADE_DATE=trade_date,
        DAILY_WIN_RATES_LIST=daily_win_rates_list,
        MERGED_WIN_RATES_LIST=merged_win_rates_list,
        DAILY_RETURN_PCTS_LIST=daily_return_pcts_list,
        MERGED_ASSET_VALUES_LIST=merged_asset_values_list,
        TODAY_STOCK_RECOMMENDATIONS_LIST=today_stock_recs_list,
        PAST_K_DAYS=past_k_days,
        PAST_DECISIONS_WITH_ACTUAL=past_decisions_str,
    )


def assert_no_personality_keywords(prompt: str) -> None:
    """断言 prompt 不含性格关键字 (Round 3 字面约束).

    Raises:
        AssertionError: 含任何性格关键字 → 违规
    """
    lower_prompt = prompt.lower()
    for kw in _PERSONALITY_KEYWORDS:
        if kw.lower() in lower_prompt:
            raise AssertionError(
                f"Personality keyword '{kw}' found in role prompt. Round 3 字面约束: 30 段必须公正公平, 不带性格色彩."
            )
