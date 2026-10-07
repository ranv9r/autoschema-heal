"""
Pluggable LLM Search Engine Client for CEGIS Synthesis.

Supports:
- Live API providers (Groq LPU, OpenAI, Gemini)
- Offline Mock Synthesizer (for hermetic benchmarks, CI/CD, and offline verification)
"""

from __future__ import annotations
import os
import re
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class BaseLLMClient(ABC):
    """Abstract interface for LLM synthesis backend."""

    @abstractmethod
    def generate_candidate(self, prompt: str) -> str:
        """Generates a candidate JQ transformation filter."""
        pass


class MockLLMClient(BaseLLMClient):
    """
    Offline mock synthesizer for hermetic unit testing, CI/CD, and local development.
    Requires zero API keys, network access, or external dependencies.
    Simulates genuine multi-round CEGIS convergence by adapting to counterexamples across rounds.
    """

    def __init__(self, simulate_cegis_round_failure: bool = True) -> None:
        self.simulate_cegis_round_failure = simulate_cegis_round_failure
        self.call_count = 0

    def generate_candidate(self, prompt: str) -> str:
        self.call_count += 1
        has_counterexample = "COUNTEREXAMPLE FROM PREVIOUS ROUND" in prompt

        # Heuristic detection of common schema patterns from prompt
        if "charge_id" in prompt or "amount_cents" in prompt:
            # Payment schema
            if self.simulate_cegis_round_failure and not has_counterexample:
                # Round 1: Naive program without millisecond/negative epoch safety or null guards
                return """
                {
                  transaction_id: .charge_id,
                  customer_email: .user.email,
                  amount_usd: (.amount_cents / 100),
                  created_at: (.timestamp_epoch | todate)
                }
                """
            else:
                # Round 2+: Refined sound program surviving adversarial fuzzing
                return """
                {
                  transaction_id: (.charge_id // .id // "unknown"),
                  customer_email: (.user?.email // .user?.contact // .email // "unknown@example.com"),
                  amount_usd: (if .amount_cents != null then (.amount_cents / 100) else (.amount // 0.0) end),
                  created_at: (
                    if (.timestamp_epoch != null and .timestamp_epoch >= 0) then
                      (if .timestamp_epoch > 100000000000 then (.timestamp_epoch / 1000) else .timestamp_epoch end | todate)
                    elif .created_at != null then
                      .created_at
                    else
                      "1970-01-01T00:00:00Z"
                    end
                  )
                }
                """

        elif "repository" in prompt or "delivery_id" in prompt:
            # GitHub webhook schema
            return """
            {
              event_id: (.delivery_id // .id // "evt_000"),
              repo_name: (.repository?.full_name // .repository?.name // "unknown/repo"),
              actor: (.sender?.login // .sender?.username // "ghost"),
              timestamp: (.created_at // "1970-01-01T00:00:00Z")
            }
            """

        elif "StageName" in prompt or "Amount" in prompt or "record_id" in prompt or "CanonicalOpportunity" in prompt:
            # Salesforce CRM schema
            return """
            {
              record_id: (.Id // .id // "SF_000"),
              account_name: (.Name // .account_name // "Unknown Account"),
              stage: (.StageName // .stage // "Prospecting"),
              revenue: (try (.Amount | tonumber) catch 0.0)
            }
            """

        # General fallback
        return "{}"


# Aliases for backwards compatibility
MockSynthesizer = MockLLMClient


class LiveAPIClient(BaseLLMClient):
    """
    Live API client connecting to OpenAI, Grok (xAI), or custom open-source endpoints
    (e.g., vLLM / Ollama) via OpenAI-compatible Chat Completions HTTP API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> None:
        self.provider = (provider or "").lower()
        
        # Check provider-specific keys or general keys
        self.api_key = (
            api_key
            or os.getenv("XAI_API_KEY")
            or os.getenv("GROK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        
        # Base URL resolution
        if base_url:
            self.base_url = base_url
        elif self.provider == "grok" or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY"):
            self.base_url = "https://api.x.ai/v1/chat/completions"
            if model == "gpt-4o-mini":
                model = "grok-2-latest"
        else:
            self.base_url = "https://api.openai.com/v1/chat/completions"

        self.model = model

    def generate_candidate(self, prompt: str) -> str:
        if not self.api_key and not ("localhost" in self.base_url or "127.0.0.1" in self.base_url):
            raise ValueError(
                "No API key configured for LiveAPIClient. Set XAI_API_KEY, GROK_API_KEY, or OPENAI_API_KEY, "
                "or pass api_key to LiveAPIClient."
            )
        
        try:
            import urllib.request
            import json

            headers = {
                "Content-Type": "application/json",
            }
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            req = urllib.request.Request(
                self.base_url,
                headers=headers,
                data=json.dumps({
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a formal program synthesis engine. Output ONLY the raw JQ transformation "
                                "filter. Never include markdown code fences, comments, or explanations."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                }).encode("utf-8"),
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Live API request to {self.base_url} failed: {e}")


class GroqClient(BaseLLMClient):
    """
    Native Groq LPU client using the official `groq` Python SDK.
    Provides ultra-fast inference for Groq models (e.g., 'openai/gpt-oss-120b',
    'llama-3.3-70b-versatile', 'llama-3.1-8b-instant').
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "openai/gpt-oss-120b",
        temperature: float = 0.2,
        max_completion_tokens: int = 2048,
        reasoning_effort: Optional[str] = None,
        stream: bool = False,
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.temperature = temperature
        self.max_completion_tokens = max_completion_tokens
        self.reasoning_effort = reasoning_effort
        self.stream = stream

    def generate_candidate(self, prompt: str) -> str:
        try:
            from groq import Groq
            client = Groq(api_key=self.api_key) if self.api_key else Groq()
        except ImportError:
            raise ImportError(
                "The `groq` package is required to use GroqClient. Install it with: pip install groq"
            )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a formal program synthesis engine. Output ONLY the raw JQ transformation "
                    "filter. Never include markdown code fences, comments, or explanations."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_completion_tokens": self.max_completion_tokens,
            "top_p": 1,
            "stop": None,
        }

        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort

        import time
        max_retries = 4
        for attempt in range(max_retries):
            try:
                if self.stream:
                    completion = client.chat.completions.create(stream=True, **kwargs)
                    chunks = []
                    for chunk in completion:
                        delta = chunk.choices[0].delta.content or ""
                        chunks.append(delta)
                    return "".join(chunks).strip()
                else:
                    completion = client.chat.completions.create(stream=False, **kwargs)
                    return (completion.choices[0].message.content or "").strip()
            except Exception as e:
                err_str = str(e).lower()
                if ("rate_limit" in err_str or "429" in err_str or "try again in" in err_str) and attempt < max_retries - 1:
                    # Exponential backoff on rate limits
                    wait_sec = 2.0 * (attempt + 1)
                    time.sleep(wait_sec)
                    continue
                raise


class XAIGrokClient(LiveAPIClient):
    """
    Client for xAI's Grok API (grok-2-latest, grok-beta) via xAI's OpenAI-compatible endpoint.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "grok-2-latest",
        base_url: str = "https://api.x.ai/v1/chat/completions",
    ) -> None:
        super().__init__(
            api_key=api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY"),
            model=model,
            base_url=base_url,
            provider="grok",
        )


