#!/usr/bin/env python3
"""CLI tool for Claudie to send letters to mailbox users.

Usage:
    send-letter.py --to <username> [--reply-to <msg_id>] <message>
    send-letter.py --to <username> [--reply-to <msg_id>] --file <path>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

MAILBOX_DIR = Path("/claude-home/mailbox")

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
log = logging.getLogger(__name__)


def read_thread(username: str) -> list[dict[str, object]]:
    """Read all messages from a user's thread, skipping corrupt lines."""
    thread_path = MAILBOX_DIR / username / "thread.jsonl"
    if not thread_path.exists():
        return []
    messages: list[dict[str, object]] = []
    for line_num, line in enumerate(thread_path.read_text().splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            messages.append(json.loads(stripped))
        except json.JSONDecodeError:
            log.warning(
                "mailbox_jsonl_corrupt_line: username=%s line=%d",
                username,
                line_num,
            )
    return messages


def generate_message_id(username: str) -> str:
    """Generate a claudie message ID: msg_YYYYMMDD_c_NNN."""
    today = datetime.now(UTC).strftime("%Y%m%d")
    id_prefix = f"msg_{today}_c_"
    messages = read_thread(username)
    count = sum(1 for m in messages if str(m.get("id", "")).startswith(id_prefix))
    return f"{id_prefix}{count + 1:03d}"


def main() -> None:
    """Entry point for send-letter CLI."""
    parser = argparse.ArgumentParser(description="Send a letter to a mailbox user")
    parser.add_argument("--to", required=True, help="Recipient username")
    parser.add_argument("--reply-to", default=None, help="Message ID being replied to")
    parser.add_argument("--file", default=None, help="Read message body from file")
    parser.add_argument("message", nargs="*", help="Message body (if not using --file)")
    args = parser.parse_args()

    username = args.to
    user_dir = MAILBOX_DIR / username

    if not user_dir.exists():
        msg = f"No mailbox found for '{username}'"
        log.error(msg)
        sys.exit(1)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            msg = f"File not found: {args.file}"
            log.error(msg)
            sys.exit(1)
        body = file_path.read_text().strip()
    elif args.message:
        body = " ".join(args.message)
    else:
        log.error("No message provided")
        sys.exit(1)

    if not body:
        log.error("Message body is empty")
        sys.exit(1)

    msg_id = generate_message_id(username)
    now = datetime.now(UTC).isoformat()

    message_obj: dict[str, str] = {
        "id": msg_id,
        "from": "claudie",
        "ts": now,
        "body": body,
    }
    if args.reply_to:
        message_obj["in_reply_to"] = args.reply_to

    thread_path = user_dir / "thread.jsonl"
    line = json.dumps(message_obj, separators=(",", ":")) + "\n"
    with thread_path.open("a") as f:
        f.write(line)

    sys.stdout.write(f"Letter sent to {username} ({msg_id})\n")


if __name__ == "__main__":
    main()
