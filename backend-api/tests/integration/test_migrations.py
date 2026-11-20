"""Migrations apply and roll back cleanly, and match the ORM models.

Sync tests on purpose: Alembic's env.py runs its own event loop.
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests.conftest import TEST_DATABASE_URL

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALL_TABLES = sorted(Base.metadata.tables)


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    return cfg


async def _query(sql: str) -> list[tuple]:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).all())
    finally:
        await engine.dispose()


async def _schema_diff() -> list:
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: compare_metadata(
                    MigrationContext.configure(sync_conn), Base.metadata
                )
            )
    finally:
        await engine.dispose()


def _table_exists(name: str) -> bool:
    rows = asyncio.run(_query(f"SELECT to_regclass('public.{name}') IS NOT NULL"))
    return bool(rows[0][0])


def test_upgrade_downgrade_upgrade_roundtrip() -> None:
    cfg = _alembic_config()

    command.upgrade(cfg, "head")
    for table in ALL_TABLES:
        assert _table_exists(table), table

    command.downgrade(cfg, "base")
    for table in ALL_TABLES:
        assert not _table_exists(table), table

    command.upgrade(cfg, "head")  # leave the test DB at head for other tests
    assert asyncio.run(_query("SELECT id FROM hotel_settings")) == [(1,)]
    extensions = {row[0] for row in asyncio.run(_query("SELECT extname FROM pg_extension"))}
    assert {"pgcrypto", "citext", "unaccent"} <= extensions


def test_models_match_migrations() -> None:
    command.upgrade(_alembic_config(), "head")
    assert asyncio.run(_schema_diff()) == []


def test_hotel_settings_allows_only_one_row() -> None:
    command.upgrade(_alembic_config(), "head")

    async def insert_second_row() -> str:
        engine = create_async_engine(TEST_DATABASE_URL)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("INSERT INTO hotel_settings (id) VALUES (2)"))
            return "inserted"
        except Exception as exc:
            return type(exc).__name__
        finally:
            await engine.dispose()

    assert asyncio.run(insert_second_row()) == "IntegrityError"
