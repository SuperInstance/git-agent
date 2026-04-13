"""
Git Agent CLI — Command-line interface for the co-captain liaison.

Provides subcommands for narrating commit histories, managing workshops,
running bootcamps, generating fleet reports, and spawning agents.

Usage:
    python -m git_agent serve                    # Start co-captain mode
    python -m git_agent narrate <agent>           # Narrate commit history
    python -m git_agent timeline <agent>          # Show visual timeline
    python -m git_agent workshop create <name>    # Create a workshop
    python -m git_agent workshop status           # List all workshops
    python -m git_agent bootcamp status           # Show bootcamp progress
    python -m git_agent bootcamp enroll <agent>   # Enroll agent in bootcamp
    python -m git_agent fleet-report              # Generate daily report
    python -m git_agent rewind <agent> <commit>   # Show state at commit
    python -m git_agent lessons <agent>           # Extract lessons learned
    python -m git_agent spawn <agent> <path>      # Create git-agent for workshop
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from git_agent import GitAgent
from narrator import NarrativeStyle


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _resolve_fleet_root(args: argparse.Namespace) -> str:
    """Resolve the fleet root directory from CLI arguments or defaults."""
    return getattr(args, "fleet_root", ".")


def _load_agent(args: argparse.Namespace) -> GitAgent:
    """Load or create a GitAgent instance."""
    fleet_root = _resolve_fleet_root(args)
    return GitAgent(fleet_root=fleet_root)


def _print_section(title: str) -> None:
    """Print a formatted section header."""
    width = 60
    print()
    print("─" * width)
    print(f"  {title}")
    print("─" * width)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_serve(args: argparse.Namespace) -> int:
    """Start the git agent server in co-captain mode.

    In co-captain mode, the agent listens for fleet events and provides
    a human-readable status dashboard.
    """
    agent = _load_agent(args)
    print("🚀 Git Agent — Co-Captain Mode")
    print("═" * 60)
    print()

    # Show current fleet status
    print(agent.fleet_status())
    print()

    # Show daily report summary
    report = agent.daily_report()
    print(agent.format_daily_report(report))
    print()

    if args.watch:
        print("Watching for changes... (Ctrl+C to stop)")
        print("Note: Interactive watch mode requires a running fleet.")
        try:
            while True:
                pass
        except KeyboardInterrupt:
            print("\nCo-captain mode ended.")

    return 0


def cmd_narrate(args: argparse.Namespace) -> int:
    """Narrate an agent's commit history."""
    agent = _load_agent(args)

    style_map = {
        "brief": NarrativeStyle.BRIEF,
        "detailed": NarrativeStyle.DETAILED,
        "technical": NarrativeStyle.TECHNICAL,
        "story": NarrativeStyle.STORY,
    }
    style = style_map.get(args.style, NarrativeStyle.STORY)

    _print_section(f"Narrative for {args.agent}")

    narrative = agent.narrate_history(
        agent_id=args.agent,
        since=args.since,
        style=style,
    )
    print(narrative)
    return 0


def cmd_timeline(args: argparse.Namespace) -> int:
    """Show a visual timeline of an agent's commits."""
    agent = _load_agent(args)

    workshop = agent._workshops.get(args.agent)
    if not workshop:
        print(f"Error: Agent {args.agent!r} is not registered.")
        return 1

    git_log = agent._run_git_log(workshop.repo_path, args.since)
    commits = agent.narrator.parse_log(git_log)

    if not commits:
        print(f"No commits found for {args.agent!r}")
        return 1

    _print_section(f"Timeline for {args.agent}")
    print(agent.narrator.generate_timeline(commits))
    return 0


def cmd_workshop_create(args: argparse.Namespace) -> int:
    """Create a new workshop."""
    agent = _load_agent(args)

    fleet_root = _resolve_fleet_root(args)
    workshop_path = str(Path(fleet_root) / f"{args.name}-workshop")

    config = {}
    if args.role:
        config["role"] = args.role
    if args.stack:
        config["language_stack"] = args.stack

    ws_config = agent.spawn_git_agent(args.name, workshop_path, config)

    _print_section("Workshop Created")
    print(f"  Agent:    {ws_config.agent_name}")
    print(f"  Role:     {ws_config.agent_role}")
    print(f"  Stack:    {ws_config.language_stack.value}")
    print(f"  Path:     {ws_config.path}")
    print(f"  Status:   Active")
    print()
    print("✅ Workshop scaffolded and registered with the fleet.")
    return 0


