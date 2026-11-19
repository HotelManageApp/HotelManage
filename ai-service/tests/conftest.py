from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings, load_settings
from app.llm.fake import FakeLLMClient
from app.main import create_app


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {"app_env": "test", "app_version": "test-sha", "_env_file": None}
    values.update(overrides)
    return load_settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def app(settings: Settings, fake_llm: FakeLLMClient) -> FastAPI:
    return create_app(settings, llm=fake_llm)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
