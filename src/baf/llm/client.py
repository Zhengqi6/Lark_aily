"""OpenAI-compatible LLM client.

Wraps the official `openai` SDK so we can point it at the zhizengzeng relay.
Keeps the surface tiny — we only need chat completions + JSON mode.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from ..config import Config


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0

    def as_json(self) -> Any:
        """Best-effort JSON parse — tolerates ```json fences."""
        txt = self.content.strip()
        if txt.startswith("```"):
            # strip fences
            lines = txt.splitlines()
            # drop first line (``` or ```json) and last line (```)
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            txt = "\n".join(lines).strip()
        return json.loads(txt)


class LLMClient:
    def __init__(self, cfg: Config):
        if not cfg.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY 未配置。请运行 `baf init` 或在 .env 中设置 LLM_API_KEY。"
            )
        self._cfg = cfg
        self._client = OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url)
        self.default_model = cfg.llm_model

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        retries: int = 2,
    ) -> LLMResponse:
        mdl = model or self.default_model
        kwargs: dict = {
            "model": mdl,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            # zhizengzeng relays OpenAI's response_format; fall back silently if unsupported
            kwargs["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                resp = self._client.chat.completions.create(**kwargs)
                latency = int((time.time() - t0) * 1000)
                usage = resp.usage
                return LLMResponse(
                    content=resp.choices[0].message.content or "",
                    model=resp.model or mdl,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                    total_tokens=getattr(usage, "total_tokens", 0) or 0,
                    latency_ms=latency,
                )
            except Exception as e:
                last_err = e
                # For json_mode rejection, retry without it
                if json_mode and "response_format" in str(e):
                    kwargs.pop("response_format", None)
                    json_mode = False
                    continue
                if attempt < retries:
                    time.sleep(1 + attempt)
                    continue
                raise
        # should not reach here
        raise RuntimeError(f"LLM call failed: {last_err}")


_default: LLMClient | None = None


def get_default_client(cfg: Config | None = None) -> LLMClient:
    global _default
    if _default is None:
        _default = LLMClient(cfg or Config.load())
    return _default
