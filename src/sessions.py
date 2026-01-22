#!/usr/bin/env python3
"""View Claude's session history."""

import sqlite3
from pathlib import Path

DB_PATH = Path("/claude-home/sessions.db")

def main():
    if not DB_PATH.exists():
        print("No sessions yet.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, timestamp, session_type, input_tokens, output_tokens,
               files_created, duration_seconds, error
        FROM sessions
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    rows = cursor.fetchall()

    if not rows:
        print("No sessions recorded yet.")
        return

    print(f"{'ID':<4} {'Timestamp':<20} {'Type':<8} {'In':<6} {'Out':<6} {'Files':<5} {'Duration':<8} {'Error'}")
    print("-" * 80)

    for row in rows:
        id_, ts, stype, inp, out, files, dur, err = row
        ts_short = ts[:19] if ts else ""
        dur_str = f"{dur:.1f}s" if dur else ""
        err_str = err[:20] + "..." if err and len(err) > 20 else (err or "")
        print(f"{id_:<4} {ts_short:<20} {stype:<8} {inp or 0:<6} {out or 0:<6} {files:<5} {dur_str:<8} {err_str}")

    conn.close()

if __name__ == "__main__":
    main()
