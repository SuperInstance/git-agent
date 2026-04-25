#!/usr/bin/env python3
"""
git-agent CLI — unified entry point for the standalone runtime.

Subcommands:
  onboard   Board a vessel repo (reads identity, configures agent)
  chat      Talk to the agent directly (no OpenClaw)
  start     Autonomous work loop
  status    Show current agent state
  scout     PLATO Scout — analyze repos and generate tiles
  scholar   PLATO Scholar — deep code analysis
  librarian PLATO Librarian — tile quality and cross-references
  quality   PLATO Quality — score and grade tiles

Usage:
  git-agent onboard --vessel SuperInstance/oracle1-workspace
  git-agent chat -m "status?"
  git-agent start --once
  git-agent status
  git-agent scout SuperInstance/flux-runtime
  git-agent scholar analyze SuperInstance/plato-kernel
  git-agent librarian stats
  git-agent quality score-all
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

GIT_AGENT_HOME = os.environ.get("GIT_AGENT_HOME", os.path.expanduser("~/.git-agent"))
STANDALONE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standalone")
PLATO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plato")

# Colors
BOLD = "\033[1m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
YELLOW = "\033[0;33m"
RED = "\033[0;31m"
DIM = "\033[2m"
NC = "\033[0m"


def run_python(script_path, args=None):
    """Run a Python script with args, passing through env."""
    cmd = [sys.executable, script_path]
    if args:
        cmd.extend(args)
    result = subprocess.run(cmd, env=os.environ.copy())
    return result.returncode


def cmd_onboard(args):
    """Board a vessel."""
    script = os.path.join(STANDALONE_DIR, "onboard.py")
    if not os.path.exists(script):
        # Fallback: look in git-agent home
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "standalone", "onboard.py")
    
    run_args = []
    if args.vessel:
        run_args.extend(["--vessel", args.vessel])
    if args.token:
        run_args.extend(["--token", args.token])
    if args.status:
        run_args.append("--status")
    
    run_python(script, run_args)


def cmd_chat(args):
    """Direct chat with the agent."""
    script = os.path.join(STANDALONE_DIR, "chat.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "standalone", "chat.py")
    
    run_args = []
    if args.vessel:
        run_args.extend(["--vessel", args.vessel])
    if args.provider:
        run_args.extend(["--provider", args.provider])
    if args.model:
        run_args.extend(["--model", args.model])
    if args.message:
        run_args.extend(["--message", args.message])
    
    run_python(script, run_args)


def cmd_start(args):
    """Start autonomous work loop."""
    script = os.path.join(STANDALONE_DIR, "start.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "standalone", "start.py")
    
    run_args = []
    if args.interval:
        run_args.extend(["--interval", str(args.interval)])
    if args.max_rounds:
        run_args.extend(["--max-rounds", str(args.max_rounds)])
    if args.once:
        run_args.append("--once")
    
    run_python(script, run_args)


def cmd_status(args):
    """Show agent status."""
    script = os.path.join(STANDALONE_DIR, "onboard.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "standalone", "onboard.py")
    run_python(script, ["--status"])


def cmd_scout(args):
    """PLATO Scout — repo analysis."""
    script = os.path.join(PLATO_DIR, "scout.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "plato", "scout.py")
    
    run_args = [args.command]  # scout, scout-org, daemon, stats
    for arg in args.args:
        run_args.append(arg)
    
    run_python(script, run_args)


def cmd_scholar(args):
    """PLATO Scholar — deep analysis."""
    script = os.path.join(PLATO_DIR, "scholar.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "plato", "scholar.py")
    
    run_args = args.args
    run_python(script, run_args)


def cmd_librarian(args):
    """PLATO Librarian — quality control."""
    script = os.path.join(PLATO_DIR, "librarian.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "plato", "librarian.py")
    
    run_args = args.args
    run_python(script, run_args)


def cmd_quality(args):
    """PLATO Quality — tile scoring."""
    script = os.path.join(PLATO_DIR, "quality.py")
    if not os.path.exists(script):
        script = os.path.join(GIT_AGENT_HOME, "git-agent", "plato", "quality.py")
    
    run_args = args.args
    run_python(script, run_args)


def cmd_version(args):
    """Show version."""
    print(f"git-agent v0.1.0")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Home: {GIT_AGENT_HOME}")
    
    config_path = os.path.join(GIT_AGENT_HOME, "config", "agent.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        agent = config.get("agent", {})
        print(f"  Agent: {agent.get('emoji', '🦀')} {agent.get('name', 'unknown')}")
        print(f"  Vessel: {agent.get('vessel', 'none')}")
        print(f"  Onboarded: {config.get('onboarded', '?')}")


def main():
    parser = argparse.ArgumentParser(
        prog="git-agent",
        description="🦀 git-agent — The repo IS the agent. Git IS the nervous system.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  git-agent onboard --vessel SuperInstance/oracle1-workspace
  git-agent chat -m "What's your current task?"
  git-agent start --once
  git-agent scout SuperInstance/flux-runtime
  git-agent scholar analyze SuperInstance/plato-kernel
  git-agent librarian stats
  git-agent quality score-all
        """
    )
    
    sub = parser.add_subparsers(dest="command", help="Available commands")
    
    # onboard
    p = sub.add_parser("onboard", help="Board a vessel repo")
    p.add_argument("--vessel", help="Vessel repo (owner/name)")
    p.add_argument("--token", help="GitHub PAT")
    p.add_argument("--status", action="store_true", help="Show onboarding status")
    p.set_defaults(func=cmd_onboard)
    
    # chat
    p = sub.add_parser("chat", help="Talk to the agent directly")
    p.add_argument("-m", "--message", help="One-shot message (no REPL)")
    p.add_argument("--vessel", help="Override vessel path")
    p.add_argument("--provider", default="deepinfra", help="LLM provider")
    p.add_argument("--model", help="Override model")
    p.set_defaults(func=cmd_chat)
    
    # start
    p = sub.add_parser("start", help="Start autonomous work loop")
    p.add_argument("--interval", type=int, default=300, help="Seconds between cycles")
    p.add_argument("--max-rounds", type=int, default=10, help="Max work cycles")
    p.add_argument("--once", action="store_true", help="Single cycle and exit")
    p.set_defaults(func=cmd_start)
    
    # status
    p = sub.add_parser("status", help="Show current agent state")
    p.set_defaults(func=cmd_status)
    
    # scout
    p = sub.add_parser("scout", help="PLATO Scout — analyze repos")
    p.add_argument("scout_command", nargs="?", default="stats", help="scout|scout-org|daemon|stats")
    p.add_argument("args", nargs="*", help="Command arguments")
    p.set_defaults(func=cmd_scout)
    
    # scholar
    p = sub.add_parser("scholar", help="PLATO Scholar — deep code analysis")
    p.add_argument("args", nargs="*", help="analyze <owner/repo> | batch <owner>")
    p.set_defaults(func=cmd_scholar)
    
    # librarian
    p = sub.add_parser("librarian", help="PLATO Librarian — quality control")
    p.add_argument("args", nargs="*", help="stats|audit|dedup|cross-reference")
    p.set_defaults(func=cmd_librarian)
    
    # quality
    p = sub.add_parser("quality", help="PLATO Quality — tile scoring")
    p.add_argument("args", nargs="*", help="score|score-all|report|promote|archive")
    p.set_defaults(func=cmd_quality)
    
    # version
    p = sub.add_parser("version", help="Show version info")
    p.set_defaults(func=cmd_version)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return
    
    args.func(args)


if __name__ == "__main__":
    main()
