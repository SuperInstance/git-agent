#!/usr/bin/env python3
"""
git-agent chat — Direct conversation with a git-agent.

Reads the vessel context, connects to the LLM, and starts a REPL.
No OpenClaw needed — the agent reads its own shell.

Usage:
  git-agent chat
  git-agent chat --vessel SuperInstance/oracle1-workspace
  git-agent chat --model glm-4.7-flash
  git-agent chat --message "What's the status?"
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

GIT_AGENT_HOME = os.environ.get("GIT_AGENT_HOME", os.path.expanduser("~/.git-agent"))
CONFIG_DIR = os.path.join(GIT_AGENT_HOME, "config")

# LLM endpoints (OpenAI-compatible)
LLM_PROVIDERS = {
    "deepinfra": {
        "url": "https://api.deepinfra.com/v1/openai/chat/completions",
        "key_env": "DEEPINFRA_API_KEY",
        "default_model": "ByteDance/Seed-2.0-mini",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key_env": "GROQ_API_KEY",
        "default_model": "llama-3.3-70b-versatile",
    },
    "siliconflow": {
        "url": "https://api.siliconflow.com/v1/chat/completions",
        "key_env": "SILICONFLOW_API_KEY",
        "default_model": "deepseek-ai/DeepSeek-V3",
    },
}


def load_config():
    """Load agent config."""
    config_path = os.path.join(CONFIG_DIR, "agent.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def load_vessel_context(vessel_path):
    """Load all context files from the vessel."""
    files = ["IDENTITY.md", "SOUL.md", "AGENTS.md", "USER.md", "TODO.md",
             "NEXT-ACTION.md", "TOOLS.md"]
    context = ""
    for filename in files:
        path = os.path.join(vessel_path, filename)
        if os.path.exists(path):
            with open(path) as f:
                content = f.read()
                context += f"\n### {filename}\n{content[:3000]}\n"
    
    # Load recent memory
    memory_dir = os.path.join(vessel_path, "memory")
    if os.path.isdir(memory_dir):
        mem_files = sorted(os.listdir(memory_dir))
        for mf in mem_files[-2:]:  # Last 2 memory files
            mp = os.path.join(memory_dir, mf)
            with open(mp) as f:
                context += f"\n### memory/{mf}\n{f.read()[:2000]}\n"
    
    return context


def call_llm(messages, provider="deepinfra", model=None, temperature=0.7):
    """Call LLM via OpenAI-compatible API."""
    prov = LLM_PROVIDERS.get(provider, LLM_PROVIDERS["deepinfra"])
    api_key = os.environ.get(prov["key_env"], "")
    model = model or prov["default_model"]
    
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2000,
    }).encode()
    
    req = urllib.request.Request(prov["url"], method="POST", data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("User-Agent", "git-agent/1.0")
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
            return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()[:200]
        return f"[LLM error {e.code}: {error_body}]"
    except Exception as e:
        return f"[Error: {e}]"


def build_system_prompt(config, vessel_context):
    """Build the system prompt from vessel identity."""
    agent = config.get("agent", {})
    name = agent.get("name", "agent")
    creature = agent.get("creature", "git-agent")
    emoji = agent.get("emoji", "🦀")
    
    return f"""You are {name}, a {creature}. You run as a git-agent.

{vessel_context}

You are now in direct chat mode. Your human (Casey) is talking to you directly
through the git-agent CLI — no OpenClaw middleman.

Rules:
- Read your identity files above. They define who you are.
- Be direct and helpful. Skip filler.
- Reference your TODO.md and NEXT-ACTION.md when asked about tasks.
- When you make changes, commit them to the vessel repo.
- Your vessel repo is your home. Keep it clean and up to date.
- If you don't know something, say so. Then figure it out.
"""


def start_chat(config, vessel_context, provider, model, one_shot=None):
    """Start a chat session."""
    agent = config.get("agent", {})
    name = agent.get("name", "agent")
    emoji = agent.get("emoji", "🦀")
    
    system_prompt = build_system_prompt(config, vessel_context)
    messages = [{"role": "system", "content": system_prompt}]
    
    if one_shot:
        messages.append({"role": "user", "content": one_shot})
        response = call_llm(messages, provider, model)
        print(f"\n{emoji} {name}: {response}\n")
        return
    
    print(f"\n{emoji} {name} — git-agent chat")
    print(f"  Provider: {provider}")
    print(f"  Model: {model}")
    print(f"  Type 'quit' to exit, 'status' for vessel status\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye.")
            break
        
        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "bye"):
            print(f"\n{emoji} Later.")
            break
        
        if user_input.lower() == "status":
            vessel_path = config.get("agent", {}).get("vessel_path", "")
            if vessel_path:
                os.system(f"cd {vessel_path} && git status --short 2>/dev/null")
            continue
        
        messages.append({"role": "user", "content": user_input})
        
        # Keep context manageable
        if len(messages) > 20:
            messages = [messages[0]] + messages[-19:]
        
        print(f"\n{emoji} ", end="", flush=True)
        response = call_llm(messages, provider, model)
        print(f"{response}\n")
        
        messages.append({"role": "assistant", "content": response})


def main():
    parser = argparse.ArgumentParser(description="git-agent chat — Talk directly to your agent")
    parser.add_argument("--vessel", help="Override vessel path")
    parser.add_argument("--provider", default="deepinfra", choices=list(LLM_PROVIDERS.keys()))
    parser.add_argument("--model", help="Override model name")
    parser.add_argument("--message", "-m", help="One-shot message (no REPL)")
    parser.add_argument("--temperature", type=float, default=0.7)
    
    args = parser.parse_args()
    
    config = load_config()
    vessel_path = args.vessel or config.get("agent", {}).get("vessel_path", "")
    
    if not vessel_path or not os.path.isdir(vessel_path):
        print("No vessel boarded. Run: git-agent onboard --vessel owner/repo")
        sys.exit(1)
    
    vessel_context = load_vessel_context(vessel_path)
    start_chat(config, vessel_context, args.provider, args.model, args.message)


if __name__ == "__main__":
    main()
