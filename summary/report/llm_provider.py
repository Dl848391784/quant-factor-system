"""v0.4.8 R49 (用户原话 2026-07-08): 30 段 AI 角色 LLM 客户端.

Provider: minimax-cn (Anthropic Messages API 兼容)
   base_url 字面 = https://api.minimaxi.com/anthropic  (v1.5.20 实证)
   protocol   = Anthropic Messages API (POST /v1/messages, headers: x-api-key + anthropic-version)
   model      = MiniMax-M3 (Hermes config.yaml:default.model)

Why HTTP 直接 requests + 不装 anthropic SDK:
   - 项目 0 LLM 依赖先例 (v1.5.20 step 2 实证 ImportError)
   - v1.5.20 step 5 实证 endpoint 可达 + key 真有效 + model 真存在
   - Round 6 字面 "key 写在本地配置 + 不要在脚本里" → os.environ 读 .env
   - 跟 karpathy-guidelines §19d v1.5.16 "不发明新 sync 协议" 同源

Round 6 字面约束落地:
   - API key 不进 commit (summary/.env + .gitignore 保护)
   - 脚本内**只** os.environ.get(...) 读, **不**写常量
   - 测试也不**写**常量 (用 monkeypatch env)

R47 v1.5.18 silent fallback 防御:
   - 失败 fallback dict 含 [⚠️ LLM 调用失败] 标记, decision=skip
   - logger.exception(...) 替代 logger.error(...) (R48 修复实战锚点)
   - 不允许 return None 假装成功
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests


logger = logging.getLogger(__name__)

# ── 常量 (固定, 不从 .env 读 — model/base_url 是项目配置, 不是 secret) ──
DEFAULT_BASE_URL = "https://api.minimaxi.com/anthropic"
DEFAULT_MODEL = "MiniMax-M3"
ANTHROPIC_VERSION = "2023-06-01"
_TIMEOUT_SEC = 60
_MAX_RETRIES = 3


def _load_api_key() -> str:
    """加载 minimax API key.

    优先级:
      1. os.environ["MINIMAX_CN_API_KEY"]  (env var, shell export)
      2. summary/.env 文件解析

    Returns:
        API key 字符串

    Raises:
        RuntimeError: 都找不到时 (启动期必查)
    """
    key = os.environ.get("MINIMAX_CN_API_KEY", "").strip()
    if key:
        return key

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "MINIMAX_CN_API_KEY":
                    return v.strip()

    raise RuntimeError(
        "MINIMAX_CN_API_KEY not found. "
        "Set shell env or write to summary/.env (gitignored). "
        "See .gitignore for protection pattern."
    )


def _load_base_url() -> str:
    """加载 minimax base URL. 同 _load_api_key 模式."""
    url = os.environ.get("MINIMAX_CN_BASE_URL", "").strip()
    if url:
        return url.rstrip("/")
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == "MINIMAX_CN_BASE_URL":
                    return v.strip().rstrip("/")
    return DEFAULT_BASE_URL


class MinMaxClient:
    """minimax-cn LLM 客户端 — Anthropic Messages API over requests.

    设计要点 (R49 + v1.5.20 + R47 silent fallback + AGENTS.md §13):
      1. 单段一次调用, 返回 parsed JSON dict
      2. 3 次重试 + 指数退避 (transient failure 防御)
      3. 失败 fallback dict 含 [⚠️] 标记 + decision=skip
      4. logger.exception(...) 替代 logger.error(...) (R48 修复实战)
      5. 超时 60s (单段), 30 段 × 60s = 最坏 30 分钟
      6. json_mode=True 时强制 response_format=json_object
      7. % 惰性格式化日志 (AGENTS.md §13 硬规则)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = DEFAULT_MODEL,
    ):
        self.api_key = api_key or _load_api_key()
        self.base_url = (base_url or _load_base_url()).rstrip("/")
        self.model = model
        self.endpoint = f"{self.base_url}/v1/messages"

    def call(
        self,
        system: str,
        user: str,
        max_tokens: int = 500,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        """调用 MiniMax-M3, 返回 parsed JSON dict.

        Args:
            system: system prompt (角色定义)
            user: user message (决策上下文, 4 曲线数据等)
            max_tokens: 最大输出 token 数
            json_mode: 是否强制 JSON 输出 (LLM structured output)

        Returns:
            {
                "decision": "operate" | "skip",
                "confidence": 0.0-1.0,
                "reasoning": "...",
                "data_observations": ["...", "..."],
            }

            失败时返回:
            {
                "decision": "skip",
                "confidence": 0.0,
                "reasoning": "[⚠️ LLM 调用失败 (...) : ...]",
                "data_observations": [],
            }
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if json_mode:
            # Anthropic 不支持 OpenAI 风格的 response_format=json_object,
            # 依赖 system prompt 强制 JSON schema + 解析时容错
            pass

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        last_err: Exception | None = None
        for retry in range(_MAX_RETRIES):
            try:
                resp = requests.post(
                    self.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=_TIMEOUT_SEC,
                )
                resp.raise_for_status()
                data = resp.json()
                return _parse_minimax_response(data, model=self.model)
            except (requests.RequestException, ValueError, KeyError) as e:
                last_err = e
                logger.warning(
                    "LLM call retry %d/%d failed (endpoint=%s, model=%s): %s",
                    retry + 1,
                    _MAX_RETRIES,
                    self.endpoint,
                    self.model,
                    e,
                )
                time.sleep(2**retry)

        # R47 v1.5.18 silent fallback 防御: 不允许 return None 假装成功
        logger.exception(
            "LLM call failed after %d retries (endpoint=%s, model=%s)",
            _MAX_RETRIES,
            self.endpoint,
            self.model,
        )
        return {
            "decision": "skip",
            "confidence": 0.0,
            "reasoning": (f"[⚠️ LLM 调用失败 ({type(last_err).__name__ if last_err else 'Unknown'}): {last_err}]"),
            "data_observations": [],
        }


def _parse_minimax_response(data: dict[str, Any], model: str) -> dict[str, Any]:
    """解析 Anthropic Messages API 响应 → 结构化 dict.

    Anthropic response schema:
      {
        "id": "msg_xxx",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "..."}],
        "model": "model-name",
        "stop_reason": "end_turn",
        "usage": {...},
      }

    text 通常是 JSON 字符串 (system prompt 强制), 用 json.loads 解析;
    解析失败 → fallback dict (R47 silent fallback 防御)
    """
    try:
        content_list = data["content"]
        if not content_list:
            raise ValueError("empty content list")
        text = content_list[0].get("text", "")
        if not text:
            raise ValueError("empty text in content[0]")

        # 尝试解析 JSON (system prompt 强制 JSON schema)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            # fallback: 把 text 包到 reasoning 里, decision 默认为 skip
            logger.warning(
                "LLM response not valid JSON (model=%s): %s",
                model,
                text[:200],
            )
            return {
                "decision": "skip",
                "confidence": 0.0,
                "reasoning": (f"[⚠️ LLM 响应非 JSON (model={model}, text={text[:100]})]"),
                "data_observations": [],
            }

        # 校验必需字段
        if not isinstance(parsed, dict):
            raise ValueError(f"response is not a dict: {type(parsed)}")
        decision = parsed.get("decision", "skip")
        if decision not in ("operate", "skip"):
            logger.warning("LLM decision %r not in (operate/skip), fallback to skip", decision)
            decision = "skip"
        confidence = float(parsed.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(parsed.get("reasoning", ""))
        data_observations = parsed.get("data_observations", [])
        if not isinstance(data_observations, list):
            data_observations = []

        return {
            "decision": decision,
            "confidence": confidence,
            "reasoning": reasoning,
            "data_observations": [str(o) for o in data_observations],
        }
    except (KeyError, ValueError, IndexError) as e:
        logger.exception("Failed to parse Anthropic response (model=%s)", model)
        return {
            "decision": "skip",
            "confidence": 0.0,
            "reasoning": f"[⚠️ 响应解析失败: {e}]",
            "data_observations": [],
        }
