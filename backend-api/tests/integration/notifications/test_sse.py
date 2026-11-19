"""Staff SSE stream: role filtering, keep-alive, expiry and latency (SPEC-notifications)."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.modules.notifications.api import EntityType, emit_status_changed
from app.modules.notifications.sse import StaffEventHub, event_stream, format_event, visible_to
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.security import encode_access_token
from tests.conftest import TEST_DATABASE_URL, TEST_STAFF_JWT_SECRET, make_settings
from tests.factories import create_staff, create_stay, staff_headers

DSN = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _event(entity_type: str, status: str = "PENDING") -> dict:
    return {
        "event": "status_changed",
        "entity_type": entity_type,
        "status": status,
        "room_number": "101",
    }


@pytest.mark.parametrize(
    ("role", "visible"),
    [
        (StaffRole.KITCHEN, {"FOOD_ORDER"}),
        (StaffRole.HOUSEKEEPING, {"HOUSEKEEPING"}),
        (StaffRole.RECEPTION, {"FOOD_ORDER", "HOUSEKEEPING", "CHECKOUT", "STAY"}),
    ],
)
def test_role_filter(role: StaffRole, visible: set[str]) -> None:
    types = {"FOOD_ORDER", "HOUSEKEEPING", "CHECKOUT", "STAY"}
    assert {t for t in types if visible_to(role, _event(t))} == visible


def test_format_event() -> None:
    text = format_event(
        {"event": "order_overdue", "entity_type": "FOOD_ORDER", "room_number": "Phòng 1"}
    )
    assert text.startswith("event: order_overdue\ndata: {")
    assert "Phòng 1" in text and text.endswith("\n\n")


async def _never_disconnected() -> bool:
    return False


async def test_stream_pings_delivers_and_ends_at_expiry() -> None:
    hub = StaffEventHub(DSN)
    sub = await hub.subscribe(StaffRole.KITCHEN)
    try:
        stream = event_stream(
            hub,
            sub,
            until=datetime.now(UTC) + timedelta(seconds=0.6),
            is_disconnected=_never_disconnected,
            ping_seconds=0.1,
        )
        hub.publish(_event("HOUSEKEEPING"))  # filtered out for the kitchen
        hub.publish(_event("FOOD_ORDER", "CONFIRMED"))
        chunks = [chunk async for chunk in stream]
    finally:
        await hub.close()
    assert chunks[0] == ": connected\n\n"
    events = [c for c in chunks if c.startswith("event:")]
    assert len(events) == 1 and '"CONFIRMED"' in events[0]
    assert ": ping\n\n" in chunks
    assert sub not in hub._subscriptions  # cleaned up when the stream ends


async def test_commit_reaches_subscribers_within_a_second(db: AsyncSession) -> None:
    hub = StaffEventHub(DSN)
    reception = await hub.subscribe(StaffRole.RECEPTION)
    kitchen = await hub.subscribe(StaffRole.KITCHEN)
    try:
        stay = await create_stay(db)
        await emit_status_changed(
            db,
            entity_type=EntityType.STAY,
            entity_id=stay.id,
            stay_id=stay.id,
            status="TEST",
            room_number="101",
            actor="SYSTEM",
            push=False,
        )
        started = asyncio.get_running_loop().time()
        await db.commit()
        event = await asyncio.wait_for(reception.queue.get(), timeout=1.0)
        assert asyncio.get_running_loop().time() - started < 1.0
        assert event["entity_type"] == "STAY"
        assert kitchen.queue.empty()
    finally:
        await hub.close()


def _short_token(staff: Staff, seconds: float) -> dict[str, str]:
    token, _ = encode_access_token(
        staff_id=staff.id,
        role=staff.role,
        token_version=staff.token_version,
        secret=TEST_STAFF_JWT_SECRET,
        ttl=timedelta(seconds=seconds),
    )
    return {"Authorization": f"Bearer {token}"}


async def test_endpoint_streams_until_token_expiry(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    staff = await create_staff(db, role=StaffRole.RECEPTION)
    response = await client.get("/api/v1/staff/events", headers=_short_token(staff, 1.5))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith(": connected")


async def test_endpoint_requires_staff(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/staff/events")).status_code == 401
    assert (
        await client.get("/api/v1/staff/events", headers={"Authorization": "Bearer guest.token.x"})
    ).status_code == 401


@pytest.fixture
def dev_app() -> FastAPI:
    return create_app(make_settings(app_env="dev"))


async def test_notify_test_only_exists_in_dev(
    dev_app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    stay = await create_stay(db)
    reception = staff_headers(await create_staff(db, email="dev@h.test", role=StaffRole.RECEPTION))
    body = {"stay_id": str(stay.id)}

    # `client` runs the test-env app: the route is not there at all.
    assert (
        await client.post("/api/v1/dev/notify-test", json=body, headers=reception)
    ).status_code == 404

    async with dev_app.router.lifespan_context(dev_app):
        transport = httpx.ASGITransport(app=dev_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as dev:
            assert (
                await dev.post("/api/v1/dev/notify-test", json=body, headers=reception)
            ).status_code == 202
            kitchen = staff_headers(
                await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN)
            )
            assert (
                await dev.post("/api/v1/dev/notify-test", json=body, headers=kitchen)
            ).status_code == 403
