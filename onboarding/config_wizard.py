#!/usr/bin/env python3
"""
git_agent.onboarding.config_wizard — Interactive configuration wizard.

Guides the user through setting up their git-agent configuration:
  1. GitHub Personal Access Token (PAT)
  2. LLM provider selection (OpenAI / Anthropic / Ollama / Proxy)
  3. Provider-specific credentials
  4. Fleet organization and vessel repo name
  5. Connection validation

Saves configuration to ~/.git-agent/config.yaml.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIG_DIR = Path.home() / ".git-agent"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

GITHUB_USER_ENDPOINT = "https://api.github.com/user"
OPENAI_MODELS_ENDPOINT = "https://api.openai.com/v1/models"
ANTHROPIC_MODELS_ENDPOINT = "https://api.anthropic.com/v1/messages"

DEFAULT_FLEET_ORG = "SuperInstance"
DEFAULT_VESSEL_REPO = "my-vessel"

PROMPT_CHARS = 60  # max chars for prompts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cprint(color: str, text: str) -> None:
    """Print colored text to stderr."""
    colors = {
        "red": "\033[0;31m",
        "green": "\033[0;32m",
        "yellow": "\033[1;33m",
        "blue": "\033[0;34m",
        "cyan": "\033[0;36m",
        "bold": "\033[1m",
        "reset": "\033[0m",
    }
    prefix = colors.get(color, "")
    suffix = colors.get("reset", "")
    print(f"{prefix}{text}{suffix}", file=sys.stderr, flush=True)


def _prompt(prompt_text: str, default: str = "", password: bool = False) -> str:
    """Prompt the user for input, with optional default value."""
    suffix = f" [{default}]: " if default else ": "
    prompt_str = prompt_text + suffix

    if password:
        import getpass
        value = getpass.getpass(prompt_str)
    else:
        try:
            value = input(prompt_str)
        except EOFError:
            value = ""

    return value.strip() or default


def _yes_no(prompt_text: str, default: bool = True) -> bool:
    """Prompt for a yes/no answer."""
    hint = "Y/n" if default else "y/N"
    answer = _prompt(f"{prompt_text} ({hint})", "").lower()
    if not answer:
        return default
    return answer in ("y", "yes", "1", "true")


def _detect_ollama() -> Optional[str]:
    """Detect if Ollama is running locally and return the base URL."""
    for url in ("http://localhost:11434", "http://127.0.0.1:11434"):
        try:
            req = urllib.request.Request(f"{url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name", "") for m in data.get("models", [])]
                if models:
                    return url
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            pass
    return None


def _validate_github_pat(token: str) -> Dict[str, Any]:
    """Validate a GitHub PAT by hitting the /user endpoint.

    Returns a dict with 'valid', 'login', and 'message' keys.
    """
    try:
        req = urllib.request.Request(
            GITHUB_USER_ENDPOINT,
            headers={"Authorization": f"token {token}", "User-Agent": "git-agent-setup"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return {"valid": True, "login": data.get("login", ""), "message": ""}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {"valid": False, "login": "", "message": "Invalid token (401 Unauthorized)."}
        return {"valid": False, "login": "", "message": f"GitHub API error: HTTP {exc.code}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"valid": False, "login": "", "message": f"Cannot reach GitHub: {exc}"}


def _validate_openai_key(api_key: str) -> Dict[str, Any]:
    """Validate an OpenAI API key by listing models.

    Returns a dict with 'valid' and 'message' keys.
    """
    try:
        req = urllib.request.Request(
            OPENAI_MODELS_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return {"valid": True, "message": ""}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {"valid": False, "message": "Invalid API key (401 Unauthorized)."}
        return {"valid": False, "message": f"OpenAI API error: HTTP {exc.code}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"valid": False, "message": f"Cannot reach OpenAI: {exc}"}


def _validate_anthropic_key(api_key: str) -> Dict[str, Any]:
    """Validate an Anthropic API key.

    Returns a dict with 'valid' and 'message' keys.
    """
    # Anthropic doesn't have a lightweight validation endpoint like OpenAI.
    # We just check the key format (starts with sk-ant-).
    if api_key.startswith("sk-ant-"):
        return {"valid": True, "message": ""}
    return {"valid": False, "message": "Anthropic keys should start with 'sk-ant-'."}


def _validate_proxy_url(url: str) -> Dict[str, Any]:
    """Validate a proxy URL is reachable.

    Returns a dict with 'valid' and 'message' keys.
    """
    try:
        req = urllib.request.Request(url.rstrip("/") + "/models", method="GET")
        urllib.request.urlopen(req, timeout=5)
        return {"valid": True, "message": ""}
    except urllib.error.HTTPError as exc:
        # 401 or 404 still means the server is reachable
        if exc.code in (401, 403, 404):
            return {"valid": True, "message": f"Server reachable (HTTP {exc.code})."}
        return {"valid": False, "message": f"Proxy returned HTTP {exc.code}."}
    except (urllib.error.URLError, OSError) as exc:
        return {"valid": False, "message": f"Cannot reach proxy: {exc}"}


def _build_config_dict(
    github_token: str,
    llm_provider: str,
    llm_api_key: Optional[str] = None,
    llm_proxy_url: Optional[str] = None,
    llm_model: Optional[str] = None,
    fleet_org: Optional[str] = None,
    vessel_repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a config dict suitable for YAML serialization."""
    config: Dict[str, Any] = {
        "github_token": github_token,
        "llm_provider": llm_provider,
    }

    if llm_api_key:
        config["llm_api_key"] = llm_api_key
    if llm_proxy_url:
        config["llm_proxy_url"] = llm_proxy_url
    if llm_model:
        config["llm_model"] = llm_model
    if fleet_org:
        config["fleet_org"] = fleet_org
    if vessel_repo:
        config["vessel_repo"] = vessel_repo

    return config


