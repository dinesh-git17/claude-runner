"""Health endpoint tests."""
from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    """Health endpoint returns 200 OK."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_health_returns_status(client: TestClient) -> None:
    """Health endpoint returns status in response."""
    response = client.get("/api/v1/health")
    data = response.json()
    assert "status" in data
    assert data["status"] == "ok"
