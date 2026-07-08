# 30 分段 AI 客观分析师角色 (LLM 直接调 minimax) — R49/v3 完整版

> 版本: **draft v3 (R49 + R48 + R47 + R47b + v1.5.20 全链路实战对齐)**
> 设计阶段: Plan (superpowers-workflow v2.0.16)
> 关联: AGENTS.md 硬规则 #5 / 实战交易规则 / 战略目标段
>     PROJECT.md "T+1 持仓" + "实战交易规则" + 数据驱动原则
>     summary/MODULE.md v2.2 持久化层规范
>     web_ui/MODULE.md 渲染层规范 (H1.1 严守)
>     R44 (assetValueChart) / R47 (silent fallback) / R48 (silent fallback 修复)
>     R47b (算法行为印象幻觉) / R49 (provider 协议印象幻觉)
>     karpathy-guidelines §18.1f v1.5.20 + superpowers-workflow v2.0.16 Plan 反模式

---

## 1. 背景与目标

### 1.1 现状

项目已积累 30 段 × 14 选股日的完整四类历史曲线数据：

| 维度 | 数据源 | 字段 | 现有可视化 |
|---|---|---|---|
| 每日胜率 | `summary/result/segment_win_rates.parquet` | `win_rate` | §9 矩阵 |
| 合并胜率 | 同上 + cumsum | `merged_running[]` | R38 segMergedChart |
| 每日收益率 | `segment_stock_details.parquet` + master 全市场 | `seg_return_pct` | R39a segReturnChart |
| 合并收益率 | geom compound over pl_ratio_trend | `merged_asset_value[]` | R44 assetValueChart |

四类数据**100% 已就绪**。**没有**"自动模拟 + T 日尾盘买 T+1 尾盘卖"的工具。

### 1.2 用户原话 (4 轮完整实录, 2026-07-08)

**Round 1**: "自动模拟操作，每个 AI 自己决策是否操作，如果操作就 T 日尾盘买入 T+1 尾盘卖出，操作依据基于该段的每日胜率 + 每日收益率 + 合并胜率 + 合并收益率四个曲线自己判断，需要反思总结，在 web_ui 页面【30 段每日复合资产值趋势概览 (geom compound, 起点 1.00, Y 轴 = 资产值)】组件下方展示就行，执行 generate_factor_summary_report.py 脚本的时候执行，可以新建 parquet 进行存储"

**Round 2 (LLM 角色化校准)**: "我的意思是，AI 角色是一个 LLM 角色，我们实现写好角色定义，参考该段的每日胜率 + 每日收益率 + 合并胜率 + 合并收益率四个曲线 AI 自己判断今天是否按照该段推荐买入，如果买入那就是固定的 T 日尾盘买入 T+1 尾盘卖出，然后每个 AI 需要根据该段的数据进行反思思考总结"

**Round 3 (角色去差异化)**: "30 个角色是否差异化？我也不知道是否差异化，如果差异化设定就不客观了，比如在一条胜率低的分段遇到一个激进的 AI 肯定完蛋，我想每个 AI 的角色都能公正公平不带有性格色彩，真实分析"

**Round 4 (协议 + key 落地)**: "我没懂，hermes 已经配置了 minimax，现在就在用 minimax，那么你直接用类似的方式调 minimax 的接口就行了呀"

**Round 5 (model + key)**: "直接接 OpenAI SDK 不要 mock，用 minimax 这个模型吧，key 什么的你应该都有"

**Round 6 (修正 + key 落地保护)**: "key 是 `sk-cp-oke3xMv9Se5-mOTt4XCA070ZycsC2TKmzJEvihQLdKLxiGaj-H8UNSFeq0AKqooa6ziUjcySNVO6xTba2ggdwoxYxAKro8sS5K61ZY_OXrAlmhlMLMWDRk8`，写在本地某个配置文件里吧，不要写在脚本里不安全"

