"""
Entry point for running the Git Agent as a module.

Usage:
    python -m git_agent serve
    python -m git_agent narrate <agent>
    python -m git_agent --help
"""

from __future__ import annotations

import sys

from cli import main


if __name__ == "__main__":
    sys.exit(main())
