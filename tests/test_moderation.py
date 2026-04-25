"""Tests for the moderation log endpoint."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.config import Settings


@pytest.fixture
def moderation_settings() -> Settings:
    """Test settings with a known API key."""
    return Settings(host="127.0.0.1", port=8000, debug=True, key="test-key")


@pytest.fixture
def moderation_client(
    moderation_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Test client that writes moderation logs to tmp_path.

    Built without entering the lifespan context so the watcher does not
    try to monitor the production /claude-home directories.
    """
    monkeypatch.setattr("api.routes.moderation.MODERATION_DIR", tmp_path)
    app = create_app(moderation_settings)
    return TestClient(app, headers={"X-API-Key": "test-key"})


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "alice",
        "message_preview": "hello world",
        "allowed": True,
        "reason": "approved",
        "sentiment": "neutral",
    }
    base.update(overrides)
    return base


def test_persisted_log_omits_client_ip(
    moderation_client: TestClient, tmp_path: Path
) -> None:
    """Moderation log written to disk does not contain client_ip."""
    response = moderation_client.post("/api/v1/moderation/log", json=_payload())
    assert response.status_code == 200

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    persisted = json.loads(files[0].read_text())
    assert "client_ip" not in persisted


def test_extra_client_ip_field_is_dropped(
    moderation_client: TestClient, tmp_path: Path
) -> None:
    """Caller sending client_ip does not cause it to be persisted."""
    response = moderation_client.post(
        "/api/v1/moderation/log",
        json=_payload(client_ip="1.2.3.4"),
    )
    assert response.status_code == 200

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    persisted = json.loads(files[0].read_text())
    assert "client_ip" not in persisted
    assert persisted["name"] == "alice"


def test_persisted_log_includes_expected_fields(
    moderation_client: TestClient, tmp_path: Path
) -> None:
    """The persisted log keeps every expected field other than client_ip."""
    response = moderation_client.post("/api/v1/moderation/log", json=_payload())
    assert response.status_code == 200

    persisted = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert set(persisted.keys()) == {
        "timestamp",
        "name",
        "message_preview",
        "allowed",
        "reason",
        "sentiment",
    }
