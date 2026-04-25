"""Tests for retention-sweep.sh."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "retention-sweep.sh"


def _touch_with_age(path: Path, *, days_old: int) -> None:
    """Create a file and set mtime to N days in the past."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("test")
    age = time.time() - (days_old * 86400)
    os.utime(path, (age, age))


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    arch = tmp_path / "visitors-archive"
    mod = tmp_path / "moderation"
    log = tmp_path / "logs" / "retention-sweep.log"
    arch.mkdir(parents=True)
    mod.mkdir(parents=True)
    return arch, mod, log


def _run(
    arch: Path, mod: Path, log: Path, *, dry_run: bool = False
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VISITORS_ARCHIVE"] = str(arch)
    env["MODERATION_DIR"] = str(mod)
    env["LOG_FILE"] = str(log)
    args = [str(SCRIPT)]
    if dry_run:
        args.append("--dry-run")
    return subprocess.run(args, capture_output=True, text=True, check=True, env=env)


def test_prunes_files_older_than_30_days(tmp_path: Path) -> None:
    """Old files are deleted; fresh files survive."""
    arch, mod, log = _setup_dirs(tmp_path)
    old_msg = arch / "2026-01" / "2026-01-01-old.md"
    fresh_msg = arch / "2026-04" / "2026-04-25-fresh.md"
    _touch_with_age(old_msg, days_old=60)
    _touch_with_age(fresh_msg, days_old=5)

    old_mod = mod / "old.json"
    fresh_mod = mod / "fresh.json"
    _touch_with_age(old_mod, days_old=60)
    _touch_with_age(fresh_mod, days_old=5)

    _run(arch, mod, log)

    assert not old_msg.exists()
    assert fresh_msg.exists()
    assert not old_mod.exists()
    assert fresh_mod.exists()


def test_sweeps_empty_partition_dirs(tmp_path: Path) -> None:
    """Empty YYYY-MM/ directories left after pruning are removed."""
    arch, mod, log = _setup_dirs(tmp_path)
    old_only = arch / "2026-01" / "2026-01-01-old.md"
    _touch_with_age(old_only, days_old=60)

    _run(arch, mod, log)

    assert not (arch / "2026-01").exists()


def test_dry_run_does_not_delete(tmp_path: Path) -> None:
    """--dry-run reports counts but leaves files in place."""
    arch, mod, log = _setup_dirs(tmp_path)
    old = arch / "2026-01" / "2026-01-01-old.md"
    old_mod = mod / "old.json"
    _touch_with_age(old, days_old=60)
    _touch_with_age(old_mod, days_old=60)

    _run(arch, mod, log, dry_run=True)

    assert old.exists()
    assert old_mod.exists()
    assert "would prune" in log.read_text()


def test_handles_missing_directories(tmp_path: Path) -> None:
    """Missing target directories do not crash the sweep."""
    log = tmp_path / "logs" / "retention-sweep.log"
    arch = tmp_path / "missing-arch"
    mod = tmp_path / "missing-mod"

    _run(arch, mod, log)

    assert log.exists()
    assert "retention-sweep complete" in log.read_text()


def test_includes_api_json_flavour(tmp_path: Path) -> None:
    """Trusted-key flow's -api.json files are also pruned by age."""
    arch, mod, log = _setup_dirs(tmp_path)
    api_old = mod / "2026-01-01-old-api.json"
    api_fresh = mod / "2026-04-25-fresh-api.json"
    _touch_with_age(api_old, days_old=60)
    _touch_with_age(api_fresh, days_old=5)

    _run(arch, mod, log)

    assert not api_old.exists()
    assert api_fresh.exists()
