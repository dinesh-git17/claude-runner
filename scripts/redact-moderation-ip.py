#!/usr/bin/env python3
"""Redact client_ip from existing moderation log files.

One-shot. Idempotent. Run on the VPS:
    python3 /claude-home/runner/scripts/redact-moderation-ip.py

Optional first argument overrides the target directory (used by tests).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def redact_file(path: Path) -> bool:
    """Remove client_ip from a moderation JSON file in place.

    Args:
        path: Target file.

    Returns:
        True if the file was rewritten, False if no client_ip was present.
    """
    data = json.loads(path.read_text())
    if "client_ip" not in data:
        return False
    del data["client_ip"]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.chmod(0o640)
    tmp.replace(path)
    return True


def main(directory: Path) -> int:
    """Redact every *.json file in the directory.

    Args:
        directory: Directory holding moderation logs.

    Returns:
        Exit code: 0 on success, 1 on errors.
    """
    redacted = 0
    skipped = 0
    errors = 0
    for path in sorted(directory.glob("*.json")):
        try:
            if redact_file(path):
                redacted += 1
            else:
                skipped += 1
        except (OSError, json.JSONDecodeError) as exc:
            errors += 1
            print(f"error: {path.name}: {exc}", file=sys.stderr)
    print(f"redacted {redacted}, skipped {skipped}, errors {errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/claude-home/moderation")
    sys.exit(main(target))
