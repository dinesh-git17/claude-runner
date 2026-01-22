"""Pytest configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        host="127.0.0.1",
        port=8000,
        debug=True,
        content_root="/tmp/test-content",
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Create test client with configured app."""
    app = create_app(settings)
    return TestClient(app)
