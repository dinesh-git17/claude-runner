"""Pytest configuration and fixtures."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    """Create test client with configured app."""
    app = create_app(settings)
    return TestClient(app)
