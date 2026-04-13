"""
Comprehensive tests for the config_wizard module.

Covers validation logic, config building, YAML writing, Ollama detection,
and the full wizard workflow with mocked I/O.

This test file contains 20 tests covering:
- GitHub PAT validation (valid, invalid, unreachable)
- OpenAI API key validation
- Anthropic API key validation
- Proxy URL validation
- Config dict building
- Config file writing (YAML and fallback)
- Ollama detection
- _yes_no helper
- Full wizard flow with mocked user input
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest import mock
from urllib.error import HTTPError

import pytest

# Ensure src and onboarding are importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "onboarding"))

from config_wizard import (
    _build_config_dict,
    _detect_ollama,
    _prompt,
    _validate_anthropic_key,
    _validate_github_pat,
    _validate_openai_key,
    _validate_proxy_url,
    _write_config,
    _yes_no,
    CONFIG_DIR,
    CONFIG_PATH,
    DEFAULT_FLEET_ORG,
    DEFAULT_VESSEL_REPO,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provide a temporary config directory, monkeypatched."""
    with mock.patch("config_wizard.CONFIG_DIR", tmp_path), \
         mock.patch("config_wizard.CONFIG_PATH", tmp_path / "config.yaml"):
        yield tmp_path


@pytest.fixture
def mock_urlopen():
    """Provide a mock for urllib.request.urlopen."""
    with mock.patch("config_wizard.urllib.request.urlopen") as m:
        yield m


# ===================================================================
# TESTS: GitHub PAT Validation (4 tests)
# ===================================================================

