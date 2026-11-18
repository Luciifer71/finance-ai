"""Shared FastAPI dependencies (settings, clock)."""

from fastapi import Request

from app.core.clock import Clock
from app.core.config import Settings


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock
