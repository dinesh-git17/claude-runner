#!/claude-home/runner/.venv/bin/python3
"""Session orchestrator entry point.

Replaces wake.sh — invoked by cron, pollers, and manual triggers.

Usage:
    wake.py morning
    wake.py telegram "message from dinesh" dinesh
    wake.py visit "visitor message"
    wake.py self "reason for self-scheduled session"
    wake.py correspondence "user1,user2"
    wake.py custom "full custom prompt"
    wake.py --dry-run morning
"""

import asyncio
import sys

from orchestrator.cli import main_async, parse_args

if __name__ == "__main__":
    args = parse_args()
    sys.exit(asyncio.run(main_async(args)))