def cmd_workshop_status(args: argparse.Namespace) -> int:
    """Show all registered workshops."""
    agent = _load_agent(args)
    print(agent.fleet_status())
    return 0


def cmd_bootcamp_status(args: argparse.Namespace) -> int:
    """Show bootcamp progress for all enrolled agents."""
    agent = _load_agent(args)

    _print_section("Bootcamp Status")
    progress_list = agent.bootcamp.get_all_progress()

    if not progress_list:
        print("  No agents enrolled in bootcamp.")
        print("  Use 'bootcamp enroll <agent>' to get started.")
        return 0

    for progress in progress_list:
        print(f"  🎓 {progress.agent_name}")
        print(f"     Rank: {progress.rank.label}  |  XP: {progress.xp}")
        print(f"     Completed: {len(progress.exercises_completed)} exercises")
        print(f"     Failed: {len(progress.exercises_failed)} exercises")

        xp_needed = agent.bootcamp.xp_to_next_rank(progress.agent_name)
        if xp_needed is not None:
            print(f"     Next rank: {xp_needed} XP needed")
        else:
            print(f"     🏆 Rank: MASTER (maximum)")
        print()

    return 0


def cmd_bootcamp_enroll(args: argparse.Namespace) -> int:
    """Enroll an agent in the bootcamp."""
    agent = _load_agent(args)

    progress = agent.bootcamp.enroll(args.agent)

    _print_section("Bootcamp Enrollment")
    print(f"  Agent:    {args.agent}")
    print(f"  Rank:     {progress.rank.label}")
    print(f"  XP:       {progress.xp}")
    print()
    print("✅ Agent enrolled. Available exercises:")

    available = agent.bootcamp.get_available_exercises(args.agent)
    for ex in available:
        print(f"    • {ex.name:<25} [{ex.exercise_type.value}] (XP: {ex.xp_reward})")

    return 0


def cmd_fleet_report(args: argparse.Namespace) -> int:
    """Generate and display the daily fleet activity report."""
    agent = _load_agent(args)

    report = agent.daily_report()
    print(agent.format_daily_report(report))
    return 0


def cmd_rewind(args: argparse.Namespace) -> int:
    """Show state at a specific commit (without actually rolling back)."""
    agent = _load_agent(args)

    workshop = agent._workshops.get(args.agent)
    if not workshop:
        print(f"Error: Agent {args.agent!r} is not registered.")
        return 1

    # Show the commit and surrounding context
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--stat", args.commit],
            cwd=workshop.repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            _print_section(f"State at {args.commit}")
            print(result.stdout)
        else:
            print(f"Error: {result.stderr}")
            return 1
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"Error: {exc}")
        return 1

    return 0


def cmd_lessons(args: argparse.Namespace) -> int:
    """Extract lessons learned from an agent's commit history."""
    agent = _load_agent(args)

    workshop = agent._workshops.get(args.agent)
    if not workshop:
        print(f"Error: Agent {args.agent!r} is not registered.")
        return 1

    git_log = agent._run_git_log(workshop.repo_path, args.since)
    commits = agent.narrator.parse_log(git_log)

    if not commits:
        print(f"No commits found for {args.agent!r}")
        return 1

    lessons = agent.narrator.extract_lessons(commits)

    _print_section(f"Lessons Learned — {args.agent}")

    if not lessons:
        print("  No clear lessons extracted from the commit history.")
        print("  Lessons emerge from experiment → failure → success patterns.")
        return 0

    for idx, lesson in enumerate(lessons, 1):
        print(f"  {idx}. {lesson}")
        print()

    return 0