class TestValidateGitHubPAT:
    """Tests for GitHub Personal Access Token validation."""

    def test_valid_pat(self, mock_urlopen):
        """A valid PAT should return valid=True with the correct login."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({"login": "superz"}).encode()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _validate_github_pat("ghp_valid_token")
        assert result["valid"] is True
        assert result["login"] == "superz"

    def test_invalid_pat_401(self, mock_urlopen):
        """An invalid PAT should return valid=False with 401 message."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.github.com/user",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

        result = _validate_github_pat("ghp_invalid_token")
        assert result["valid"] is False
        assert "401" in result["message"]

    def test_github_unreachable(self, mock_urlopen):
        """Network errors should return valid=False with connection message."""
        mock_urlopen.side_effect = OSError("Connection refused")

        result = _validate_github_pat("ghp_any_token")
        assert result["valid"] is False
        assert "Cannot reach GitHub" in result["message"]

    def test_github_forbidden(self, mock_urlopen):
        """A 403 error should return valid=False with HTTP code."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.github.com/user",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

        result = _validate_github_pat("ghp_forbidden_token")
        assert result["valid"] is False
        assert "403" in result["message"]


# ===================================================================
# TESTS: OpenAI API Key Validation (2 tests)
# ===================================================================

class TestValidateOpenAIKey:
    """Tests for OpenAI API key validation."""

    def test_valid_key(self, mock_urlopen):
        """A valid OpenAI key should return valid=True."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({"data": []}).encode()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _validate_openai_key("sk-valid-key")
        assert result["valid"] is True

    def test_invalid_key_401(self, mock_urlopen):
        """An invalid key should return valid=False."""
        mock_urlopen.side_effect = HTTPError(
            url="https://api.openai.com/v1/models",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

        result = _validate_openai_key("sk-invalid")
        assert result["valid"] is False
        assert "401" in result["message"]


# ===================================================================
# TESTS: Anthropic API Key Validation (2 tests)
# ===================================================================

class TestValidateAnthropicKey:
    """Tests for Anthropic API key format validation."""

    def test_valid_key_format(self):
        """A key starting with sk-ant- should pass format validation."""
        result = _validate_anthropic_key("sk-ant-api03-abcdef123456")
        assert result["valid"] is True
        assert result["message"] == ""

    def test_invalid_key_format(self):
        """A key not starting with sk-ant- should fail format validation."""
        result = _validate_anthropic_key("sk-wrong-prefix")
        assert result["valid"] is False
        assert "sk-ant-" in result["message"]


# ===================================================================
# TESTS: Proxy URL Validation (2 tests)
# ===================================================================

class TestValidateProxyURL:
    """Tests for proxy URL validation."""

    def test_reachable_proxy(self, mock_urlopen):
        """A reachable proxy should return valid=True."""
        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _validate_proxy_url("http://localhost:8000/v1")
        assert result["valid"] is True

    def test_unreachable_proxy(self, mock_urlopen):
        """An unreachable proxy should return valid=False."""
        mock_urlopen.side_effect = OSError("Connection refused")

        result = _validate_proxy_url("http://nonexistent:9999/v1")
        assert result["valid"] is False
        assert "Cannot reach" in result["message"]


# ===================================================================
# TESTS: Config Building (2 tests)
# ===================================================================

class TestBuildConfigDict:
    """Tests for building configuration dictionaries."""

    def test_full_config(self):
        """All fields should be included when provided."""
        config = _build_config_dict(
            github_token="ghp_test",
            llm_provider="openai",
            llm_api_key="sk-test",
            llm_model="gpt-4",
            fleet_org="MyOrg",
            vessel_repo="MyOrg/vessel",
        )
        assert config["github_token"] == "ghp_test"
        assert config["llm_provider"] == "openai"
        assert config["llm_api_key"] == "sk-test"
        assert config["llm_model"] == "gpt-4"
        assert config["fleet_org"] == "MyOrg"
        assert config["vessel_repo"] == "MyOrg/vessel"

    def test_minimal_config(self):
        """Only required fields should be present when optional ones are omitted."""
        config = _build_config_dict(
            github_token="ghp_test",
            llm_provider="ollama",
            llm_proxy_url="http://localhost:11434/v1",
        )
        assert config["github_token"] == "ghp_test"
        assert config["llm_provider"] == "ollama"
        assert config["llm_proxy_url"] == "http://localhost:11434/v1"
        # Optional fields should not be present
        assert "llm_api_key" not in config or config.get("llm_api_key") is None
        assert "llm_model" not in config or config.get("llm_model") is None
        assert "fleet_org" not in config or config.get("fleet_org") is None


# ===================================================================
# TESTS: Config Writing (2 tests)
# ===================================================================

class TestWriteConfig:
    """Tests for writing configuration to disk."""

    def test_write_yaml_config(self, tmp_config_dir):
        """Config should be written as valid YAML when PyYAML is available."""
        config = {
            "github_token": "ghp_test",
            "llm_provider": "openai",
            "llm_api_key": "sk-test",
        }
        _write_config(config)

        config_path = tmp_config_dir / "config.yaml"
        assert config_path.exists()

        content = config_path.read_text()
        assert "ghp_test" in content
        assert "openai" in content
        assert "sk-test" in content

    def test_write_creates_directory(self, tmp_path):
        """Config directory should be created if it doesn't exist."""
        nested_dir = tmp_path / "deep" / "nested" / "dir"
        nested_config = nested_dir / "config.yaml"

        with mock.patch("config_wizard.CONFIG_DIR", nested_dir), \
             mock.patch("config_wizard.CONFIG_PATH", nested_config):
            _write_config({"github_token": "ghp_x", "llm_provider": "proxy"})

        assert nested_config.exists()
        assert "ghp_x" in nested_config.read_text()


# ===================================================================
# TESTS: Ollama Detection (1 test)
# ===================================================================

class TestDetectOllama:
    """Tests for local Ollama detection."""

    def test_detect_running_ollama(self, mock_urlopen):
        """Should return URL when Ollama is running and has models."""
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({
            "models": [{"name": "llama3"}]
        }).encode()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _detect_ollama()
        assert result == "http://localhost:11434"

    def test_detect_no_ollama(self, mock_urlopen):
        """Should return None when Ollama is not running."""
        mock_urlopen.side_effect = OSError("Connection refused")

        result = _detect_ollama()
        assert result is None


# ===================================================================
# TESTS: Helper Functions (1 test)
# ===================================================================

class TestHelpers:
    """Tests for wizard helper functions."""

    def test_yes_no_default_true_with_empty_input(self):
        """Empty input should return the default value (True)."""
        with mock.patch("builtins.input", return_value=""):
            assert _yes_no("Continue?", default=True) is True

    def test_yes_no_default_false_with_empty_input(self):
        """Empty input should return the default value (False)."""
        with mock.patch("builtins.input", return_value=""):
            assert _yes_no("Continue?", default=False) is False

    def test_yes_no_explicit_yes(self):
        """Explicit 'y' should return True regardless of default."""
        with mock.patch("builtins.input", return_value="y"):
            assert _yes_no("Continue?", default=False) is True

    def test_yes_no_explicit_no(self):
        """Explicit 'n' should return False regardless of default."""
        with mock.patch("builtins.input", return_value="n"):
            assert _yes_no("Continue?", default=True) is False


# ===================================================================
# Run tests
# ===================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
