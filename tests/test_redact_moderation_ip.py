"""Tests for redact-moderation-ip.py."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "redact-moderation-ip.py"


def _make_log(path: Path, *, with_ip: bool) -> None:
    data: dict[str, object] = {
        "timestamp": "2026-01-15T12:00:00",
        "name": "alice",
        "message_preview": "hello",
        "allowed": True,
        "reason": "approved",
        "sentiment": "neutral",
    }
    if with_ip:
        data["client_ip"] = "1.2.3.4"
    path.write_text(json.dumps(data, indent=2))
    path.chmod(0o640)


def _run(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        check=True,
    )


def test_redacts_client_ip_field(tmp_path: Path) -> None:
    """Files with client_ip have it removed."""
    target = tmp_path / "2026-01-15-120000.json"
    _make_log(target, with_ip=True)

    result = _run(tmp_path)

    payload = json.loads(target.read_text())
    assert "client_ip" not in payload
    assert "redacted 1" in result.stdout


def test_skips_files_without_client_ip(tmp_path: Path) -> None:
    """Files lacking client_ip are not modified."""
    target = tmp_path / "2026-01-15-120001-api.json"
    _make_log(target, with_ip=False)
    pre_mtime = target.stat().st_mtime

    result = _run(tmp_path)

    assert "skipped 1" in result.stdout
    assert target.stat().st_mtime == pre_mtime


def test_idempotent_second_run_redacts_nothing(tmp_path: Path) -> None:
    """Running the script twice is safe."""
    target = tmp_path / "2026-01-15-120002.json"
    _make_log(target, with_ip=True)

    _run(tmp_path)
    second = _run(tmp_path)
    assert "redacted 0" in second.stdout
    payload = json.loads(target.read_text())
    assert "client_ip" not in payload


def test_preserves_file_mode_after_redact(tmp_path: Path) -> None:
    """Redacted files retain mode 0o640."""
    target = tmp_path / "2026-01-15-120003.json"
    _make_log(target, with_ip=True)

    _run(tmp_path)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o640


def test_preserves_other_fields(tmp_path: Path) -> None:
    """Only client_ip is removed; other keys remain."""
    target = tmp_path / "2026-01-15-120004.json"
    _make_log(target, with_ip=True)

    _run(tmp_path)

    payload = json.loads(target.read_text())
    assert payload["name"] == "alice"
    assert payload["message_preview"] == "hello"
    assert payload["sentiment"] == "neutral"
