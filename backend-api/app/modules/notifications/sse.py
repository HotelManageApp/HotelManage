"""Realtime events for staff screens over Server-Sent Events (spec/SPEC-notifications.md).

One PostgreSQL `LISTEN staff_events` connection per process feeds every open stream. Each stream
only receives the entity types its role works on:

    KITCHEN       -> FOOD_ORDER
    HOUSEKEEPING  -> HOUSEKEEPING
    RECEPTION     -> everything

The stream sends `: ping` every 15 s, and ends when the access token expires (the web client
refreshes and reconnects, then reloads its lists — missed events are not replayed in V1).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.logging import get_logger
from app.modules.notifications.api import STAFF_EVENTS_CHANNEL
from app.modules.staff_auth.deps import CurrentStaff
from app.modules.staff_auth.models import StaffRole
from app.modules.staff_auth.security import decode_access_token

logger = get_logger(__name__)

PING_SECONDS = 15.0
QUEUE_SIZE = 200

ROLE_ENTITY_TYPES: dict[StaffRole, frozenset[str] | None] = {
    StaffRole.KITCHEN: frozenset({"FOOD_ORDER"}),
    StaffRole.HOUSEKEEPING: frozenset({"HOUSEKEEPING"}),
    StaffRole.RECEPTION: None,  # all
}


def visible_to(role: StaffRole, event: dict[str, Any]) -> bool:
    if event.get("event") == "do_not_disturb" and role is StaffRole.HOUSEKEEPING:
        return True  # housekeeping must know not to knock
    allowed = ROLE_ENTITY_TYPES[role]
    return allowed is None or event.get("entity_type") in allowed


@dataclass(eq=False)
class Subscription:
    role: StaffRole
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=QUEUE_SIZE)
    )


class StaffEventHub:
    """Fan-out of `staff_events` NOTIFY messages to subscribed streams."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: asyncpg.Connection | None = None
        self._subscriptions: set[Subscription] = set()
        self._lock = asyncio.Lock()

    async def _ensure_listening(self) -> None:
        async with self._lock:
            if self._conn is not None and not self._conn.is_closed():
                return
            self._conn = await asyncpg.connect(self._dsn)
            await self._conn.add_listener(STAFF_EVENTS_CHANNEL, self._on_notify)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        try:
            event = json.loads(payload)
        except ValueError:
            logger.warning("staff_event_bad_payload")
            return
        self.publish(event)

    def publish(self, event: dict[str, Any]) -> None:
        for sub in list(self._subscriptions):
            if visible_to(sub.role, event):
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("staff_event_dropped", role=sub.role.value)

    async def subscribe(self, role: StaffRole) -> Subscription:
        await self._ensure_listening()
        sub = Subscription(role)
        self._subscriptions.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscriptions.discard(sub)

    async def close(self) -> None:
        if self._conn is not None and not self._conn.is_closed():
            await self._conn.close()
        self._conn = None


def format_event(event: dict[str, Any]) -> str:
    name = event.get("event", "status_changed")
    return f"event: {name}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def event_stream(
    hub: StaffEventHub,
    sub: Subscription,
    *,
    until: datetime,
    is_disconnected: Callable[[], Awaitable[bool]],
    ping_seconds: float = PING_SECONDS,
) -> AsyncIterator[str]:
    try:
        yield ": connected\n\n"
        while True:
            remaining = (until - datetime.now(UTC)).total_seconds()
            if remaining <= 0 or await is_disconnected():
                return
            try:
                event = await asyncio.wait_for(sub.queue.get(), min(ping_seconds, remaining))
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield format_event(event)
    finally:
        hub.unsubscribe(sub)


router = APIRouter(prefix="/staff", tags=["realtime"])
_bearer = HTTPBearer(auto_error=False)


@router.get("/events")
async def staff_events(
    request: Request,
    staff: CurrentStaff,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> StreamingResponse:
    settings = request.app.state.settings
    # current_staff already validated the token; read its expiry to end the stream on time.
    claims = decode_access_token(
        credentials.credentials if credentials else "",
        secret=settings.staff_jwt_secret.get_secret_value(),
    )
    hub: StaffEventHub = request.app.state.staff_event_hub
    sub = await hub.subscribe(staff.role)
    return StreamingResponse(
        event_stream(hub, sub, until=claims.expires_at, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        # no-transform: proxies and the admin-web server (Next's gzip) must not compress the
        # stream, or events sit in the compressor's buffer and never reach the browser.
        headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"},
    )
