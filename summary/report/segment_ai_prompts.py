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
- 当日**每日胜率** ({DAILY_WIN_RATE:.2f}%): {DAILY_WINS}/{DAILY_TOTAL} 只命中
- 当日**每日收益率** ({DAILY_RETURN_PCT:+.2f}%)
- 截至今日**合并胜率** (累计): {CUM_WIN_RATE:.2f}% ({CUM_WINS}/{CUM_TOTAL})
- 截至今日**合并资产值** (geom compound 起点 1.00): {CUM_ASSET_VALUE:.4f}

## 历史窗口 (过去 {HISTORY_WINDOW} 天, {HISTORY_START} ~ {HISTORY_END})
- 每日胜率序列: {HISTORY_WIN_RATES}
- 每日收益率序列: {HISTORY_RETURN_PCTS}
- 合并胜率序列: {HISTORY_CUM_WIN_RATES}
- 合并资产值序列: {HISTORY_CUM_ASSET_VALUES}

## 决策要求 (Round 3 字面: 公正公平, 不带性格色彩, 真实分析)
- 你**没有**先验人格; 没有差异化偏好
- 你的决策**必须**基于上述数据本身的客观特征, 不参考本段以外的其他段
- 决策输出 = `operate` (今天对该段执行虚拟买入) 或 `skip` (今天不操作)
- 操作 = 固定动作: T 日尾盘按该段当日资产清单等权买入 / T+1 日尾盘卖出 (不含交易成本, 这是虚拟模拟)

## 输出格式 (严格 JSON, 不许 free text)
{{
  "decision": "operate" 或 "skip",
  "confidence": 0.0-1.0 之间的浮点数,
  "reasoning": "1-3 句中文, 引用上述具体数字 (胜率/收益/资产值), 解释为什么做此判断",
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
    daily_data: dict[str, Any],
    history_data: dict[str, Any],
    past_decisions: list[dict[str, Any]] | None = None,
    history_window: int = 5,
    past_k_days: int = 5,
) -> str:
    """生成 1 段的 objective analyst system prompt.

    Args:
        segment_label: 'S1' ~ 'S30' (Round 3 字面: 30 段**同模板**, 只换这个)
        selection_date: T 日 (YYYY-MM-DD)
        trade_date: T+1 日
        daily_data: {daily_win_rate, daily_wins, daily_total, daily_return_pct,
                     cum_win_rate, cum_wins, cum_total, cum_asset_value}
        history_data: {history_win_rates, history_return_pcts,
                       history_cum_win_rates, history_cum_asset_values,
                       history_start, history_end}
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

    # Map lower-case daily_data keys → UPPER placeholders, so ROLE_PROMPT_TEMPLATE
    # can use consistent UPPER placeholder names. (Python str.format() requires
    # exact case match.)
    formatted_daily: dict[str, Any] = {}
    for k, v in daily_data.items():
        formatted_daily[k.upper()] = v

    # Map lower-case history_data keys (already mixed case) → UPPER placeholders.
    formatted_history: dict[str, Any] = {}
    for k, v in history_data.items():
        formatted_history[k.upper()] = v
    formatted_history["HISTORY_WINDOW"] = history_window
    formatted_history["PAST_K_DAYS"] = past_k_days
    formatted_history["PAST_DECISIONS_WITH_ACTUAL"] = past_decisions_str

    return ROLE_PROMPT_TEMPLATE.format(
        SEGMENT_LABEL=segment_label,
        SELECTION_DATE=selection_date,
        TRADE_DATE=trade_date,
        **formatted_daily,
        **formatted_history,
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
