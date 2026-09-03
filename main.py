"""ASGI entry point: ``uvicorn main:app --reload``."""

from backend.app import app

__all__ = ["app"]