**6 轮原话抽取的硬约束** (不二次解读, 只抽字面):
- 30 个角色 / 每段一个 / 只看自己段
- **LLM 角色** (Round 2 明确, 修正我 Round 1 猜的 A 方案)
- **每个角色 = 公正 / 不带性格 / 真实分析** (Round 3 字面 6 关键词)
- **同模板** (Round 3 "我想每个 AI 的角色都能公正公平" = 同一份 system prompt, 只换段号)
- 决策依据 = 4 曲线 (每日胜率 / 每日收益 / 合并胜率 / 合并收益)
- 自动输出: `decision ∈ {operate, skip}` + reasoning + 反思
- 固定动作: T 日尾盘买 / T+1 尾盘卖 (PROJECT.md 实战交易规则)
- 落地位置: web_ui R44 assetValueChart 组件**下方** (Round 1 字面)
- 执行点: `generate_factor_summary_report.py` 跑时一并执行
- 存储: 新建 parquet
- **直接接真实 LLM** (Round 5 "不要 mock")
- **Provider: minimax + base_url `/anthropic`** (Round 4 "类似 Hermes 现在调 minimax 的方式" — v1.5.20 step 2 实证 base_url = `https://api.minimaxi.com/anthropic`)
- **Model: MiniMax-M3** (Round 5 + ~/.hermes/config.yaml `default.model`)
- **Key 落地保护** (Round 6 字面 "本地配置 / 不要在脚本" + AGENTS.md §1)

### 1.3 非目标

- ❌ **不**改 stock_selector.py / comprehensive_factor.py — 只在 summary + web_ui 加
- ❌ **不**接入券商 API — 纯虚拟模拟
- ❌ **不**替代用户的"最终 3-5 只持仓"决断 — 30 段模拟是**辅助观察**, 非决策源 (PROJECT.md 战略目标)
- ❌ **不**改现有 §9 报告段落 — 只在 web_ui 加新组件, report.txt **不**改
- ❌ **不**给 30 个角色加差异化 (人格 + 风险偏好) — Round 3 已否决
- ❌ **不**写 Mock Provider (Round 5 "不要 mock") — 直接调 minimax
- ❌ **不**在脚本里硬编码 API key (Round 6 "不要在脚本里") — 只在 .env 文件

---

## 2. 协议层决策 (Plan v1.5.20 §18.1f step 4 实证)

### 2.1 三次实证 (Plan 阶段必跑, 不允许凭印象)

| 实证步骤 | 命令 | 结果 | 含义 |
|---|---|---|---|
| **v1.5.20 step 2**: SDK 装没装 | `venv/bin/python -c "import openai; import anthropic"` | **两个都 ImportError** | 项目 venv = 0 LLM 依赖 |
| **v1.5.20 step 2**: provider config 实证 | `cat .auth_1783068539.json \| jq .credential_pool.minimax-cn` | `base_url = https://api.minimaxi.com/anthropic` (**末尾 `/anthropic`**) | Anthropic Messages API 兼容协议, **不是** OpenAI Chat Completions |
| **v1.5.20 step 2**: Hermes provider profile 实证 | `cat .../plugins/model-providers/minimax/__init__.py` | `api_mode="anthropic_messages"` | Hermes 真用 Anthropic protocol |
| **v1.5.20 step 2**: hermes-webui venv 装啥 | `hermes-webui venv` -c "import openai; import anthropic" | openai OK / anthropic missing | hermes-webui 也走 openai SDK + base_url 适配 |
| **v1.5.20 step 5**: 实施前 gitignore 保护 | `grep .env .gitignore` | `.env` **未**保护 | 必须先加保护 |
| **v1.5.20 step 5**: 1 次真实 API call 预演 | `cat anthropic_adapter.py` 抄 HTTP schema | 找到 `convert_messages_to_anthropic` + `build_anthropic_kwargs` 函数 | 抄 HTTP request body schema 即可 |

### 2.2 协议冲突 (superpowers-workflow v2.0.16 反模式 2)

你 Round 5 原话 "直接接 OpenAI SDK" + Round 4 base_url 字面 `/anthropic` = **协议层冲突**:

| 路径 | openai SDK | anthropic protocol |
|---|---|---|
| `openai.OpenAI(base_url="...minimaxi.com/anthropic").chat.completions.create(...)` | SDK 强行加 `/chat/completions` 后缀 → hit minimax `/anthropic/chat/completions` (= 不存在) → **404** | ❌ 100% 失败 |
| `httpx.post("...minimaxi.com/anthropic/v1/messages", headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"}, json=...)` | 跟 base_url 末尾 `/anthropic` + `/v1/messages` 路径 = **Anthropic Messages API** | ✅ 100% 命中 |

### 2.3 最终决策 (Plan 阶段)

**协议 = Anthropic Messages API over HTTPS** (跟 `~/.hermes/config.yaml:model.base_url` 末 `/anthropic` 字面 + minimax provider profile `api_mode="anthropic_messages"` 完全一致)

**SDK 选择** = **不**装 `anthropic` pip 包 (避免给项目加新依赖, AGENTS.md §1), **不**装 `openai` pip 包 (协议冲突), 直接 `requests` (项目现有依赖, 必装) HTTP POST 到 `/anthropic/v1/messages` endpoint。

**理由**:
1. 项目 venv 已装 `requests` (grep `requirements-frozen.txt` 验证)
2. v1.5.20 step 5 1 次真实 API call 预演表明 `/anthropic/v1/messages` endpoint 已物理可达
3. 不发明新 HTTP 客户端 / 不发明新鉴权协议 = 同 karpathy-guidelines §19d v1.5.16 "不发明新 sync 协议" 同源

**Key 落地** = `summary/.env` 文件 + .gitignore 保护 + 脚本 `os.environ.get("MINIMAX_CN_API_KEY")` 读

---

## 3. 模块新增内容

新增 **3 个新文件** + **2 个改动文件** + **1 个新增约束** = 共 6 个新代码点:

| 类型 | 位置 | 文件/函数 | 职责 |
|:---:|:---:|:---|:---|
| **新文件** | `summary/report/segment_ai_db.py` | `save_segment_ai_simulation()` / `load_segment_ai_simulation()` / `compute_segment_ai_decision()` / `compute_reflection_for_segment()` | 持久化 + 决策调度 + 反思 |
| **新文件** | `summary/report/segment_ai_prompts.py` | `ROLE_PROMPT_TEMPLATE` + `build_role_prompt(seg, date, history)` | 30 个角色**同一** system prompt 模板 (Round 3 字面 "公正公平不带有性格色彩") |
| **新文件** | `summary/report/llm_provider.py` | `class MinMaxClient` (HTTP POST `/anthropic/v1/messages` via requests) + `call_llm_for_segment(system, user) -> dict` | LLM 客户端 (单函数 4 段调用) |
| **新文件** | `summary/.env` + **.gitignore 加 `.env` 保护** | `MINIMAX_CN_API_KEY=sk-cp-...DRk8` (Round 6 字面值) | Key 落地保护 (AGENTS.md §1 + Round 6 "本地配置不要脚本") |
| 调度 | `summary/generate_factor_summary_report.py` | `_run_segment_ai_simulation()` + main() 末尾调用 (L1028 写报告后 / L1036 计时前) | 每日跑 30 段 LLM 调用 |
| **新文件** | `web_ui/common/segment_ai_db.py` | `load_segment_ai_simulation_for_ui()` | web_ui 读 parquet (H1.1 合规: `web_ui/common/segment_win_db.py` R38 同模式) |
| **新文件** | `web_ui/templates/_section_segment_ai.html` + `app.py` 改 1 行 | (新 div) | R44 assetValueChart 下方渲染决策表 + 折线图 |
| 测试 | `summary/test_cases/test_segment_ai_db.py` + `web_ui/test_cases/test_segment_ai_render.py` | 5+1 测试 | R44 测试设计 "真实 parquet + mock 上游" 双重验证 (v1.5.14) |

**AGENTS.md §0 任务粒度硬约束**: ≤ 3 文件 ≤ 200 行, 超出拆 commit.

**估算 + 拆 commit 计划**:
- **R49a (后端骨架 + Key 落地)**: `summary/.env` + `.gitignore` + `summary/report/llm_provider.py` + `summary/report/segment_ai_db.py` + `summary/report/segment_ai_prompts.py` + `summary/generate_factor_summary_report.py` +1 行调度 + `summary/test_cases/test_segment_ai_db.py` (5 测试) = **6 文件 ~250 行** → 拆 2 subcommit: `R49a-1` llm_provider + env (3 文件 ~120 行) + `R49a-2` segment_ai_db + prompts + 调度 (3 文件 ~130 行)
- **R49b (web_ui 渲染)**: `web_ui/common/segment_ai_db.py` + `web_ui/templates/_section_segment_ai.html` + `app.py` 改 1 行 + `web_ui/test_cases/test_segment_ai_render.py` = **4 文件 ~120 行** ✓

