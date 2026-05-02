#!/usr/bin/env python3
"""
git-agent onboard — Vessel onboarding system.

When an agent boards a vessel repo, this reads:
  IDENTITY.md → who am I
  SOUL.md → personality and tone
  AGENTS.md → standing orders and rules
  TODO.md → what to do
  NEXT-ACTION.md → what to do RIGHT NOW
  TOOLS.md → available tools
  memory/ → continuity files

Then generates:
  config/agent.yaml → runtime config
  config/services.json → fleet service URLs
  config/context.json → loaded identity context

Usage:
  python3 onboard.py --vessel SuperInstance/oracle1-workspace
  python3 onboard.py --vessel SuperInstance/oracle1-workspace --token ghp_xxx
  python3 onboard.py --status  # Show current onboarding state
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional

# Config paths
GIT_AGENT_HOME = os.environ.get("GIT_AGENT_HOME", os.path.expanduser("~/.git-agent"))
CONFIG_DIR = os.path.join(GIT_AGENT_HOME, "config")
VESSELS_DIR = os.path.join(GIT_AGENT_HOME, "vessels")

# Fleet services (defaults, overridden by fleet.yaml)
FLEET_SERVICES = {
    "plato": "http://localhost:8847",
    "keeper": "http://localhost:8900",
    "agent_api": "http://localhost:8901",
    "arena": "http://localhost:4044",
    "crab_trap": "http://localhost:4042",
    "the_lock": "http://localhost:4043",
    "grammar": "http://localhost:4045",
    "matrix": "http://localhost:6167",
    "mud": "http://localhost:7777",
    "purple_pincher": "http://localhost:4048",
}

# Vessel identity files to read (in order)
IDENTITY_FILES = [
    "IDENTITY.md",
    "SOUL.md",
    "AGENTS.md",
    "USER.md",
    "TODO.md",
    "NEXT-ACTION.md",
    "TOOLS.md",
    "HEARTBEAT.md",
]


def log(msg, level="info"):
    icons = {"info": "ℹ", "ok": "✓", "warn": "⚠", "error": "✗", "bold": "▸"}
    print(f"  {icons.get(level, '•')} {msg}")


def read_file_safe(path):
    """Read file, return content or None."""
    try:
        with open(path, "r") as f:
            return f.read()
    except (FileNotFoundError, PermissionError):
        return None


def parse_identity(content):
    """Extract key fields from IDENTITY.md."""
    if not content:
        return {}
    fields = {}
    for line in content.split("\n"):
        # Match "- **Key:** Value" pattern
        m = re.match(r"-\s*\*\*(.+?)\*:\s*(.+)", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            fields[key] = m.group(2).strip()
    return fields


def parse_soul(content):
    """Extract key directives from SOUL.md."""
    if not content:
        return {}
    directives = {
        "has_personality": "opinion" in content.lower() or "vibe" in content.lower(),
        "has_boundaries": "bound" in content.lower() or "red line" in content.lower(),
        "continuity_aware": "continuity" in content.lower() or "wake up fresh" in content.lower(),
    }
    return directives


def parse_agents_orders(content):
    """Extract standing orders from AGENTS.md."""
    if not content:
        return {"orders": [], "red_lines": []}
    orders = []
    red_lines = []
    in_red_lines = False
    
    for line in content.split("\n"):
        if "Red Line" in line:
            in_red_lines = True
            continue
        if line.startswith("## ") and in_red_lines:
            in_red_lines = False
        
        m = re.match(r"-\s*(.+)", line.strip())
        if m:
            text = m.group(1).strip()
            if in_red_lines:
                red_lines.append(text)
            elif len(text) > 10:
                orders.append(text)
    
    return {"orders": orders, "red_lines": red_lines}


def clone_vessel(vessel_spec, token=None):
    """Clone or update a vessel repo."""
    owner, name = vessel_spec.split("/")
    vessel_dir = os.path.join(VESSELS_DIR, name)
    
    if os.path.isdir(vessel_dir):
        log(f"Updating existing vessel at {vessel_dir}")
        os.system(f"cd {vessel_dir} && git pull -q 2>/dev/null")
        return vessel_dir
    
    os.makedirs(VESSELS_DIR, exist_ok=True)
    
    if token:
        url = f"https://{token}@github.com/{vessel_spec}.git"
    else:
        url = f"https://github.com/{vessel_spec}.git"
    
    log(f"Cloning vessel {vessel_spec}...")
    ret = os.system(f"git clone -q {url} {vessel_dir} 2>/dev/null")
    if ret != 0:
        log(f"Clone failed, trying without token...", "warn")
        ret = os.system(f"git clone -q https://github.com/{vessel_spec}.git {vessel_dir} 2>/dev/null")
        if ret != 0:
            log(f"Could not clone vessel — working offline", "warn")
            os.makedirs(vessel_dir, exist_ok=True)
    
    return vessel_dir


def load_vessel_context(vessel_dir):
    """Read all identity files from the vessel."""
    context = {
        "files_loaded": [],
        "identity": {},
        "soul": {},
        "orders": {},
        "todo": None,
        "next_action": None,
        "tools": None,
        "heartbeat": None,
        "raw": {},
    }
    
    for filename in IDENTITY_FILES:
        path = os.path.join(vessel_dir, filename)
        content = read_file_safe(path)
        if content:
            context["files_loaded"].append(filename)
            context["raw"][filename] = content[:2000]  # Truncate for config
            
            if filename == "IDENTITY.md":
                context["identity"] = parse_identity(content)
            elif filename == "SOUL.md":
                context["soul"] = parse_soul(content)
            elif filename == "AGENTS.md":
                context["orders"] = parse_agents_orders(content)
            elif filename == "TODO.md":
                context["todo"] = content[:1000]
            elif filename == "NEXT-ACTION.md":
                context["next_action"] = content[:500]
            elif filename == "TOOLS.md":
                context["tools"] = content[:1000]
            elif filename == "HEARTBEAT.md":
                context["heartbeat"] = content[:500]
    
    # Check for memory/ directory
    memory_dir = os.path.join(vessel_dir, "memory")
    if os.path.isdir(memory_dir):
        mem_files = os.listdir(memory_dir)
        context["memory_files"] = sorted(mem_files)[-5:]  # Last 5
        log(f"Found {len(mem_files)} memory files")
    
    return context


def detect_fleet_services():
    """Auto-detect running fleet services."""
    active = {}
    for name, url in FLEET_SERVICES.items():
        try:
            req = urllib.request.Request(f"{url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    active[name] = {"url": url, "status": "up"}
                    continue
        except:
            pass
        # Try root endpoint
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    active[name] = {"url": url, "status": "up"}
        except:
            active[name] = {"url": url, "status": "down"}
    
    return active


def generate_config(vessel_spec, vessel_dir, context, token=None):
    """Generate the runtime config."""
    owner, name = vessel_spec.split("/")
    agent_name = name.replace("-workspace", "").replace("-vessel", "")
    identity = context.get("identity", {})
    
    config = {
        "agent": {
            "name": identity.get("name", agent_name),
            "creature": identity.get("creature", "git-agent"),
            "emoji": identity.get("emoji", "🦀"),
            "vessel": vessel_spec,
            "vessel_path": vessel_dir,
            "timezone": "UTC",
        },
        "github": {
            "token": token or "${GITHUB_TOKEN}",
            "owner": owner,
        },
        "llm": {
            "provider": "deepinfra",
            "model": "ByteDance/Seed-2.0-mini",
            "api_key": "${DEEPINFRA_API_KEY}",
            "temperature": 0.7,
            "max_tokens": 4096,
        },
        "plato": {
            "url": FLEET_SERVICES["plato"],
            "auto_tile": True,
            "rooms": [],
        },
        "fleet": {
            "org": owner,
            "services": {},
        },
        "onboarded": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "files_loaded": context["files_loaded"],
    }
    
    # Add identity details
    if "vibe" in identity:
        config["agent"]["vibe"] = identity["vibe"]
    
    return config


def save_config(config):
    """Save config files."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    
    # Main config
    config_path = os.path.join(CONFIG_DIR, "agent.yaml")
    # Write as JSON (simpler, no yaml dependency)
    json_path = os.path.join(CONFIG_DIR, "agent.json")
    with open(json_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    log(f"Config saved to {json_path}")
    
    # Services
    services_path = os.path.join(CONFIG_DIR, "services.json")
    services = detect_fleet_services()
    with open(services_path, "w") as f:
        json.dump(services, f, indent=2)
    up = sum(1 for s in services.values() if s["status"] == "up")
    log(f"Fleet services: {up}/{len(services)} up")
    
    # Context (loaded identity files)
    context_path = os.path.join(CONFIG_DIR, "context.json")
    # Don't include raw content in context — just metadata
    ctx_meta = {k: v for k, v in config.items() if k != "raw"}
    with open(context_path, "w") as f:
        json.dump(ctx_meta, f, indent=2)
    
    return json_path


def show_status():
    """Show current onboarding status."""
    config_path = os.path.join(CONFIG_DIR, "agent.json")
    
    if not os.path.exists(config_path):
        print("git-agent not onboarded. Run: git-agent onboard --vessel owner/repo")
        return
    
    config = json.loads(read_file_safe(config_path) or "{}")
    agent = config.get("agent", {})
    
    print(f"\n🦀 git-agent status")
    print(f"  Name:     {agent.get('name', 'unknown')}")
    print(f"  Emoji:    {agent.get('emoji', '🦀')}")
    print(f"  Vessel:   {agent.get('vessel', 'none')}")
    print(f"  Onboarded: {config.get('onboarded', 'unknown')}")
    print(f"  Files:    {', '.join(config.get('files_loaded', []))}")
    
    # Check services
    services_path = os.path.join(CONFIG_DIR, "services.json")
    if os.path.exists(services_path):
        services = json.loads(read_file_safe(services_path) or "{}")
        print(f"\n  Fleet services:")
        for name, info in services.items():
            icon = "✓" if info["status"] == "up" else "✗"
            print(f"    {icon} {name}: {info['url']}")
    
    # Check vessel
    vessel_dir = agent.get("vessel_path", "")
    if vessel_dir and os.path.isdir(vessel_dir):
        print(f"\n  Vessel path: {vessel_dir}")
        dirty = os.popen(f"cd {vessel_dir} && git status --short 2>/dev/null").read().strip()
        if dirty:
            print(f"    Uncommitted changes: {len(dirty.split(chr(10)))} files")
        else:
            print(f"    Working tree clean")
        
        # Show TODO status
        todo = read_file_safe(os.path.join(vessel_dir, "TODO.md"))
        if todo:
            unchecked = len(re.findall(r"- \[ \]", todo))
            checked = len(re.findall(r"- \[x\]", todo))
            print(f"    TODO: {checked}/{checked + unchecked} done")
        
        next_action = read_file_safe(os.path.join(vessel_dir, "NEXT-ACTION.md"))
        if next_action:
            # Extract active task
            for line in next_action.split("\n"):
                if line.startswith("**") and "Active" in line:
                    continue
                if line.startswith("**") and ":" in line:
                    m = re.match(r"\*\*(.+?)\*\*\s*(.+)", line)
                    if m:
                        print(f"    Active task: {m.group(2)[:80]}")
                        break


def onboard(vessel_spec, token=None):
    """Full onboarding flow."""
    print(f"\n🦀 Boarding vessel: {vessel_spec}")
    print(f"{'='*50}")
    
    # 1. Clone vessel
    vessel_dir = clone_vessel(vessel_spec, token)
    log(f"Vessel at {vessel_dir}")
    
    # 2. Load identity
    context = load_vessel_context(vessel_dir)
    
    loaded = context["files_loaded"]
    if not loaded:
        log("No identity files found — empty vessel", "warn")
    else:
        log(f"Loaded: {', '.join(loaded)}")
    
    # 3. Show identity summary
    identity = context.get("identity", {})
    if identity:
        print(f"\n  Agent identity:")
        for k, v in identity.items():
            print(f"    {k}: {v}")
    
    # 4. Show soul status
    soul = context.get("soul", {})
    if soul:
        features = [k.replace("has_", "").replace("_", " ") for k, v in soul.items() if v]
        if features:
            log(f"Soul features: {', '.join(features)}")
    
    # 5. Show standing orders
    orders = context.get("orders", {})
    if orders.get("red_lines"):
        log(f"Red lines: {len(orders['red_lines'])} defined")
        for rl in orders["red_lines"][:3]:
            print(f"    🔴 {rl[:60]}")
    
    # 6. Show current task
    if context.get("next_action"):
        for line in context["next_action"].split("\n"):
            if line.strip() and not line.startswith("#") and not line.startswith("**"):
                log(f"Current task: {line.strip()[:80]}")
                break
    
    # 7. Generate and save config
    config = generate_config(vessel_spec, vessel_dir, context, token)
    config_path = save_config(config)
    
    # 8. Register with fleet services
    agent_name = config["agent"]["name"]
    
    # Try PLATO registration
    try:
        plato_url = FLEET_SERVICES["plato"]
        workspace_data = {
            "agent": agent_name,
            "role": config["agent"].get("creature", "git-agent"),
            "status": "onboarded",
            "active_task": context.get("next_action", "Awaiting orders")[:100],
            "vessel": vessel_spec,
        }
        req = urllib.request.Request(
            f"{plato_url}/workspace/{agent_name}",
            method="POST",
            data=json.dumps(workspace_data).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                log("Registered with PLATO")
    except Exception as e:
        log(f"PLATO registration skipped: {e}", "warn")
    
    # Try Keeper registration
    try:
        keeper_url = FLEET_SERVICES["keeper"]
        reg_data = {
            "agent": agent_name,
            "vessel": vessel_spec,
            "services": list(FLEET_SERVICES.keys()),
        }
        req = urllib.request.Request(
            f"{keeper_url}/register",
            method="POST",
            data=json.dumps(reg_data).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                log("Registered with Keeper")
    except Exception:
        log("Keeper registration skipped", "warn")
    
    # Done
    print(f"\n{'='*50}")
    log(f"Agent '{agent_name}' successfully boarded {vessel_spec}", "ok")
    log(f"Config: {config_path}")
    print(f"\n  Ready to work. Start with:")
    print(f"    git-agent start")
    print(f"    git-agent chat")
    print(f"    git-agent status")
    print()


def main():
    parser = argparse.ArgumentParser(description="git-agent onboard — Board a vessel and become someone")
    parser.add_argument("--vessel", help="Vessel repo (owner/name) to board")
    parser.add_argument("--token", help="GitHub personal access token")
    parser.add_argument("--status", action="store_true", help="Show current onboarding status")
    parser.add_argument("--reboard", action="store_true", help="Force re-onboarding")
    
    args = parser.parse_args()
    
    if args.status:
        show_status()
    elif args.vessel:
        token = args.token or os.environ.get("GITHUB_TOKEN", "")
        onboard(args.vessel, token or None)
    else:
        # Check if already onboarded
        config_path = os.path.join(CONFIG_DIR, "agent.json")
        if os.path.exists(config_path):
            print("Already onboarded. Showing status:")
            show_status()
            print("\nRe-onboard with: git-agent onboard --vessel owner/repo --reboard")
        else:
            print("No vessel boarded. Run: git-agent onboard --vessel owner/repo")
            print("\nExample:")
            print("  git-agent onboard --vessel SuperInstance/oracle1-workspace")
            print("  git-agent onboard --vessel Lucineer/JetsonClaw1-vessel")


if __name__ == "__main__":
    main()
