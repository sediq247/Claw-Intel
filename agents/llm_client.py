"""
ClawIntel Multi-Provider LLM Client
===================================
Supports: Gemini | Grok (xAI) | Cerebras | OpenRouter

Features:
- Configurable provider priority order
- Per-provider model fallback lists (user can override)
- Latest free / free-tier friendly models as defaults
- Automatic failover across providers and models
- Structured JSON generation helper
- Single async interface for all agents

Environment variables (all optional except keys you want to use):

  LLM_PROVIDERS=gemini,cerebras,openrouter,grok          # priority order

  GEMINI_API_KEY=...

  XAI_API_KEY=...                                        # Grok
  XAI_MODELS=grok-4.1-fast,grok-2-mini,grok-2

  CEREBRAS_API_KEY=...
  CEREBRAS_MODELS=gpt-oss-120b,llama3.1-8b,qwen-3.8-27b

  OPENROUTER_API_KEY=...
  OPENROUTER_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,openai/gpt-oss-120b:free,meta-llama/llama-3.3-70b-instruct:free,openrouter/free
"""

from __future__ import annotations

import os
import json
import asyncio
import re
from typing import Optional, List, Dict, Any, Union
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------
try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GENAI = True
except ImportError:
    genai = None
    genai_types = None
    HAS_GENAI = False

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    AsyncOpenAI = None
    HAS_OPENAI = False