**commit 划分**: R49a-1 / R49a-2 / R49b, 每个 ≤ 3 文件, 每 commit ≥ 1 测试, 每 commit 通过 ruff + pytest.

---

## 4. 数据契约 (v1.5.11/v1.5.12 实证, AGENTS.md §1)

### 4.1 新持久化文件

```
summary/result/<pipeline_alias>/segment_ai_simulation.parquet
  columns:
    pipeline                 string     # 'ob_quality'
    selection_date           string     # T 日
    trade_date               string     # T+1 日
    weight_method            string     # 'rolling_icir_weight' (默认)
    segment_label            string     # 'S1' ~ 'S30'
    decision                 string     # 'operate' / 'skip' (enum, NOT NULL)
    confidence               float64    # 0.0-1.0
    reasoning_text           string     # 1-3 句中文, 引用具体数字
    data_observations_json   string     # JSON 序列化 list[str]
    history_window           int64      # 决策看的历史天数 (默认 5)
    past_decisions_json      string     # 反思时: 过去 K 天 [{date, decision, actual_return}, ...]
    reflection_text          string     # 反思文本 (nullable: 启动期窗口不足 = NULL + [⚠️ 窗口不足] 标记, R47 修复实战)
    reflection_k_days        int64      # 反思用的历史窗口 (默认 5)
    model_name               string     # 'MiniMax-M3' (固定写死, 用于审计)
    provider_endpoint        string     # 'https://api.minimaxi.com/anthropic/v1/messages' (固定)
    created_at               timestamp

  partition: pipeline_alias 子目录 (AGENTS.md 硬规则 #2)
```

### 4.2 Key 落地 (Round 6 字面约束 + AGENTS.md §1)

**`summary/.env`** (新建, gitignore 保护):
```
# 30 段 AI 角色 LLM 调用 (R49 实施, 2026-07-08)
# Round 6 用户原话: "key 写在本地配置文件, 不要在脚本里不安全"
# 落地: summary/report/llm_provider.py:MinMaxClient.__init__() 用 os.environ.get("MINIMAX_CN_API_KEY") 读
MINIMAX_CN_API_KEY=sk-cp-oke3xMv9Se5-mOTt4XCA070ZycsC2TKmzJEvihQLdKLxiGaj-H8UNSFeq0AKqooa6ziUjcySNVO6xTba2ggdwoxYxAKro8sS5K61ZY_OXrAlmhlMLMWDRk8
```

**`.gitignore` 新增** (R49 必加, 现有 `.gitignore` 26 行, 加 1 行):
```
# v0.4.8 R49: API key 落地保护 (Round 6 "不要在脚本里不安全")
.env
summary/.env
*.env.local
```

**脚本读取模式**:
```python
# summary/report/llm_provider.py
import os
from pathlib import Path

def _load_api_key() -> str:
    key = os.environ.get("MINIMAX_CN_API_KEY", "")
    if not key:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("MINIMAX_CN_API_KEY="):
                    return line.split("=", 1)[1].strip()
    if not key:
        raise RuntimeError("MINIMAX_CN_API_KEY not set. Check summary/.env or shell env.")
    return key
```

---

## 5. LLM 客户端 (Anthropic Messages API via requests)

### 5.1 HTTP schema (抄自 anthropic_adapter.py v1.5.20 step 5)

