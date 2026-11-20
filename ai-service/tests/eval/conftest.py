"""Fixtures of the live /eval-bot scenarios (S2–S4); unused by the offline eval tests."""

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest

from app.core.backend_client import BackendClient
from app.core.config import ConfigError, Settings, load_settings
from app.main import create_app
from tests.eval.live_stack import Guest, close_stays, seed_stays


@dataclass
class Stack:
    settings: Settings
    ai: httpx.AsyncClient
    backend: httpx.AsyncClient


@pytest.fixture
def live_settings() -> Settings:
    try:
        settings = load_settings(app_env="test")  # "test" keeps the debug block in /chat
    except ConfigError as exc:
        pytest.fail(f"live eval needs a real LLM configuration: {exc}")
    if settings.llm_provider == "fake":
        pytest.fail("live eval needs LLM_PROVIDER=gemini|openai and its API key")
    return settings


@pytest.fixture
async def stack(live_settings: Settings) -> AsyncIterator[Stack]:
    backend_url = os.environ.get("EVAL_BACKEND_URL") or str(live_settings.backend_internal_url)
    app = create_app(live_settings, backend=BackendClient(backend_url, timeout_seconds=10))
    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://eval", timeout=60
        ) as ai,
        httpx.AsyncClient(base_url=backend_url.rstrip("/"), timeout=10) as backend,
    ):
        health = await backend.get("/health")
        if health.status_code != 200:
            pytest.fail(f"backend-api at {backend_url} is not healthy ({health.status_code})")
        yield Stack(live_settings, ai, backend)


@pytest.fixture
async def guests(stack: Stack) -> AsyncIterator[dict[str, Guest]]:
    """Fresh stays A and B for one run; closed (like a check-out) afterwards."""
    try:
        stays = await seed_stays()
    except (RuntimeError, OSError) as exc:
        pytest.fail(str(exc))
    try:
        yield {label: Guest(stay, stack.ai, stack.backend) for label, stay in stays.items()}
    finally:
        await close_stays()