def cmd_spawn(args: argparse.Namespace) -> int:
    """Create a git-agent for a workshop."""
    agent = _load_agent(args)

    config = {}
    if args.role:
        config["role"] = args.role
    if args.stack:
        config["language_stack"] = args.stack

    ws_config = agent.spawn_git_agent(args.agent, args.workshop, config)

    _print_section("Git Agent Spawned")
    print(f"  Agent:   {ws_config.agent_name}")
    print(f"  Role:    {ws_config.agent_role}")
    print(f"  Stack:   {ws_config.language_stack.value}")
    print(f"  Path:    {ws_config.path}")
    print()
    print("✅ New git-agent instance ready for the workshop.")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="git-agent",
        description="Git Agent — Co-captain liaison for the SuperInstance fleet",
    )
    parser.add_argument(
        "--fleet-root",
        default=".",
        help="Root directory for fleet data (default: current directory)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_p = subparsers.add_parser("serve", help="Start co-captain mode")
    serve_p.add_argument("--watch", action="store_true", help="Watch for changes")

    # narrate
    narrate_p = subparsers.add_parser("narrate", help="Narrate commit history")
    narrate_p.add_argument("agent", help="Agent ID to narrate")
    narrate_p.add_argument("--since", default=None, help="Git date reference")
    narrate_p.add_argument(
        "--style",
        choices=["brief", "detailed", "technical", "story"],
        default="story",
        help="Narrative style (default: story)",
    )

    # timeline
    timeline_p = subparsers.add_parser("timeline", help="Show visual timeline")
    timeline_p.add_argument("agent", help="Agent ID")
    timeline_p.add_argument("--since", default=None, help="Git date reference")

    # workshop
    workshop_p = subparsers.add_parser("workshop", help="Workshop management")
    workshop_sub = workshop_p.add_subparsers(dest="workshop_cmd")

    ws_create = workshop_sub.add_parser("create", help="Create a new workshop")
    ws_create.add_argument("name", help="Workshop/agent name")
    ws_create.add_argument("--role", default=None, help="Agent role description")
    ws_create.add_argument("--stack", default="full", help="Language stack")

    workshop_sub.add_parser("status", help="List all workshops")

    # bootcamp
    bootcamp_p = subparsers.add_parser("bootcamp", help="Bootcamp management")
    bootcamp_sub = bootcamp_p.add_subparsers(dest="bootcamp_cmd")

    bootcamp_sub.add_parser("status", help="Show bootcamp progress")

    bc_enroll = bootcamp_sub.add_parser("enroll", help="Enroll agent in bootcamp")
    bc_enroll.add_argument("agent", help="Agent ID to enroll")

    # fleet-report
    subparsers.add_parser("fleet-report", help="Generate daily fleet report")

    # rewind
    rewind_p = subparsers.add_parser("rewind", help="Show state at a specific commit")
    rewind_p.add_argument("agent", help="Agent ID")
    rewind_p.add_argument("commit", help="Commit hash")

    # lessons
    lessons_p = subparsers.add_parser("lessons", help="Extract lessons learned")
    lessons_p.add_argument("agent", help="Agent ID")
    lessons_p.add_argument("--since", default=None, help="Git date reference")

    # spawn
    spawn_p = subparsers.add_parser("spawn", help="Create a git-agent for a workshop")
    spawn_p.add_argument("agent", help="Agent ID")
    spawn_p.add_argument("workshop", help="Workshop path")
    spawn_p.add_argument("--role", default=None, help="Agent role")
    spawn_p.add_argument("--stack", default="full", help="Language stack")

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)

    command_map = {
        "serve": cmd_serve,
        "narrate": cmd_narrate,
        "timeline": cmd_timeline,
        "workshop": None,  # handled by sub-subcommand
        "bootcamp": None,  # handled by sub-subcommand
        "fleet-report": cmd_fleet_report,
        "rewind": cmd_rewind,
        "lessons": cmd_lessons,
        "spawn": cmd_spawn,
    }

    # Handle sub-subcommands
    if args.command == "workshop":
        if getattr(args, "workshop_cmd", None) == "create":
            return cmd_workshop_create(args)
        elif getattr(args, "workshop_cmd", None) == "status":
            return cmd_workshop_status(args)
        else:
            parser.parse_args(["workshop", "--help"])
            return 1

    if args.command == "bootcamp":
        if getattr(args, "bootcamp_cmd", None) == "status":
            return cmd_bootcamp_status(args)
        elif getattr(args, "bootcamp_cmd", None) == "enroll":
            return cmd_bootcamp_enroll(args)
        else:
            parser.parse_args(["bootcamp", "--help"])
            return 1

    handler = command_map.get(args.command)
    if handler is None:
        parser.print_help()
        return 0 if args.command is None else 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
