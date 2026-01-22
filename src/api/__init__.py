"""Claude's Home API package."""
from api.__main__ import main
from api.app import create_app

__all__ = ["create_app", "main"]