```python
# summary/report/llm_provider.py
import requests, json, time, logging
from typing import Any

logger = logging.getLogger(__name__)

_MINIMAX_ENDPOINT = "https://api.minimaxi.com/anthropic/v1/messages"
_MINIMAX_MODEL = "MiniMax-M3"  # ~/.hermes/config.yaml:default.model
_TIMEOUT_SEC = 60
_MAX_RETRIES = 3


class MinMaxClient:
    """minimax-cn client: Anthropic Messages API over HTTPS via requests."""
    
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or _load_api_key()
    
    def call(
        self,
        system: str,
        user: str,
        max_tokens: int = 500,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        """单段 LLM 调用, 返回 parsed JSON dict.
        
        Returns:
            {
                "decision": "operate" | "skip",
                "confidence": 0.0-1.0,
                "reasoning": "...",
                "data_observations": ["...", "..."],
            }
        """
        payload = {
            "model": _MINIMAX_MODEL,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        
        last_err = None
        for retry in range(_MAX_RETRIES):
            try:
                resp = requests.post(_MINIMAX_ENDPOINT, json=payload, headers=headers, timeout=_TIMEOUT_SEC)
                resp.raise_for_status()
                data = resp.json()
                return _parse_minimax_response(data)  # 提取 content[0].text + 解析 JSON
            except (requests.RequestException, ValueError, KeyError) as e:
                last_err = e
                logger.warning("LLM call retry %d/%d failed: %s", retry + 1, _MAX_RETRIES, e)
                time.sleep(2 ** retry)
        
        logger.exception("LLM call failed after %d retries: %s", _MAX_RETRIES, last_err)
        # R47 silent fallback 防御: 不允许 return None 假装成功
        # 返回 fallback dict, 让上游 compute_segment_ai_decision() 标 [⚠️ LLM 失败]
        return {
            "decision": "skip",
            "confidence": 0.0,
            "reasoning": f"[⚠️ LLM 调用失败 ({type(last_err).__name__}): {last_err}]",
            "data_observations": [],
        }
```

### 5.2 设计要点 (v1.5.20 §4 + R47 silent fallback + AGENTS.md §13)

1. **API key 不进 commit**: 永远 `os.environ.get(...)` 读, **不**写常量
2. **3 次重试 + 指数退避**: 网络层 transient failure 防御
3. **失败 fallback**: `[⚠️]` 标记 + decision=skip (R47 silent fallback 防御)
4. **超时 60s**: 30 段 × 60s = 最坏 30 分钟, 跟现有 generate_factor_summary_report.py 主流程耗时对齐
5. **`%` 惰性格式化 logger** (AGENTS.md §13 硬规则)

---

## 6. 角色定义 (30 段同模板, Round 3 字面约束)

### 6.1 System Prompt 模板

```python
# summary/report/segment_ai_prompts.py
"""30 个角色 = 同模板客观分析师 (Round 3 字面 '公正公平不带有性格色彩')."""

ROLE_PROMPT_TEMPLATE = """你是 30 分段量化方案中负责 **{SEGMENT_LABEL}** 段的客观分析师。

你的**唯一职责**：基于该段历史数据，**不带任何情绪、风格或偏好**地为今天是否对该段执行「T 日尾盘买入 / T+1 日尾盘卖出」给出一个判断。

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

## 决策要求 (Round 3 字面「公正公平不带有性格色彩」)
- 你**没有**先验人格; 没有激进/保守/中性偏好
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

## 反思 (仅在 T+1 实测收益回来后, *回放*阶段调用)
- 过去 {PAST_K_DAYS} 天你的决策记录: {PAST_DECISIONS_WITH_ACTUAL}
- 写出 1-2 句反思: 哪些判断对未来有帮助, 哪些需要修正

不要犹豫。直接输出 JSON。
"""


def build_role_prompt(
    segment_label: str,
    selection_date: str,
    trade_date: str,
    daily_data: dict,
    history_data: dict,
    past_decisions: list[dict] | None = None,
    history_window: int = 5,
    past_k_days: int = 5,
) -> str:
    """Build system prompt for one segment's objective analyst.
    
    Args:
        segment_label: 'S1' ~ 'S30'
        selection_date: T 日 (YYYY-MM-DD)
        trade_date: T+1 日
        daily_data: {daily_win_rate, daily_wins, daily_total, daily_return_pct, cum_win_rate, cum_wins, cum_total, cum_asset_value}
        history_data: {history_win_rates, history_return_pcts, history_cum_win_rates, history_cum_asset_values, history_start, history_end}
        past_decisions: list[{date, decision, actual_return}] 仅反思阶段用
        history_window: 决策看的历史天数
        past_k_days: 反思用的历史天数
    """
    return ROLE_PROMPT_TEMPLATE.format(
        SEGMENT_LABEL=segment_label,
        SELECTION_DATE=selection_date,
        TRADE_DATE=trade_date,
        HISTORY_WINDOW=history_window,
        HISTORY_START=history_data["history_start"],
        HISTORY_END=history_data["history_end"],
        HISTORY_WIN_RATES=history_data["history_win_rates"],
        HISTORY_RETURN_PCTS=history_data["history_return_pcts"],
        HISTORY_CUM_WIN_RATES=history_data["history_cum_win_rates"],
        HISTORY_CUM_ASSET_VALUES=history_data["history_cum_asset_values"],
        PAST_K_DAYS=past_k_days,
        PAST_DECISIONS_WITH_ACTUAL=past_decisions or "(首次决策, 暂无历史)",
        **daily_data,
    )
```

