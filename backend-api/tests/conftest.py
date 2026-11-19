import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings, load_settings
from app.main import create_app
from app.models import Base

# Integration tests run against a real PostgreSQL database (spec: no SQLite).
# Local: `docker compose up -d db` creates `hotel_test`. CI: service container (T06).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://hotel:hotel_dev_only@localhost:5432/hotel_test",
)
TEST_STAFF_JWT_SECRET = "test-staff-secret-" + "x" * 32
BACKEND_ROOT = Path(__file__).resolve().parents[1]

# Tables whose rows are part of the schema itself (seeded by migrations); never truncated.
_KEEP_ROWS = {"hotel_settings"}


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": TEST_DATABASE_URL,
        "app_version": "test-sha",
        "staff_jwt_secret": TEST_STAFF_JWT_SECRET,
        "_env_file": None,
    }
    values.update(overrides)
    return load_settings(**values)


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def migrated_database() -> None:
    """Bring the test database to the latest schema once per test session."""
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def db(migrated_database: None) -> AsyncIterator[AsyncSession]:
    """A session on the migrated test DB; all data rows are wiped after each test."""
    engine = create_async_engine(TEST_DATABASE_URL)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        tables = [t.name for t in Base.metadata.sorted_tables if t.name not in _KEEP_ROWS]
        if tables:
            async with engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
        await engine.dispose()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
