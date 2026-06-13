#!/usr/bin/env python3
"""
git-agent — API-agnostic autonomous git-native agent.

Usage:
    python -m git_agent                # Full autonomous session
    python -m git_agent observe        # Only observe fleet state
    python -m git_agent plan           # Only plan (dry-run)
    python -m git_agent bootstrap      # First-run setup
    python -m git_agent version        # Print version
"""

import argparse
import asyncio
import logging
import os
import sys

from git_agent import __version__

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("git-agent")


def find_config() -> str:
    """Find configuration file."""
    # 1. Explicit path via env var
    env_path = os.environ.get("GIT_AGENT_CONFIG")
    if env_path and os.path.isfile(env_path):
        return env_path

    # 2. ~/.git-agent/config.yaml
    home_config = os.path.expanduser("~/.git-agent/config.yaml")
    if os.path.isfile(home_config):
        return home_config

    # 3. ./config.yaml in cwd
    if os.path.isfile("config.yaml"):
        return "config.yaml"

    # 4. Not found
    return ""


def cmd_bootstrap(args):
    """Run first-time bootstrap."""
    from git_agent.config import AgentConfig
    from git_agent.vessel import VesselManager
    from git_agent.github.client import GitHubAPIClient

    config_path = find_config()
    if not config_path:
        logger.error(
            "No configuration found. Run the setup wizard first:\n"
            "  python onboarding/config_wizard.py\n"
            "Or set GIT_AGENT_CONFIG=/path/to/config.yaml"
        )
        sys.exit(1)

    config = AgentConfig.load(config_path)
    logger.info("Bootstrapping agent %s...", config.agent_name)

    gh = GitHubAPIClient(token=config.github_token)
    vessel = VesselManager(
        gh_client=gh,
        vessel_repo=config.vessel_repo,
        agent_name=config.agent_name,
    )
    vessel.bootstrap()
    logger.info("Bootstrap complete. Vessel initialized at %s", vessel.vessel_path)


def cmd_observe(args):
    """Observe fleet state without executing."""
    from git_agent.config import AgentConfig
    from git_agent.fleet.reader import FleetReader
    from git_agent.github.client import GitHubAPIClient

    config_path = find_config()
    if not config_path:
        logger.error("No configuration found.")
        sys.exit(1)

    config = AgentConfig.load(config_path)
    gh = GitHubAPIClient(token=config.github_token)

    reader = FleetReader(gh_client=gh, fleet_org=config.fleet_org)

    logger.info("Observing fleet state for org: %s", config.fleet_org or "(user repos)")

    # Read tasks
    tasks = reader.read_tasks()
    logger.info("Found %d open tasks", len(tasks))
    for task in tasks[:10]:
        logger.info("  [%s] %s — %s (priority: %s)", task.id, task.repo, task.title, task.priority)

    # Read bottles
    bottles = reader.read_bottles()
    logger.info("Found %d bottles", len(bottles))
    for bottle in bottles[:5]:
        logger.info("  From %s: %s", bottle.get("from", "?"), bottle.get("subject", "?")[:60])

    # Read fleet status
    fleet = reader.read_fleet_status()
    if fleet:
        logger.info("Active vessels: %d", len(fleet.get("vessels", [])))

    logger.info("Observation complete.")


def cmd_plan(args):
    """Plan tasks without executing (dry run)."""
    from git_agent.config import AgentConfig
    from git_agent.fleet.reader import FleetReader
    from git_agent.fleet.planner import FleetPlanner
    from git_agent.github.client import GitHubAPIClient

    config_path = find_config()
    if not config_path:
        logger.error("No configuration found.")
        sys.exit(1)

    config = AgentConfig.load(config_path)
    gh = GitHubAPIClient(token=config.github_token)

    reader = FleetReader(gh_client=gh, fleet_org=config.fleet_org)
    planner = FleetPlanner(reader=reader)

    plan = planner.create_plan(max_tasks=args.max_tasks)
    logger.info("Generated plan with %d tasks:", len(plan.tasks))
    for task in plan.tasks:
        logger.info(
            "  [%s] %s — %s (score: %.1f, repo: %s)",
            task.id,
            task.title,
            task.action,
            task.score,
            task.repo,
        )

    if plan.execution_order:
        logger.info("Execution order: %s", " → ".join(t.id for t in plan.execution_order))


def cmd_run(args):
    """Run full autonomous agent session."""
    from git_agent.config import AgentConfig
    from git_agent.agent import Agent
    from git_agent.llm import create_provider
    from git_agent.github.client import GitHubAPIClient
    from git_agent.fleet.reader import FleetReader
    from git_agent.fleet.executor import TaskExecutor
    from git_agent.fleet.communicator import FleetCommunicator
    from git_agent.vessel import VesselManager

    config_path = find_config()
    if not config_path:
        logger.error(
            "No configuration found. Run the setup wizard first:\n"
            "  python onboarding/config_wizard.py"
        )
        sys.exit(1)

    config = AgentConfig.load(config_path)
    logger.info("Starting agent session as %s", config.agent_name)
    logger.info("LLM provider: %s (model: %s)", config.llm_provider, config.llm_model)

    # Create dependencies
    llm = create_provider(config)
    gh = GitHubAPIClient(token=config.github_token)
    reader = FleetReader(gh_client=gh, fleet_org=config.fleet_org)
    communicator = FleetCommunicator(gh_client=gh, fleet_org=config.fleet_org)
    vessel = VesselManager(
        gh_client=gh,
        vessel_repo=config.vessel_repo,
        agent_name=config.agent_name,
    )
    executor = TaskExecutor(
        gh_client=gh,
        llm=llm,
        work_dir=args.work_dir,
    )

    # Create and run agent
    agent = Agent(
        config=config,
        llm=llm,
        gh_client=gh,
        reader=reader,
        planner=None,  # Uses default
        executor=executor,
        communicator=communicator,
        vessel=vessel,
    )

    try:
        agent.run(
            max_tasks=args.max_tasks,
            max_rounds=args.max_rounds,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        logger.info("Agent interrupted by user. Saving state...")
        agent.reflect()
    except Exception as e:
        logger.error("Agent session failed: %s", e, exc_info=True)
        sys.exit(1)

    logger.info("Session complete.")


def main():
    parser = argparse.ArgumentParser(
        prog="git-agent",
        description="API-agnostic autonomous git-native agent",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run full autonomous session")
    run_parser.add_argument("--max-tasks", type=int, default=10, help="Max tasks per session")
    run_parser.add_argument("--max-rounds", type=int, default=5, help="Max planning rounds")
    run_parser.add_argument("--work-dir", default="./workspace", help="Working directory")
    run_parser.add_argument("--dry-run", action="store_true", help="Plan without executing")

    # observe
    subparsers.add_parser("observe", help="Observe fleet state")

    # plan
    plan_parser = subparsers.add_parser("plan", help="Plan tasks (dry run)")
    plan_parser.add_argument("--max-tasks", type=int, default=10, help="Max tasks to plan")

    # bootstrap
    subparsers.add_parser("bootstrap", help="First-run setup")

    args = parser.parse_args()

    if args.command == "bootstrap":
        cmd_bootstrap(args)
    elif args.command == "observe":
        cmd_observe(args)
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "run" or args.command is None:
        cmd_run(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
