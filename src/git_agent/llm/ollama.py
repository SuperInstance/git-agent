"""
git_agent.llm.ollama — Local Ollama LLM provider.

Connects to a local Ollama server and provides:
    - Model listing and selection
    - Streaming support
    - Synchronous and async completion
    - Token usage tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import (
    BaseLLMProvider,
    LLMError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
    TokenUsage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ollama Provider
# ---------------------------------------------------------------------------

class OllamaProvider(BaseLLMProvider):
    """Local Ollama LLM provider.

    Connects to a local Ollama server (default: http://localhost:11434).

    Parameters
    ----------
    model:
        Model name (e.g. "llama3", "codellama", "mistral").
    base_url:
        Ollama server base URL.
    temperature:
        Default sampling temperature.
    max_tokens:
        Default max response tokens.
    timeout:
        Request timeout in seconds.
    **kwargs:
        Additional parameters (e.g. ``keep_alive``, ``num_ctx``).
    """

    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        model: str = "llama3",
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 120.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **kwargs,
        )
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._last_usage: Optional[TokenUsage] = None

    # -- Model info ---------------------------------------------------------

    def _get_model_info(self) -> ModelInfo:
        return ModelInfo(
            name=self.model,
            provider="ollama",
            context_window=self._extra.get("num_ctx", 4096),
            max_output_tokens=self.max_tokens,
            supports_tools=False,
            supports_streaming=True,
            supports_vision=False,
            cost_per_1k_prompt_tokens=0.0,
            cost_per_1k_completion_tokens=0.0,
        )

    def get_last_usage(self) -> Optional[TokenUsage]:
        return self._last_usage

    # -- Model management ---------------------------------------------------

    def list_models(self) -> List[Dict[str, Any]]:
        """List available models on the Ollama server."""
        url = f"{self.base_url}/api/tags"
        try:
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", [])
        except Exception as exc:
            raise LLMUnavailableError(f"Failed to list models: {exc}") from exc

    def pull_model(self, model: str) -> Dict[str, Any]:
        """Pull/download a model from the Ollama registry."""
        url = f"{self.base_url}/api/pull"
        payload = json.dumps({"name": model, "stream": False}).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=600)  # downloads can be slow
            return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise LLMError(f"Failed to pull model '{model}': {exc}") from exc

    def show_model_info(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Get detailed info about a model."""
        url = f"{self.base_url}/api/show"
        payload = json.dumps({"name": model or self.model}).encode("utf-8")
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"},
                                      method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise LLMError(f"Failed to show model info: {exc}") from exc

    # -- Message conversion -------------------------------------------------

    @staticmethod
    def _convert_messages(messages: List[Dict[str, str]]) -> str:
        """Convert messages to Ollama prompt format.

        Ollama /api/chat accepts messages in OpenAI-compatible format,
        but we build a simple prompt for /api/generate as fallback.
        """
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "").upper()
            content = m.get("content", "")
            if role == "SYSTEM":
                parts.append(f"<|system|>\n{content}")
            elif role == "USER":
                parts.append(f"<|user|>\n{content}")
            elif role == "ASSISTANT":
                parts.append(f"<|assistant|]\n{content}")
            else:
                parts.append(content)
        return "\n\n".join(parts)

    # -- Sync completion ----------------------------------------------------

    def _complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        self.validate_messages(messages)

        # Use /api/chat endpoint (OpenAI-compatible)
        payload = self._build_chat_payload(messages, temperature, max_tokens, **kwargs)
        response = self._request(payload)

        message = response.get("message", {})
        content = message.get("content", "")

        # Track usage
        eval_count = response.get("eval_count", 0)
        prompt_count = response.get("prompt_eval_count", 0)
        self._last_usage = TokenUsage(
            prompt_tokens=prompt_count,
            completion_tokens=eval_count,
            total_tokens=prompt_count + eval_count,
        )

        return content

    # -- Async completion ---------------------------------------------------

    async def _complete_async(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> str:
        self.validate_messages(messages)
        payload = self._build_chat_payload(messages, temperature, max_tokens, **kwargs)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, self._request, payload)

        message = response.get("message", {})
        content = message.get("content", "")

        eval_count = response.get("eval_count", 0)
        prompt_count = response.get("prompt_eval_count", 0)
        self._last_usage = TokenUsage(
            prompt_tokens=prompt_count,
            completion_tokens=eval_count,
            total_tokens=prompt_count + eval_count,
        )

        return content

    # -- Streaming ----------------------------------------------------------

    async def stream(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream tokens from Ollama."""
        self.validate_messages(messages)
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        payload = self._build_chat_payload(
            messages, temperature, max_tokens, stream=True, **kwargs,
        )

        loop = asyncio.get_event_loop()

        def _do_stream():
            url = f"{self.base_url}/api/chat"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                for raw_line in resp:
                    decoded = raw_line.decode("utf-8").strip()
                    if not decoded:
                        continue
                    try:
                        chunk = json.loads(decoded)
                        message = chunk.get("message", {})
                        content = message.get("content", "")
                        if content:
                            yield content
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
            except Exception as exc:
                raise LLMUnavailableError(f"Streaming error: {exc}") from exc

        chunks: List[str] = []
        for chunk in _do_stream():
            chunks.append(chunk)
        for chunk in chunks:
            yield chunk

    # -- HTTP layer ---------------------------------------------------------

    def _request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to Ollama server."""
        url = f"{self.base_url}/api/chat"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMUnavailableError(
                f"Cannot connect to Ollama at {self.base_url}: {exc}"
            ) from exc
        except Exception as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

    # -- Payload builders ---------------------------------------------------

    def _build_chat_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Build the Ollama /api/chat payload."""
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": kwargs.get("stream", False),
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # Add Ollama-specific options from kwargs
        for key in ("keep_alive", "format", "num_ctx", "num_batch",
                     "top_k", "top_p", "repeat_penalty"):
            if key in self._extra:
                payload["options"][key] = self._extra[key]

        return payload