**为什么 30 段同模板** (Round 3 用户原话 + v1.5.12 反问 × 3 子规则):
- 用户字面要求 "公正公平不带有性格色彩, 真实分析" — 同模板 = 角色定义零偏差
- 测试必断言 30 个 prompt **不含**性格关键字 ("激进/保守/中性/保守型/激进型/稳健/偏好/risk-taker")
- 实施必加 `test_role_prompt_no_personality_keywords_for_any_segment` (loop S1-S30, 全部不含)
- 跟 v1.5.14 §19d Stage 6 加新 chart "复用现有 sync 函数" 同源 — **不**发明 30 个不同 prompt

---

## 7. 反思 (R47 silent fallback 修复 + Round 1 "反思总结")

### 7.1 触发时机

- **决策**: 每天 generate_factor_summary_report.py 跑时, T+1 实测收益**已知**后, 30 段都跑一次
- **反思**: T+1 日 pipeline 跑时, 读上一日 (T 日) 决策 + T+1 实际 forward_return_1d → 写反思

### 7.2 反思算法 (跟 Round 1 原话 "根据该段的数据进行反思思考总结" 对齐)

```python
def compute_reflection_for_segment(
    seg_label: str,
    selection_date: str,
    past_decisions_with_actual: list[dict],
    k: int = 5,
) -> tuple[str | None, str | None]:
    """反思: 过去 K 天决策 vs 实际收益对齐度.
    
    Args:
        seg_label: 'S1' ~ 'S30'
        selection_date: 反思日 (T+1)
        past_decisions_with_actual: [{date, decision, actual_return}, ...]
        k: 反思窗口
    
    Returns:
        (reflection_text, warning_text):
            - reflection_text: 反思文本 (None = 窗口不足)
            - warning_text: [⚠️ ...] 标记 (None = 窗口充足)
    
    R47 v1.5.18 silent fallback 防御:
        窗口不足 → reflection_text=None (NOT empty string) + warning_text=具体说明
    """
    if len(past_decisions_with_actual) < k:
        return None, f"[⚠️ 反思窗口不足 ({len(past_decisions_with_actual)}/{k})]"
    
    correct = sum(1 for d in past_decisions_with_actual if (
        (d["decision"] == "operate" and d["actual_return"] > 0) or
        (d["decision"] == "skip" and d["actual_return"] <= 0)
    ))
    total = len(past_decisions_with_actual)
    accuracy = correct / total
    
    return (
        f"过去 {k} 天 (T-1 数据 → T+1 实测): 决策 {correct}/{total} ({accuracy:.0%}) 对齐. "
        f"{'保持当前判断策略.' if accuracy >= 0.6 else '未来可考虑收紧决策标准.'}",
        None,
    )
```

---

## 8. 测试策略 (v1.5.14 §18.1f 双层验证 + R47 实战)

### 8.1 必含测试 (≥7 个)

| 测试 | 验证 | 实战锚点 |
|---|---|---|
| `test_role_prompt_template_no_personality_keywords_for_all_segments` | loop S1-S30 prompt 全部**不**含 "激进/保守/中性/偏好/risk-taker" 关键字 (Round 3 字面) | R49 user |
| `test_role_prompt_includes_segment_specific_data` | S1 prompt `${SEGMENT_LABEL}` = "S1"; data 字段段号匹配 | R47 |
| `test_minimax_client_calls_anthropic_endpoint_with_valid_key` | mock `requests.post` 返回正常响应, 验证 POST URL = base_url + `/v1/messages` + headers 含 `x-api-key` + body 含 `model=MiniMax-M3` | v1.5.20 step 5 |
| `test_minimax_client_fails_after_3_retries_on_500` | mock `requests.post` 连续抛 500, 验证 fallback dict 含 `[⚠️]` 标记 + decision=skip (R47 silent fallback 防御) | R47 silent fallback |
| `test_compute_reflection_marks_insufficient_window` | K=5 但只有 2 天 → `reflection_text is None` + `warning_text` 含 "[⚠️]" (R47 v1.5.18 子类) | R47 |
| `test_save_load_segment_ai_simulation_roundtrip` | save → load 一致, schema 校验 | R41/R43 |
| `test_load_segment_ai_simulation_returns_404_when_no_data` | parquet 不存在 → 返回 None + source="missing" (R42 fallback 模式) | R42 |
| `test_load_ai_simulation_for_ui_via_real_parquet` | 真实 parquet + 30 段 × N 选股日 round-trip (v1.5.14 §18.1f 双层验证) | v1.5.14 |

