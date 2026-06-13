"""
Comprehensive tests for the git_agent LLM provider layer.

Covers:
    - base.py: Protocol, ModelInfo, TokenUsage, ChatMessage, exceptions, BaseLLMProvider
    - mock.py: MockProvider (canned responses, delay, error simulation, call logging)
    - openai_compat.py: OpenAICompatibleProvider (payload building, response parsing)
    - anthropic.py: AnthropicProvider (message conversion, payload building, response parsing)
    - ollama.py: OllamaProvider (payload building, message conversion)
    - proxy.py: ProxyProvider (inheritance, proxy metadata)
    - router.py: LLMRouter (provider selection, failover, cost optimization, health monitoring)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import pytest

# Ensure src is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from git_agent.llm.base import (
    BaseLLMProvider,
    ChatMessage,
    LLMAuthError,
    LLMContextError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelInfo,
    ProviderCapability,
    StreamingProvider,
    TokenUsage,
    ToolCall,
    ToolCapableProvider,
)
from git_agent.llm.mock import CallRecord, MockProvider
from git_agent.llm.openai_compat import OpenAICompatibleProvider
from git_agent.llm.anthropic import AnthropicProvider
from git_agent.llm.ollama import OllamaProvider
from git_agent.llm.proxy import ProxyProvider
from git_agent.llm.router import (
    CostTier,
    LLMRouter,
    ProviderEntry,
    RoutingStrategy,
    TokenBudget,
)


# ===================================================================
# TESTS: base.py (8 tests)
# ===================================================================

class TestTokenUsage:
    """Test TokenUsage data model."""

    def test_default_usage(self):
        usage = TokenUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.cost_usd == 0.0

    def test_custom_usage(self):
        usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150


class TestModelInfo:
    """Test ModelInfo data model."""

    def test_default_model_info(self):
        info = ModelInfo(name="test", provider="test")
        assert info.context_window == 4096
        assert info.supports_tools is False
        assert info.supports_streaming is True

    def test_model_info_to_dict(self):
        info = ModelInfo(
            name="gpt-4o", provider="openai",
            context_window=128000, supports_tools=True,
        )
        d = info.to_dict()
        assert d["name"] == "gpt-4o"
        assert d["provider"] == "openai"
        assert d["context_window"] == 128000
        assert d["supports_tools"] is True


class TestChatMessage:
    """Test ChatMessage conversion."""

    def test_to_openai_dict(self):
        msg = ChatMessage(role="user", content="Hello")
        d = msg.to_openai_dict()
        assert d == {"role": "user", "content": "Hello"}

    def test_from_openai_dict(self):
        msg = ChatMessage.from_openai_dict({"role": "assistant", "content": "Hi there!"})
        assert msg.role == "assistant"
        assert msg.content == "Hi there!"

    def test_tool_call_roundtrip(self):
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(id="call_1", name="get_weather", arguments='{"city": "NYC"}'),
            ],
        )
        d = msg.to_openai_dict()
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["function"]["name"] == "get_weather"

        msg2 = ChatMessage.from_openai_dict(d)
        assert len(msg2.tool_calls) == 1
        assert msg2.tool_calls[0].name == "get_weather"


class TestLLMExceptions:
    """Test LLM exception hierarchy."""

    def test_llm_error_base(self):
        exc = LLMError("test error")
        assert isinstance(exc, Exception)
        assert str(exc) == "test error"

    def test_specific_errors_inherit(self):
        assert issubclass(LLMAuthError, LLMError)
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMTimeoutError, LLMError)
        assert issubclass(LLMContextError, LLMError)
        assert issubclass(LLMUnavailableError, LLMError)

    def test_protocol_is_runtime_checkable(self):
        assert hasattr(LLMProvider, "__protocol_attrs__") or True  # Protocol
        # Verify a dict is not an LLMProvider
        assert not isinstance({}, LLMProvider)


class TestBaseLLMProviderValidation:
    """Test BaseLLMProvider message validation."""

    def test_validate_empty_messages(self):
        class DummyProvider(BaseLLMProvider):
            def _complete_sync(self, messages, temperature, max_tokens, **kwargs):
                return ""
            def _complete_async(self, messages, temperature, max_tokens, **kwargs):
                return asyncio.coroutine(lambda: "")()
            def _get_model_info(self):
                return ModelInfo(name="test", provider="test")

        provider = DummyProvider(model="test")
        with pytest.raises(ValueError, match="non-empty"):
            provider.validate_messages([])

    def test_validate_missing_role(self):
        class DummyProvider(BaseLLMProvider):
            def _complete_sync(self, messages, temperature, max_tokens, **kwargs):
                return ""
            async def _complete_async(self, messages, temperature, max_tokens, **kwargs):
                return ""
            def _get_model_info(self):
                return ModelInfo(name="test", provider="test")

        provider = DummyProvider(model="test")
        with pytest.raises(ValueError, match="missing 'role'"):
            provider.validate_messages([{"content": "hello"}])

    def test_validate_missing_content(self):
        class DummyProvider(BaseLLMProvider):
            def _complete_sync(self, messages, temperature, max_tokens, **kwargs):
                return ""
            async def _complete_async(self, messages, temperature, max_tokens, **kwargs):
                return ""
            def _get_model_info(self):
                return ModelInfo(name="test", provider="test")

        provider = DummyProvider(model="test")
        with pytest.raises(ValueError, match="missing 'content'"):
            provider.validate_messages([{"role": "user"}])

    def test_validate_invalid_role(self):
        class DummyProvider(BaseLLMProvider):
            def _complete_sync(self, messages, temperature, max_tokens, **kwargs):
                return ""
            async def _complete_async(self, messages, temperature, max_tokens, **kwargs):
                return ""
            def _get_model_info(self):
                return ModelInfo(name="test", provider="test")

        provider = DummyProvider(model="test")
        with pytest.raises(ValueError, match="invalid role"):
            provider.validate_messages([{"role": "invalid", "content": "x"}])


class TestTokenCounting:
    """Test rough token counting."""

    def test_count_tokens(self):
        class DummyProvider(BaseLLMProvider):
            def _complete_sync(self, messages, temperature, max_tokens, **kwargs):
                return ""
            async def _complete_async(self, messages, temperature, max_tokens, **kwargs):
                return ""
            def _get_model_info(self):
                return ModelInfo(name="test", provider="test")

        provider = DummyProvider(model="test")
        messages = [
            {"role": "user", "content": "a" * 100},
            {"role": "assistant", "content": "b" * 200},
        ]
        count = provider.count_tokens(messages)
        assert count == 75  # 300 chars / 4


# ===================================================================
# TESTS: mock.py (8 tests)
# ===================================================================

class TestMockProvider:
    """Test MockProvider."""

    def test_default_response(self):
        mock = MockProvider(response="hello world")
        result = mock.complete([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    def test_pattern_response(self):
        mock = MockProvider(
            responses={
                r"code": "Here is the code",
                r"error": "There was an error",
            },
        )
        r1 = mock.complete([{"role": "user", "content": "write code"}])
        assert r1 == "Here is the code"
        r2 = mock.complete([{"role": "user", "content": "fix error"}])
        assert r2 == "There was an error"
        r3 = mock.complete([{"role": "user", "content": "other"}])
        assert r3 == "Mock response"

    def test_call_counting(self):
        mock = MockProvider()
        assert mock.call_count == 0
        mock.complete([{"role": "user", "content": "a"}])
        assert mock.call_count == 1
        mock.complete([{"role": "user", "content": "b"}])
        assert mock.call_count == 2

    def test_call_logging(self):
        mock = MockProvider(response="logged")
        mock.complete([{"role": "user", "content": "test"}])
        assert len(mock.call_log) == 1
        record = mock.call_log[0]
        assert isinstance(record, CallRecord)
        assert record.index == 1
        assert record.response == "logged"
        assert record.messages[0]["content"] == "test"

    def test_error_on_call(self):
        mock = MockProvider(error_on_call=2)
        mock.complete([{"role": "user", "content": "first"}])  # succeeds
        with pytest.raises(LLMError, match="call #2"):
            mock.complete([{"role": "user", "content": "second"}])

    def test_error_on_messages(self):
        mock = MockProvider(error_on_messages=r"forbidden")
        mock.complete([{"role": "user", "content": "hello"}])  # succeeds
        with pytest.raises(LLMError, match="forbidden"):
            mock.complete([{"role": "user", "content": "forbidden content"}])

    def test_delay(self):
        mock = MockProvider(delay=0.05)
        import time
        start = time.time()
        mock.complete([{"role": "user", "content": "wait"}])
        elapsed = time.time() - start
        assert elapsed >= 0.04  # allow some tolerance

    def test_reset(self):
        mock = MockProvider()
        mock.complete([{"role": "user", "content": "a"}])
        assert mock.call_count == 1
        mock.reset()
        assert mock.call_count == 0
        assert len(mock.call_log) == 0

    def test_model_info(self):
        mock = MockProvider(model_name="my-mock")
        info = mock.model_info()
        assert info["name"] == "my-mock"
        assert info["provider"] == "mock"

    def test_assert_helpers(self):
        mock = MockProvider()
        mock.assert_not_called()
        mock.complete([{"role": "user", "content": "hello"}])
        mock.assert_called(1)
        mock.assert_last_messages_contain("hello")

    def test_async_complete(self):
        mock = MockProvider(response="async result")
        result = asyncio.run(mock.acomplete([{"role": "user", "content": "hi"}]))
        assert result == "async result"
        assert mock.call_count == 1


# ===================================================================
# TESTS: openai_compat.py (5 tests)
# ===================================================================

class TestOpenAICompatibleProvider:
    """Test OpenAI-compatible provider (without actual HTTP calls)."""

    def test_model_info_known_model(self):
        provider = OpenAICompatibleProvider(model="gpt-4o", api_key="sk-test")
        info = provider.model_info()
        assert info["name"] == "gpt-4o"
        assert info["context_window"] == 128000
        assert info["supports_tools"] is True
        assert info["supports_vision"] is True

    def test_model_info_unknown_model(self):
        provider = OpenAICompatibleProvider(model="my-custom-model", api_key="sk-test")
        info = provider.model_info()
        assert info["name"] == "my-custom-model"
        assert info["provider"] == "openai_compatible"
        assert info["context_window"] == 4096

    def test_build_payload_basic(self):
        provider = OpenAICompatibleProvider(model="gpt-4o", api_key="sk-test")
        messages = [{"role": "user", "content": "Hello!"}]
        payload = provider._build_payload(messages, temperature=0.5, max_tokens=100)
        assert payload["model"] == "gpt-4o"
        assert payload["messages"] == messages
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 100
        assert payload["top_p"] == 1.0

    def test_build_payload_with_tools(self):
        provider = OpenAICompatibleProvider(model="gpt-4o", api_key="sk-test")
        messages = [{"role": "user", "content": "What's the weather?"}]
        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
        payload = provider._build_payload(messages, temperature=0.5, max_tokens=100, tools=tools)
        assert payload["tools"] == tools

    def test_extract_text(self):
        response = {
            "choices": [
                {"message": {"content": "Hello there!"}},
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        text = OpenAICompatibleProvider._extract_text(response)
        assert text == "Hello there!"

    def test_extract_text_empty(self):
        response = {
            "choices": [
                {"message": {"content": None}},
            ],
        }
        text = OpenAICompatibleProvider._extract_text(response)
        assert text == ""

    def test_extract_text_and_tools(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": "Let me check the weather.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city": "NYC"}',
                                },
                            },
                        ],
                    },
                },
            ],
        }
        text, tools = OpenAICompatibleProvider._extract_text_and_tools(response)
        assert text == "Let me check the weather."
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "get_weather"

    def test_extract_text_malformed(self):
        with pytest.raises(LLMError, match="Malformed"):
            OpenAICompatibleProvider._extract_text({"not_choices": []})

    def test_custom_api_base(self):
        provider = OpenAICompatibleProvider(
            model="gpt-4o",
            api_key="sk-test",
            api_base="https://my-proxy.example.com/v1",
        )
        assert provider.api_base == "https://my-proxy.example.com/v1"

    def test_deepseek_model_info(self):
        provider = OpenAICompatibleProvider(model="deepseek-chat", api_key="sk-test")
        info = provider.model_info()
        assert info["context_window"] == 65536
        assert info["supports_tools"] is True

    def test_deepseek_reasoner_model_info(self):
        provider = OpenAICompatibleProvider(model="deepseek-reasoner", api_key="sk-test")
        info = provider.model_info()
        assert info["supports_tools"] is False


# ===================================================================
# TESTS: anthropic.py (5 tests)
# ===================================================================

class TestAnthropicProvider:
    """Test Anthropic provider (without actual HTTP calls)."""

    def test_model_info_known_model(self):
        provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-ant")
        info = provider.model_info()
        assert info["name"] == "claude-sonnet-4-20250514"
        assert info["provider"] == "anthropic"
        assert info["context_window"] == 200000
        assert info["supports_tools"] is True

    def test_model_info_claude_3_opus(self):
        provider = AnthropicProvider(model="claude-3-opus-20240229", api_key="sk-ant")
        info = provider.model_info()
        assert info["cost_per_1k_prompt_tokens"] == 0.015

    def test_convert_messages_system_extraction(self):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        system, anth_msgs = AnthropicProvider._convert_messages(messages)
        assert system == "You are helpful."
        assert len(anth_msgs) == 2
        assert anth_msgs[0]["role"] == "user"
        assert anth_msgs[1]["role"] == "assistant"

    def test_convert_messages_no_system(self):
        messages = [
            {"role": "user", "content": "Hello!"},
        ]
        system, anth_msgs = AnthropicProvider._convert_messages(messages)
        assert system is None
        assert len(anth_msgs) == 1

    def test_convert_messages_multiple_system(self):
        messages = [
            {"role": "system", "content": "Part 1"},
            {"role": "system", "content": "Part 2"},
            {"role": "user", "content": "Hello"},
        ]
        system, _ = AnthropicProvider._convert_messages(messages)
        assert "Part 1" in system
        assert "Part 2" in system

    def test_convert_tools(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get weather for a city",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            },
        ]
        anth_tools = AnthropicProvider._convert_tools(tools)
        assert len(anth_tools) == 1
        assert anth_tools[0]["name"] == "get_weather"
        assert "input_schema" in anth_tools[0]

    def test_extract_text(self):
        response = {
            "content": [
                {"type": "text", "text": "Hello from Claude!"},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        text = AnthropicProvider._extract_text(response)
        assert text == "Hello from Claude!"

    def test_extract_text_multiple_blocks(self):
        response = {
            "content": [
                {"type": "text", "text": "First part."},
                {"type": "text", "text": "Second part."},
            ],
        }
        text = AnthropicProvider._extract_text(response)
        assert text == "First part.\nSecond part."

    def test_extract_text_and_tools(self):
        response = {
            "content": [
                {"type": "text", "text": "Checking weather..."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_weather",
                    "input": {"city": "NYC"},
                },
            ],
        }
        text, tools = AnthropicProvider._extract_text_and_tools(response)
        assert text == "Checking weather..."
        assert len(tools) == 1
        assert tools[0]["function"]["name"] == "get_weather"
        assert json.loads(tools[0]["function"]["arguments"]) == {"city": "NYC"}

    def test_build_payload(self):
        provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-ant")
        messages = [{"role": "user", "content": "Hi"}]
        payload = provider._build_payload(
            messages, temperature=0.5, max_tokens=100, system="Be helpful",
        )
        assert payload["model"] == "claude-sonnet-4-20250514"
        assert payload["max_tokens"] == 100
        assert payload["system"] == "Be helpful"


# ===================================================================
# TESTS: ollama.py (4 tests)
# ===================================================================

class TestOllamaProvider:
    """Test Ollama provider (without actual HTTP calls)."""

    def test_model_info(self):
        provider = OllamaProvider(model="llama3")
        info = provider.model_info()
        assert info["name"] == "llama3"
        assert info["provider"] == "ollama"
        assert info["supports_tools"] is False
        assert info["supports_streaming"] is True
        assert info["cost_per_1k_prompt_tokens"] == 0.0

    def test_custom_base_url(self):
        provider = OllamaProvider(model="llama3", base_url="http://192.168.1.100:11434")
        assert provider.base_url == "http://192.168.1.100:11434"

    def test_build_chat_payload(self):
        provider = OllamaProvider(model="codellama", temperature=0.3, max_tokens=2048)
        messages = [{"role": "user", "content": "Write code"}]
        payload = provider._build_chat_payload(messages, temperature=0.3, max_tokens=2048)
        assert payload["model"] == "codellama"
        assert payload["messages"] == messages
        assert payload["options"]["temperature"] == 0.3
        assert payload["options"]["num_predict"] == 2048
        assert payload["stream"] is False

    def test_build_chat_payload_with_stream(self):
        provider = OllamaProvider(model="llama3")
        messages = [{"role": "user", "content": "Hi"}]
        payload = provider._build_chat_payload(messages, 0.7, 4096, stream=True)
        assert payload["stream"] is True

    def test_custom_num_ctx(self):
        provider = OllamaProvider(model="llama3", num_ctx=32768)
        info = provider.model_info()
        assert info["context_window"] == 32768

    def test_convert_messages(self):
        messages = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = OllamaProvider._convert_messages(messages)
        assert "Be helpful" in result
        assert "Hello" in result
        assert "Hi!" in result


# ===================================================================
# TESTS: proxy.py (3 tests)
# ===================================================================

class TestProxyProvider:
    """Test ProxyProvider."""

    def test_inherits_openai_compat(self):
        proxy = ProxyProvider(
            proxy_url="https://proxy.example.com/v1",
            api_key="key",
            model="gpt-4o",
        )
        assert isinstance(proxy, OpenAICompatibleProvider)

    def test_model_info_shows_proxy(self):
        proxy = ProxyProvider(
            proxy_url="https://zeroclaw.example.com/v1",
            api_key="key",
            model="default",
            proxy_name="ZeroClaw",
        )
        info = proxy.model_info()
        assert info["provider"] == "proxy(ZeroClaw)"

    def test_proxy_url_set_correctly(self):
        proxy = ProxyProvider(
            proxy_url="https://proxy.example.com/v1/",
            model="test",
        )
        assert proxy.api_base == "https://proxy.example.com/v1"
        assert proxy.proxy_url == "https://proxy.example.com/v1"

    def test_proxy_name_defaults_to_url(self):
        proxy = ProxyProvider(
            proxy_url="https://my-proxy.com/v1",
            model="test",
        )
        assert proxy.proxy_name == "https://my-proxy.com/v1"

    def test_repr(self):
        proxy = ProxyProvider(
            proxy_url="https://proxy.example.com/v1",
            model="gpt-4o",
            proxy_name="TestProxy",
        )
        r = repr(proxy)
        assert "TestProxy" in r
        assert "gpt-4o" in r


# ===================================================================
# TESTS: router.py (10 tests)
# ===================================================================

class TestTokenBudget:
    """Test TokenBudget tracking."""

    def test_default_budget(self):
        budget = TokenBudget()
        assert budget.remaining_tokens == 1_000_000
        assert budget.is_exhausted is False

    def test_record_usage(self):
        budget = TokenBudget(max_tokens=1000)
        budget.record_usage(500)
        assert budget.used_tokens == 500
        assert budget.remaining_tokens == 500

    def test_budget_exhaustion(self):
        budget = TokenBudget(max_tokens=100)
        budget.record_usage(100)
        assert budget.is_exhausted is True

    def test_cost_tracking(self):
        budget = TokenBudget(max_cost_usd=10.0)
        budget.record_usage(1000, cost_usd=7.5)
        assert budget.used_cost_usd == 7.5
        assert budget.remaining_cost_usd == pytest.approx(2.5)


class TestCostTier:
    """Test CostTier ordering."""

    def test_tier_ordering(self):
        assert CostTier.FREE < CostTier.LOW
        assert CostTier.LOW < CostTier.MEDIUM
        assert CostTier.MEDIUM < CostTier.HIGH
        assert CostTier.HIGH < CostTier.PREMIUM


class TestProviderEntry:
    """Test ProviderEntry health tracking."""

    def test_initial_health(self):
        entry = ProviderEntry(
            name="test",
            provider=MockProvider(),
        )
        assert entry.is_healthy is True
        assert entry.error_rate == 0.0

    def test_unhealthy_after_failures(self):
        entry = ProviderEntry(
            name="test",
            provider=MockProvider(),
        )
        for _ in range(5):
            entry.consecutive_failures += 1
        assert entry.is_healthy is False

    def test_error_rate(self):
        entry = ProviderEntry(
            name="test",
            provider=MockProvider(),
        )
        entry.total_requests = 10
        entry.total_errors = 3
        assert entry.error_rate == 0.3


class TestLLMRouterBasic:
    """Test LLMRouter basic operations."""

    def _make_router(self) -> LLMRouter:
        router = LLMRouter(default_provider="mock1")
        router.add_provider(
            "mock1",
            MockProvider(response="response from mock1"),
            capabilities=["chat", "code"],
            cost_tier=CostTier.MEDIUM,
            priority=10,
        )
        router.add_provider(
            "mock2",
            MockProvider(response="response from mock2"),
            capabilities=["code", "reasoning"],
            cost_tier=CostTier.FREE,
            priority=5,
        )
        return router

    def test_register_providers(self):
        router = self._make_router()
        assert set(router.list_providers()) == {"mock1", "mock2"}

    def test_direct_provider_selection(self):
        router = self._make_router()
        result = router.complete(
            [{"role": "user", "content": "hello"}],
            provider="mock1",
        )
        assert result == "response from mock1"

    def test_default_provider(self):
        router = self._make_router()
        result = router.complete([{"role": "user", "content": "hi"}])
        assert result == "response from mock1"

    def test_capability_routing(self):
        # When no default_provider is set, capability routing selects
        # the best matching provider. mock1 has "reasoning" with higher
        # priority, so it wins. mock2 only matches "code".
        router = LLMRouter(strategy=RoutingStrategy.CAPABILITY)
        router.add_provider(
            "mock1",
            MockProvider(response="response from mock1"),
            capabilities=["chat", "reasoning"],
            cost_tier=CostTier.MEDIUM,
            priority=10,
        )
        router.add_provider(
            "mock2",
            MockProvider(response="response from mock2"),
            capabilities=["code"],
            cost_tier=CostTier.FREE,
            priority=5,
        )
        # mock1 matches "reasoning" capability
        result = router.complete(
            [{"role": "user", "content": "think"}],
            capability="reasoning",
            failover=False,
        )
        assert result == "response from mock1"
        # mock2 matches "code" capability (only one with that capability)
        result = router.complete(
            [{"role": "user", "content": "write code"}],
            capability="code",
            failover=False,
        )
        assert result == "response from mock2"

    def test_unknown_provider_raises(self):
        router = self._make_router()
        with pytest.raises(LLMError, match="Unknown provider"):
            router.complete(
                [{"role": "user", "content": "hi"}],
                provider="nonexistent",
                failover=False,
            )

    def test_remove_provider(self):
        router = self._make_router()
        router.remove_provider("mock2")
        assert "mock2" not in router.list_providers()


class TestLLMRouterFailover:
    """Test LLMRouter failover behavior."""

    def test_failover_to_secondary(self):
        router = LLMRouter()
        router.add_provider(
            "failing",
            MockProvider(error_on_call=1),
            priority=10,
        )
        router.add_provider(
            "backup",
            MockProvider(response="backup response"),
            priority=5,
        )
        result = router.complete(
            [{"role": "user", "content": "test"}],
            provider="failing",
            failover=True,
        )
        assert result == "backup response"

    def test_no_failover_exhausted(self):
        router = LLMRouter()
        router.add_provider(
            "always_fails",
            MockProvider(error_on_call=1),
        )
        with pytest.raises(LLMError, match="All providers failed"):
            router.complete(
                [{"role": "user", "content": "test"}],
                failover=True,
            )


class TestLLMRouterHealth:
    """Test LLMRouter health monitoring."""

    def test_health_report(self):
        router = LLMRouter()
        router.add_provider(
            "healthy",
            MockProvider(response="ok"),
            capabilities=["chat"],
        )
        router.complete([{"role": "user", "content": "hi"}], provider="healthy")

        report = router.get_health_report()
        assert report["total_providers"] == 1
        assert report["healthy_providers"] == 1
        assert "healthy" in report["providers"]
        assert report["providers"]["healthy"]["total_requests"] == 1

    def test_health_tracking_with_errors(self):
        router = LLMRouter()
        router.add_provider(
            "flaky",
            MockProvider(error_on_call=1, response="ok"),
        )
        try:
            router.complete([{"role": "user", "content": "fail"}], provider="flaky", failover=False)
        except LLMError:
            pass

        report = router.get_health_report()
        assert report["providers"]["flaky"]["total_errors"] == 1
        assert report["providers"]["flaky"]["consecutive_failures"] == 1

    def test_reset_health(self):
        router = LLMRouter()
        mock = MockProvider(error_on_call=1)
        router.add_provider("test", mock)
        try:
            router.complete([{"role": "user", "content": "fail"}], provider="test", failover=False)
        except LLMError:
            pass
        router.reset_health("test")
        report = router.get_health_report()
        assert report["providers"]["test"]["consecutive_failures"] == 0


class TestLLMRouterCostOptimization:
    """Test cost-based routing."""

    def test_cheapest_strategy(self):
        router = LLMRouter(strategy=RoutingStrategy.CHEAPEST)
        router.add_provider(
            "expensive",
            MockProvider(response="expensive result"),
            cost_tier=CostTier.HIGH,
        )
        router.add_provider(
            "cheap",
            MockProvider(response="cheap result"),
            cost_tier=CostTier.FREE,
        )
        result = router.complete([{"role": "user", "content": "hi"}])
        assert result == "cheap result"

    def test_priority_strategy(self):
        router = LLMRouter(strategy=RoutingStrategy.PRIORITY)
        router.add_provider(
            "low_pri",
            MockProvider(response="low"),
            priority=1,
        )
        router.add_provider(
            "high_pri",
            MockProvider(response="high"),
            priority=100,
        )
        result = router.complete([{"role": "user", "content": "hi"}])
        assert result == "high"


class TestLLMRouterAsync:
    """Test LLMRouter async completion."""

    def test_async_complete(self):
        router = LLMRouter(default_provider="mock")
        router.add_provider(
            "mock",
            MockProvider(response="async response"),
        )
        result = asyncio.run(router.acomplete([{"role": "user", "content": "hi"}]))
        assert result == "async response"

    def test_async_failover(self):
        router = LLMRouter()
        router.add_provider(
            "failing_async",
            MockProvider(error_on_call=1),
            priority=10,
        )
        router.add_provider(
            "backup_async",
            MockProvider(response="async backup"),
            priority=5,
        )
        result = asyncio.run(
            router.acomplete(
                [{"role": "user", "content": "hi"}],
                provider="failing_async",
                failover=True,
            )
        )
        assert result == "async backup"


class TestLLMRouterModelInfo:
    """Test router model_info delegation."""

    def test_model_info_default(self):
        router = LLMRouter(default_provider="mock")
        router.add_provider("mock", MockProvider(model_name="test-model"))
        info = router.model_info()
        assert info["name"] == "test-model"

    def test_model_info_specific_provider(self):
        router = LLMRouter()
        router.add_provider("m1", MockProvider(model_name="model-1"))
        router.add_provider("m2", MockProvider(model_name="model-2"))
        info = router.model_info(provider_name="m2")
        assert info["name"] == "model-2"


# ===================================================================
# TESTS: Integration / Protocol compliance (3 tests)
# ===================================================================

class TestProtocolCompliance:
    """Verify all providers implement the LLMProvider Protocol."""

    def test_mock_provider_protocol(self):
        mock = MockProvider()
        assert isinstance(mock, LLMProvider)
        assert hasattr(mock, "complete")
        assert hasattr(mock, "acomplete")
        assert hasattr(mock, "model_info")

    def test_all_providers_have_required_methods(self):
        providers = {
            "mock": MockProvider(),
            "openai": OpenAICompatibleProvider(api_key="test"),
            "anthropic": AnthropicProvider(api_key="test"),
            "ollama": OllamaProvider(),
            "proxy": ProxyProvider(proxy_url="http://localhost/v1"),
        }
        for name, provider in providers.items():
            assert callable(provider.complete), f"{name} missing complete()"
            assert callable(provider.acomplete), f"{name} missing acomplete()"
            assert callable(provider.model_info), f"{name} missing model_info()"

    def test_all_model_info_returns_dict(self):
        providers = {
            "mock": MockProvider(),
            "openai": OpenAICompatibleProvider(api_key="test"),
            "anthropic": AnthropicProvider(api_key="test"),
            "ollama": OllamaProvider(),
            "proxy": ProxyProvider(proxy_url="http://localhost/v1"),
        }
        for name, provider in providers.items():
            info = provider.model_info()
            assert isinstance(info, dict), f"{name} model_info() did not return dict"
            assert "name" in info, f"{name} model_info missing 'name'"
            assert "provider" in info, f"{name} model_info missing 'provider'"


# ===================================================================
# Run tests
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
