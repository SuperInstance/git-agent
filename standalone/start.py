#!/usr/bin/env python3
"""
git-agent start — Start the autonomous work loop.

The agent reads NEXT-ACTION.md, does the task, updates TODO.md, commits.
Runs continuously like a greenhorn on a boat — always working.

Usage:
  git-agent start [--interval 300] [--max-rounds 10]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

GIT_AGENT_HOME = os.environ.get("GIT_AGENT_HOME", os.path.expanduser("~/.git-agent"))
CONFIG_DIR = os.path.join(GIT_AGENT_HOME, "config")

DEEPINFRA_API_KEY = os.environ.get("DEEPINFRA_API_KEY", "RhZPtvuy4cXzu02LbBSffbXeqs5Yf2IZ")
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"


def load_config():
    config_path = os.path.join(CONFIG_DIR, "agent.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            return json.load(f)
    return {}


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def call_llm(system_prompt, user_message, temperature=0.5):
    """Call Seed-2.0-mini for task execution."""
    payload = json.dumps({
        "model": "ByteDance/Seed-2.0-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": 3000,
    }).encode()
    
    req = urllib.request.Request(DEEPINFRA_URL, method="POST", data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {DEEPINFRA_API_KEY}")
    req.add_header("User-Agent", "git-agent/1.0")
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode())
        return body["choices"][0]["message"]["content"]


def git_commit(vessel_path, message):
    """Commit and push changes."""
    os.system(f"cd {vessel_path} && git add -A && git commit -m '{message}' && git push 2>/dev/null")


def extract_active_task(next_action_content):
    """Extract the active task from NEXT-ACTION.md."""
    if not next_action_content:
        return None
    lines = next_action_content.split("\n")
    in_active = False
    for line in lines:
        if "Active Task" in line or "active_task" in line.lower():
            in_active = True
            continue
        if in_active and line.strip() and not line.startswith("#") and not line.startswith("**"):
            return line.strip()
        if in_active and line.startswith("##"):
            break
    return None


def run_work_cycle(config, round_num):
    """One work cycle: read task → execute → update files."""
    agent = config.get("agent", {})
    name = agent.get("name", "agent")
    emoji = agent.get("emoji", "🦀")
    vessel_path = agent.get("vessel_path", "")
    
    if not vessel_path or not os.path.isdir(vessel_path):
        print(f"  [{round_num}] No vessel path — skipping")
        return False
    
    # Pull latest
    os.system(f"cd {vessel_path} && git pull -q 2>/dev/null")
    
    # Read current state
    next_action = read_file(os.path.join(vessel_path, "NEXT-ACTION.md"))
    todo = read_file(os.path.join(vessel_path, "TODO.md"))
    tools = read_file(os.path.join(vessel_path, "TOOLS.md"))
    
    active_task = extract_active_task(next_action)
    if not active_task:
        print(f"  [{round_num}] No active task found — waiting")
        return False
    
    print(f"  [{round_num}] {emoji} {name}: {active_task[:80]}")
    
    # Build context for LLM
    system_prompt = f"""You are {name}, a git-agent running an autonomous work cycle.
You read your task from NEXT-ACTION.md and execute it.
Output format:
1. A summary of what you did (2-3 sentences)
2. Files to update (JSON array): [{{"path": "file.md", "content": "..."}}]
3. Next task suggestion

Current TODO state (first 50 lines):
{todo[:2000] if todo else 'No TODO.md'}

Available tools:
{tools[:1000] if tools else 'None specified'}

Execute the task. Be concrete — reference actual files and actions."""

    user_message = f"Active task: {active_task}\n\nExecute this task now."
    
    try:
        response = call_llm(system_prompt, user_message)
        print(f"  [{round_num}] Response: {response[:150]}...")
        
        # Try to extract file updates
        file_pattern = r'"path":\s*"([^"]+)"[^}]*"content":\s*"([^"]*)"'
        matches = re.findall(file_pattern, response)
        
        if matches:
            for filepath, content in matches:
                full_path = os.path.join(vessel_path, filepath)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                write_file(full_path, content.replace("\\n", "\n"))
                print(f"  [{round_num}] Updated: {filepath}")
            
            git_commit(vessel_path, f"work cycle {round_num}: {active_task[:50]}")
            print(f"  [{round_num}] Committed and pushed")
        else:
            print(f"  [{round_num}] No file updates extracted")
        
        return True
        
    except Exception as e:
        print(f"  [{round_num}] Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="git-agent start — Autonomous work loop")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between cycles")
    parser.add_argument("--max-rounds", type=int, default=10, help="Max cycles before stopping")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    
    args = parser.parse_args()
    config = load_config()
    agent = config.get("agent", {})
    
    if not agent:
        print("Not onboarded. Run: git-agent onboard --vessel owner/repo")
        sys.exit(1)
    
    name = agent.get("name", "agent")
    emoji = agent.get("emoji", "🦀")
    
    print(f"\n{emoji} {name} — Starting autonomous work loop")
    print(f"  Interval: {args.interval}s")
    print(f"  Max rounds: {args.max_rounds}")
    print(f"  Vessel: {agent.get('vessel', 'none')}")
    print()
    
    rounds_done = 0
    
    for i in range(1, args.max_rounds + 1):
        timestamp = datetime.utcnow().strftime("%H:%M:%S")
        print(f"\n[{timestamp}] Cycle {i}/{args.max_rounds}")
        
        did_work = run_work_cycle(config, i)
        rounds_done += 1
        
        if args.once:
            break
        
        if i < args.max_rounds:
            print(f"  Sleeping {args.interval}s...")
            time.sleep(args.interval)
    
    print(f"\n{emoji} Work loop complete. {rounds_done} cycles run.")


if __name__ == "__main__":
    main()
