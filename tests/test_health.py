"""Health endpoint tests."""

from fastapi.testclient import TestClient


def test_liveness_returns_200(client: TestClient) -> None:
    """Liveness endpoint returns 200 OK."""
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_liveness_returns_status(client: TestClient) -> None:
    """Liveness endpoint returns alive status."""
    response = client.get("/api/v1/health/live")
    data = response.json()
    assert "status" in data
    assert data["status"] == "alive"