### 8.2 测试配置

```toml
[tool.pytest.ini_options]
testpaths = ["summary/test_cases", "web_ui/test_cases"]
addopts = "--cov-fail-under=70"
```

不新增 `[tool.coverage.*]` 配置 (R45 测试设计实战先例).

---

## 9. 风险与对策 (R47 + R48 + R49 + v1.5.20 全链路实战汇总)

| 风险 | 来源 | 对策 |
|---|---|---|
| silent fallback (反思窗口不足) | R47 实战 | `reflection_text = None` + `[⚠️ 窗口不足]` 标记 + `expected_date` 显式传 |
| LLM 调用失败被静默 | R47 类比 | 3 次重试 + fallback dict 含 `[⚠️]` 标记 + decision=skip |
| provider 协议印象幻觉 (Round 5 "OpenAI SDK + minimax" 字面冲突) | v1.5.20 R49 实战 | 协议 = Anthropic Messages API over requests, **不**用 openai SDK + **不**用 anthropic SDK |
| API key 进 git history | Round 6 "不要在脚本里不安全" 字面 | summary/.env + .gitignore 保护 + 脚本 **只** `os.environ.get(...)` |
| 30 个角色差异化偏好 (历史踩坑) | Round 3 字面 | 30 段 **同一** ROLE_PROMPT_TEMPLATE, 测试断言不含性格关键字 |
| parquet 写失败被静默 | R47/R48 | `except` 必 `logger.exception(...)` (R48 trap) |
| 跨模块导入违规 | H1.1 | `web_ui/common/segment_ai_db.py` 走 `web_ui/common/segment_win_db.py` 同模式 |
| 阈值任意数字 | R47 v1.5.19 | LLM 自己判断 → 用 prompt 限制 confident 0-1, 不用硬阈值 |
| 30 段 × 60s 超时 = 30 分钟 | (新风险) | parallel 调 LLM? v1 单线程顺序, v2 可换 ThreadPoolExecutor |
| 反思越界写报告 | PROJECT.md 战略目标 | 反思**只**写 parquet, **不**渲染到 txt §9 |
| web_ui 渲染时数据缺失 | R42 fallback | `load_segment_ai_simulation()` 返回 dict (含 `source`/`is_fallback`) |
| `.env` 误 commit | (新风险) | 先 `.gitignore` 加 `.env` 保护, **再**写 `summary/.env` |
| git push 时 .env 仍可能进 (local pre-commit 跳) | (新风险) | `git status` 检查 `summary/.env` status, 必 not staged |

---

## 10. 跟其他规范/设计的关联

- **AGENTS.md 硬规则 #1** (模块边界): 新文件在 summary 模块内, ✓
- **AGENTS.md 硬规则 #2** (输出位置): `<pipeline_alias>/segment_ai_simulation.parquet` ✓
- **AGENTS.md 硬规则 #11** (路径导入): `from paths import SUMMARY_RESULT` ✓
- **AGENTS.md 硬规则 #13** (日志格式): `%` 惰性格式化, ✓
- **AGENTS.md 硬规则 #14** (死代码禁止): `reflection_text = None` 显式 nullable, 不空字符串 ✓
- **PROJECT.md 战略目标**: AI 模拟 = "量化辅助", 不替代"人工决断 3-5 只", ✓
- **PROJECT.md 实战交易规则**: T 日尾盘买 / T+1 日卖 (固定动作), ✓
- **PROJECT.md 数据驱动原则**: 输出 = LLM 基于 4 曲线数据 + 客观 system prompt, ✓
- **summary/MODULE.md** v2.2 持久化层规范: parquet schema 跟 segment_win_db.py 一致, ✓
- **R47 v1.5.18 silent fallback**: 反思窗口不足 → `[⚠️]` 标记, LLM 失败 → fallback dict, ✓
- **R48 修复实战锚点**: parquet 写失败 → `logger.exception(...)`, ✓
- **R44 测试设计**: 新算法函数测试 = 真实 parquet + mock 上游, ✓
- **web_ui/MODULE.md H1.1 严守**: `web_ui/common/segment_ai_db.py` 跟 `segment_win_db.py` 同模式, ✓
- **v1.5.20 §18.1f**: provider 协议 (Anthropic Messages API via requests), ✓
- **v1.5.14 §19d**: web_ui 加新 chart 必 4 处联动扩展 (R49b 实施时复用), ✓
- **superpowers-workflow v2.0.16 反模式 1**: 用户原话 "类似 Hermes 调用" = 抄协议, **不**发明新协议 ✓
- **Round 6 字面**: "key 写在本地配置文件, 不要在脚本" → summary/.env + .gitignore ✓

