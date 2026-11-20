"""Fixtures for the concierge-actions integration tests (a module may define its own)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.backend_client import BackendClient
from app.llm.fake import FakeLLMClient
from app.main import create_app
from tests.conftest import make_settings
from tests.integration.concierge_actions.support import KEY, GateBackend


@pytest.fixture
def backend() -> GateBackend:
    return GateBackend()


@pytest.fixture
def app(fake_llm: FakeLLMClient, backend: GateBackend) -> FastAPI:
    settings = make_settings(concierge_signing_key=KEY)
    client = BackendClient("http://backend", transport=httpx.MockTransport(backend))
    return create_app(settings, llm=fake_llm, backend=client)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