# ---------------------------------------------------------------------------
# Default free / free-tier friendly model lists (Sep 2026)
# ---------------------------------------------------------------------------
DEFAULT_MODELS: Dict[str, List[str]] = {
    "gemini": [
        "gemini-3.8-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ],
    "grok": [
        "grok-4.1-fast",
        "grok-2-mini",
        "grok-2",
        "grok-3-mini",
    ],
    "cerebras": [
        "gpt-oss-120b",
        "llama3.1-8b",
        "qwen-3.8-27b",
        "llama3.3-70b",
    ],
    "openrouter": [
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "openai/gpt-oss-120b:free",
        "meta-llama/llama-3.3-70b-instruct:free",
        "nvidia/nemotron-3.5-lightning:free",
        "openrouter/free",
    ],
}

PROVIDER_BASE_URLS = {
    "grok": "https://api.x.ai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _parse_list(env_value: Optional[str], default: List[str]) -> List[str]:
    if not env_value:
        return default
    return [m.strip() for m in env_value.split(",") if m.strip()]


class LLMClient:
    """
    Unified multi-provider LLM client with automatic failover.
    """

    def __init__(self):
        # Provider priority (user configurable)
        providers_env = os.getenv("LLM_PROVIDERS", "gemini,cerebras,openrouter,grok")
        self.providers = [p.strip().lower() for p in providers_env.split(",") if p.strip()]

        # Per-provider model lists
        self.models: Dict[str, List[str]] = {
            "gemini": _parse_list(os.getenv("GEMINI_MODELS"), DEFAULT_MODELS["gemini"]),
            "grok": _parse_list(os.getenv("XAI_MODELS") or os.getenv("GROK_MODELS"), DEFAULT_MODELS["grok"]),
            "cerebras": _parse_list(os.getenv("CEREBRAS_MODELS"), DEFAULT_MODELS["cerebras"]),
            "openrouter": _parse_list(os.getenv("OPENROUTER_MODELS"), DEFAULT_MODELS["openrouter"]),
        }

        # API keys
        self.keys = {
            "gemini": os.getenv("GEMINI_API_KEY"),
            "grok": os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY"),
            "cerebras": os.getenv("CEREBRAS_API_KEY"),
            "openrouter": os.getenv("OPENROUTER_API_KEY"),
        }

        # Clients (lazy)
        self._gemini_client = None
        self._openai_clients: Dict[str, Any] = {}

        self._available = self._detect_available()
        if not self._available:
            print("⚠️ LLMClient: No LLM providers configured. Running in pure fallback mode.")
        else:
            print(f"✅ LLMClient ready. Providers (priority): {', '.join(self._available)}")

    def _detect_available(self) -> List[str]:
        available = []
        for p in self.providers:
            if p == "gemini" and self.keys["gemini"] and HAS_GENAI:
                available.append(p)
            elif p in ("grok", "cerebras", "openrouter") and self.keys.get(p) and HAS_OPENAI:
                available.append(p)
        return available

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_gemini(self):
        if self._gemini_client is None and self.keys["gemini"] and HAS_GENAI:
            self._gemini_client = genai.Client(api_key=self.keys["gemini"])
        return self._gemini_client

    def _get_openai_client(self, provider: str):
        if provider not in self._openai_clients:
            key = self.keys.get(provider)
            base = PROVIDER_BASE_URLS.get(provider)
            if not key or not base or not HAS_OPENAI:
                return None
            extra_headers = {}
            if provider == "openrouter":
                extra_headers = {
                    "HTTP-Referer": "https://clawintel.local",
                    "X-Title": "ClawIntel",
                }
            self._openai_clients[provider] = AsyncOpenAI(
                api_key=key,
                base_url=base,
                default_headers=extra_headers or None,
            )
        return self._openai_clients[provider]

    async def _call_gemini(
        self,
        model: str,
        contents: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        client = self._get_gemini()
        if not client:
            raise RuntimeError("Gemini client not available")

        config = None
        if genai_types:
            kwargs = {
                "temperature": temperature,
                "max_output_tokens": max_tokens,
            }
            if json_mode:
                kwargs["response_mime_type"] = "application/json"
            config = genai_types.GenerateContentConfig(**kwargs)

        def _sync_call():
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )

        response = await asyncio.wait_for(asyncio.to_thread(_sync_call), timeout=25)
        text = response.text if hasattr(response, "text") else str(response)
        return (text or "").strip()

    async def _call_openai_compatible(
        self,
        provider: str,
        model: str,
        contents: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> str:
        client = self._get_openai_client(provider)
        if not client:
            raise RuntimeError(f"{provider} client not available")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": contents})

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await asyncio.wait_for(
            client.chat.completions.create(**kwargs),
            timeout=30,
        )
        return (response.choices[0].message.content or "").strip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def generate(
        self,
        contents: str,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
        preferred_provider: Optional[str] = None,
    ) -> str:
        """
        Generate text using the configured provider chain.
        Tries providers in order (or preferred first), then models inside each.
        Raises if every attempt fails.
        """
        order = list(self._available)
        if preferred_provider and preferred_provider in order:
            order.remove(preferred_provider)
            order.insert(0, preferred_provider)

        last_error = None
        for provider in order:
            models = self.models.get(provider, [])
            for model in models:
                try:
                    if provider == "gemini":
                        # Gemini does not take a separate system message in the same way;
                        # we prepend it.
                        full = f"{system}\n\n{contents}" if system else contents
                        return await self._call_gemini(
                            model=model,
                            contents=full,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            json_mode=json_mode,
                        )
                    else:
                        return await self._call_openai_compatible(
                            provider=provider,
                            model=model,
                            contents=contents,
                            system=system,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            json_mode=json_mode,
                        )
                except Exception as e:
                    err = str(e)
                    # Skip clearly unavailable models quickly
                    if any(x in err.lower() for x in ("404", "not_found", "not found", "model_not_found", "does not exist")):
                        print(f"⚠️ LLMClient: {provider}/{model} unavailable, trying next...")
                        last_error = e
                        continue
                    if any(x in err.lower() for x in ("rate", "quota", "429", "resource_exhausted", "insufficient")):
                        print(f"⚠️ LLMClient: {provider}/{model} rate/quota limited, trying next...")
                        last_error = e
                        continue
                    print(f"⚠️ LLMClient: {provider}/{model} error: {e}")
                    last_error = e
                    continue

        raise RuntimeError(f"All LLM providers/models exhausted. Last error: {last_error}")

    async def generate_json(
        self,
        contents: str,
        system: Optional[str] = None,
        temperature: float = 0.4,
        max_tokens: int = 1200,
        preferred_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate and parse JSON. Adds a strong instruction to return pure JSON.
        """
        json_instruction = (
            "\n\nIMPORTANT: Respond with valid JSON only. "
            "No markdown, no code fences, no explanation outside the JSON object."
        )
        full_contents = contents + json_instruction

        text = await self.generate(
            contents=full_contents,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            preferred_provider=preferred_provider,
        )

        # Clean possible markdown fences
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Last resort: try to extract the first {...} block
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            raise ValueError(f"Failed to parse JSON from LLM response: {cleaned[:300]}...")

    @property
    def is_available(self) -> bool:
        return len(self._available) > 0

    def status(self) -> Dict[str, Any]:
        return {
            "available_providers": self._available,
            "configured_order": self.providers,
            "models": {p: self.models[p] for p in self._available},
        }


# Singleton instance used by all agents
llm = LLMClient()


# Convenience alias for older code that expected "gemini"
async def generate(contents: str, config=None, **kwargs) -> Any:
    """
    Backward-compatible thin wrapper.
    Older agents called gemini.generate(...). We keep a similar surface.
    """
    temperature = 0.7
    max_tokens = 280
    if config and hasattr(config, "temperature"):
        temperature = config.temperature or 0.7
    if config and hasattr(config, "max_output_tokens"):
        max_tokens = config.max_output_tokens or 280

    text = await llm.generate(
        contents=contents,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )

    # Mimic the old response object that had .text
    class _Resp:
        def __init__(self, t):
            self.text = t

    return _Resp(text)