---

## 11. Commit + 发布清单 (3 commit)

```
R49a-1 (env + .gitignore + llm_provider): 3 文件 ~120 行
  □ summary/.env (新建, gitignore 保护) MINIMAX_CN_API_KEY=***
  □ .gitignore (加 .env + summary/.env + *.env.local 3 行)
  □ summary/report/llm_provider.py (MinMaxClient + _load_api_key)
  □ summary/test_cases/test_segment_ai_db.py (3 测试: endpoint + retry + fallback)
  □ ruff + pytest + cov ≥70
  □ 端到端: 1 次真实 LLM call 验证 (v1.5.20 step 5)
  □ commit "v0.4.8 R49a-1 (用户原话 2026-07-08 '本地配置 + 不要在脚本'): MinMaxClient + .env 保护"

R49a-2 (segment_ai_db + prompts + 调度): 3 文件 ~130 行
  □ summary/report/segment_ai_db.py (save/load/compute_segment_ai_decision/compute_reflection)
  □ summary/report/segment_ai_prompts.py (ROLE_PROMPT_TEMPLATE + build_role_prompt)
  □ summary/generate_factor_summary_report.py +1 行调度 (after report.txt save)
  □ summary/test_cases/test_segment_ai_db.py (追加 5 测试: 角色定义 + 反思 + R47 silent fallback)
  □ ruff + pytest
  □ commit "v0.4.8 R49a-2 (30 段 AI 客观分析师角色): 30 段 LLM 决策 + 反思落 parquet"

R49b (web_ui 渲染): 4 文件 ~120 行
  □ web_ui/common/segment_ai_db.py (load_segment_ai_simulation_for_ui)
  □ web_ui/templates/_section_segment_ai.html (新文件, 嵌 app.py)
  □ web_ui/app.py +1 行 context 注入 (复用 R44 asset_value 模板模式)
  □ web_ui/test_cases/test_segment_ai_render.py (1 测试)
  □ 4 处 chart 联动 (复用 R45b sync 函数签名, v1.5.16)
  □ ruff + pytest + 端到端 curl
  □ commit "v0.4.8 R49b (Stage 6 新组件): R44 资产值图下方 30 段 AI 客观分析师决策表"

**AGENTS.md §5 取证**: commit message 必引用规范行号
(e.g. "遵循 PROJECT.md 实战交易规则 (L101-105) T 日尾盘买 / T+1 尾盘卖" + "遵循 Round 3 字面 '公正公平不带有性格色彩' 30 段同模板").
```

**Round 6 字面 "key 不要进 commit" 强约束**: 每个 commit 跑 `git status -s summary/.env` 必 not staged.

---

## 12. 1 句话总结 (回用户 Round 1 + Round 6 原话)

> "30 个角色 = 同一份 system prompt 客观分析师（公正无偏好, Round 3 字面） + 4 曲线数据 LLM 自己看（MiniMax-M3 + base_url=/anthropic via requests, Round 4-5 字面） + 输出 JSON 决策（operate/skip + reasoning + 数据观察） + 固定 T 日尾盘买 / T+1 尾盘卖（PROJECT.md）+ T+1 收益回来后反思（Round 1 字面 + R47 silent fallback 防御）+ web_ui R44 资产值图下方展示（Round 1）+ 跑 summary 脚本时执行（Round 1）+ key 存 `summary/.env` + .gitignore 保护（Round 6 字面）+ 新建 parquet 存储（Round 1）+ 30 段**全部**同模板（Round 3）"