def _write_config(config: Dict[str, Any]) -> None:
    """Write the config dict to ~/.git-agent/config.yaml as YAML."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import yaml
        content = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except ImportError:
        # Fallback: manual YAML serialization
        lines = []
        for k, v in config.items():
            if isinstance(v, str) and any(c in v for c in (":", "#", "{", "}", "[", "]", ",")):
                lines.append(f'{k}: "{v}"')
            elif isinstance(v, str):
                lines.append(f"{k}: {v}")
            elif v is None:
                lines.append(f"{k}: null")
            else:
                lines.append(f"{k}: {v}")
        content = "\n".join(lines) + "\n"

    CONFIG_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

def _step_github_token() -> str:
    """Step 1: Ask for GitHub PAT."""
    _cprint("cyan", "\n── Step 1: GitHub Authentication ──")
    _cprint("reset", "A GitHub Personal Access Token is required for the agent to interact")
    _cprint("reset", "with repositories, open PRs, and communicate with the fleet.")
    _cprint("reset", "Generate one at: https://github.com/settings/tokens")
    _cprint("reset", "Required scopes: repo, read:org, read:user")

    while True:
        token = _prompt("GitHub PAT", password=True)
        if not token:
            _cprint("red", "GitHub PAT is required. Please provide a valid token.")
            continue

        _cprint("blue", "Validating token...")
        result = _validate_github_pat(token)
        if result["valid"]:
            _cprint("green", f"  Authenticated as @{result['login']}")
            return token
        else:
            _cprint("red", f"  {result['message']}")
            if not _yes_no("Try again?", default=True):
                _cprint("yellow", "Skipping GitHub validation. Token will be saved but unverified.")
                return token


def _step_llm_provider() -> tuple:
    """Step 2: Ask for LLM provider and credentials.

    Returns a tuple of (provider_name, api_key, proxy_url, model).
    """
    _cprint("cyan", "\n── Step 2: LLM Configuration ──")
    _cprint("reset", "Select the LLM provider for the agent's reasoning engine.")

    providers = {
        "1": "OpenAI (GPT-4, GPT-3.5, etc.)",
        "2": "Anthropic (Claude 3, etc.)",
        "3": "Ollama (Local models)",
        "4": "Custom Proxy (ZeroClaw, Pi agent, etc.)",
    }

    for key, desc in providers.items():
        _cprint("reset", f"  [{key}] {desc}")

    while True:
        choice = _prompt("Provider (1-4)", default="1")
        if choice in providers:
            break
        _cprint("red", f"Invalid choice. Enter 1-4.")

    api_key: Optional[str] = None
    proxy_url: Optional[str] = None
    model: Optional[str] = None

    if choice == "1":
        # OpenAI
        provider = "openai"
        api_key = _prompt("OpenAI API Key", password=True)
        if not api_key:
            _cprint("red", "OpenAI API key is required.")
            api_key = _prompt("OpenAI API Key", password=True)

        _cprint("blue", "Validating API key...")
        result = _validate_openai_key(api_key)
        if result["valid"]:
            _cprint("green", "  API key is valid.")
        else:
            _cprint("yellow", f"  {result['message']}")

        model = _prompt("Model", default="gpt-4")

    elif choice == "2":
        # Anthropic
        provider = "anthropic"
        api_key = _prompt("Anthropic API Key", password=True)
        if not api_key:
            _cprint("red", "Anthropic API key is required.")
            api_key = _prompt("Anthropic API Key", password=True)

        _cprint("blue", "Validating API key format...")
        result = _validate_anthropic_key(api_key)
        if result["valid"]:
            _cprint("green", "  API key format is valid.")
        else:
            _cprint("yellow", f"  {result['message']}")

        model = _prompt("Model", default="claude-3-sonnet-20240229")

    elif choice == "3":
        # Ollama
        provider = "ollama"
        _cprint("blue", "Detecting local Ollama installation...")

        ollama_url = _detect_ollama()
        if ollama_url:
            _cprint("green", f"  Ollama detected at {ollama_url}")
            proxy_url = ollama_url + "/v1"
        else:
            _cprint("yellow", "  Ollama not detected. Make sure it's running:")
            _cprint("reset", "    curl -fsSL https://ollama.com/install.sh | sh")
            _cprint("reset", "    ollama serve")
            proxy_url = _prompt("Ollama URL", default="http://localhost:11434/v1")

        model = _prompt("Model", default="llama3")

    elif choice == "4":
        # Proxy
        provider = "proxy"
        proxy_url = _prompt("Proxy URL", default="http://localhost:8000/v1")
        if proxy_url:
            _cprint("blue", "Validating proxy URL...")
            result = _validate_proxy_url(proxy_url)
            if result["valid"]:
                _cprint("green", f"  {result['message']}")
            else:
                _cprint("yellow", f"  {result['message']}")

        proxy_key = _prompt("Proxy API Key (optional, leave empty if none)", password=True)
        if proxy_key:
            api_key = proxy_key

        model = _prompt("Model", default="")

    return provider, api_key, proxy_url, model


def _step_fleet_config() -> tuple:
    """Step 3: Ask for fleet organization and vessel repo.

    Returns a tuple of (fleet_org, vessel_repo).
    """
    _cprint("cyan", "\n── Step 3: Fleet Configuration ──")
    _cprint("reset", "Configure the fleet organization and your vessel (identity) repository.")

    fleet_org = _prompt("Fleet organization", default=DEFAULT_FLEET_ORG)
    vessel_name = _prompt("Vessel repo name", default=DEFAULT_VESSEL_REPO)
    vessel_repo = f"{fleet_org}/{vessel_name}" if "/" not in vessel_name else vessel_name

    return fleet_org, vessel_repo


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_wizard() -> Dict[str, Any]:
    """Run the interactive configuration wizard.

    Returns the config dict that was saved.
    """
    _cprint("cyan", "============================================================")
    _cprint("cyan", "  git-agent Configuration Wizard")
    _cprint("cyan", "============================================================")
    _cprint("reset", "This wizard will guide you through setting up your git-agent.")
    _cprint("reset", "All configuration is saved to ~/.git-agent/config.yaml")
    _cprint("reset", "You can re-run this wizard at any time.")

    # Check if existing config
    if CONFIG_PATH.exists():
        _cprint("yellow", f"\nExisting configuration found at {CONFIG_PATH}")
        if not _yes_no("Overwrite existing configuration?", default=False):
            _cprint("blue", "Loading existing configuration...")
            try:
                import yaml
                with open(CONFIG_PATH) as f:
                    return yaml.safe_load(f) or {}
            except ImportError:
                _cprint("red", "Cannot read existing config (PyYAML not installed). Starting fresh.")

    # Step 1: GitHub
    github_token = _step_github_token()

    # Step 2: LLM
    llm_provider, llm_api_key, llm_proxy_url, llm_model = _step_llm_provider()

    # Step 3: Fleet
    fleet_org, vessel_repo = _step_fleet_config()

    # Build config
    config = _build_config_dict(
        github_token=github_token,
        llm_provider=llm_provider,
        llm_api_key=llm_api_key,
        llm_proxy_url=llm_proxy_url,
        llm_model=llm_model,
        fleet_org=fleet_org,
        vessel_repo=vessel_repo,
    )

    # Save
    _write_config(config)

    _cprint("green", f"\n  Configuration saved to {CONFIG_PATH}")
    _cprint("green", "============================================================\n")

    return config


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the config wizard CLI."""
    try:
        config = run_wizard()
        _cprint("green", "Configuration complete!")
        _cprint("reset", f"  Config file: {CONFIG_PATH}")
        _cprint("reset", f"  Provider:   {config.get('llm_provider', 'N/A')}")
        _cprint("reset", f"  Fleet org:  {config.get('fleet_org', 'N/A')}")
        _cprint("reset", f"  Vessel:     {config.get('vessel_repo', 'N/A')}")
        _cprint("reset", "")
        _cprint("cyan", "To start the agent:")
        _cprint("reset", "  python -m git_agent")
        sys.exit(0)
    except KeyboardInterrupt:
        _cprint("\nyellow", "\nConfiguration cancelled by user.")
        sys.exit(1)
    except Exception as exc:
        _cprint("red", f"\nConfiguration failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
