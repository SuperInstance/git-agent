"""
git_agent.fleet — Fleet coordination modules.

Provides tools for reading fleet state, planning tasks, executing
work in parallel, inter-agent communication, and cross-repo research.
"""

from .reader import FleetReader
from .planner import FleetPlanner
from .executor import TaskExecutor
from .communicator import FleetCommunicator
from .researcher import FleetResearcher

__all__ = [
    "FleetReader",
    "FleetPlanner",
    "TaskExecutor",
    "FleetCommunicator",
    "FleetResearcher",
]
