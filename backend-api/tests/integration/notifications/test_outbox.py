"""Outbox + NOTIFY semantics and the delivery worker (SPEC-notifications)."""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.notifications import templates
from app.modules.notifications.api import STAFF_EVENTS_CHANNEL, EntityType, emit_status_changed
from app.modules.notifications.models import DeliveryStatus, NotificationOutbox
from app.modules.notifications.outbox_worker import OutboxWorker
from app.modules.notifications.senders import (
    FakePushSender,
    PushMessage,
    SendOutcome,
    SendResult,
)
from app.modules.stay_access.models import Stay, StaySession
from tests.conftest import TEST_DATABASE_URL
from tests.factories import add_session, create_stay


@pytest.fixture
async def notifications() -> AsyncIterator[list[dict]]:
    """Payloads received on the staff_events channel."""
    received: list[dict] = []
    conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
    await conn.add_listener(
        STAFF_EVENTS_CHANNEL, lambda *args: received.append(json.loads(args[3]))
    )
    try:
        yield received
    finally:
        await conn.close()


async def _wait_for(predicate, within: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def _worker(db: AsyncSession, sender: FakePushSender) -> OutboxWorker:
    return OutboxWorker(async_sessionmaker(db.bind, expire_on_commit=False), sender)


async def _emit(db: AsyncSession, stay: Stay, status: str = "TEST", **kwargs) -> None:
    await emit_status_changed(
        db,
        entity_type=EntityType.STAY,
        entity_id=stay.id,
        stay_id=stay.id,
        status=status,
        room_number="101",
        actor="SYSTEM",
        **kwargs,
    )


async def _outbox(db: AsyncSession) -> list[NotificationOutbox]:
    db.expire_all()
    return list(
        await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))
    )


async def _make_due(db: AsyncSession) -> None:
    await db.execute(
        update(NotificationOutbox).values(next_attempt_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()


async def test_commit_creates_outbox_row_and_staff_event(
    db: AsyncSession, notifications: list[dict]
) -> None:
    stay = await create_stay(db)
    stay_id = stay.id  # read before _outbox() expires the session
    await _emit(db, stay)
    await db.commit()

    rows = await _outbox(db)
    assert [(r.entity_type, r.status, r.delivery_status) for r in rows] == [
        ("STAY", "TEST", DeliveryStatus.PENDING)
    ]
    await _wait_for(lambda: len(notifications) == 1)
    event = notifications[0]
    assert event["event"] == "status_changed"
    assert event["entity_type"] == "STAY"
    assert event["entity_id"] == str(stay_id)
    assert event["room_number"] == "101"


async def test_rollback_sends_nothing(db: AsyncSession, notifications: list[dict]) -> None:
    stay = await create_stay(db)
    await _emit(db, stay)
    await db.rollback()
    await asyncio.sleep(0.3)
    assert await _outbox(db) == []
    assert notifications == []


async def test_push_false_only_notifies_staff(db: AsyncSession, notifications: list[dict]) -> None:
    stay = await create_stay(db)
    await _emit(db, stay, push=False)
    await db.commit()
    await _wait_for(lambda: len(notifications) == 1)
    assert await _outbox(db) == []


async def test_worker_sends_to_every_active_device_in_its_language(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="tok-vi", lang="vi")
    await add_session(db, stay, fcm_token="tok-en", lang="en")
    await add_session(db, stay, fcm_token="tok-revoked", revoked=True)
    await add_session(db, stay, fcm_token=None)
    await _emit(db, stay)
    await db.commit()

    sender = FakePushSender()
    assert await _worker(db, sender).run_once() == 1

    by_token = {m.token: m for m in sender.sent}
    assert set(by_token) == {"tok-vi", "tok-en"}
    assert by_token["tok-vi"].title == "Thông báo thử"
    assert by_token["tok-en"].title == "Test notification"
    data = by_token["tok-vi"].data
    assert set(data) == {"type", "entity_id", "status", "title_key", "occurred_at"}
    assert data["type"] == "STAY" and data["status"] == "TEST" and data["title_key"] == "STAY.TEST"
    assert "Tran Thi B" not in json.dumps(data) and "101" not in json.dumps(data)

    row = (await _outbox(db))[0]
    assert row.delivery_status == DeliveryStatus.SENT and row.attempts == 1 and row.sent_at


async def test_nothing_to_send_is_skipped(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await _emit(db, stay)  # no device token at all
    no_template = await create_stay(db, room_number="102")
    await add_session(db, no_template, fcm_token="tok")
    await _emit(db, no_template, status="NO_SUCH_STATUS")
    await db.commit()

    sender = FakePushSender()
    await _worker(db, sender).run_once()
    assert sender.sent == []
    assert {r.delivery_status for r in await _outbox(db)} == {DeliveryStatus.SKIPPED}


async def test_unregistered_token_is_forgotten(db: AsyncSession) -> None:
    stay = await create_stay(db)
    session_id = (await add_session(db, stay, fcm_token="gone")).id
    await _emit(db, stay)
    await db.commit()

    await _worker(db, FakePushSender(outcomes=[SendOutcome.UNREGISTERED])).run_once()

    db.expire_all()
    assert (
        await db.scalar(select(StaySession.fcm_token).where(StaySession.id == session_id)) is None
    )
    assert (await _outbox(db))[0].delivery_status == DeliveryStatus.SENT


class PerTokenSender:
    """Answers per device token from a script; records every message."""

    def __init__(self, script: dict[str, list[SendOutcome]]) -> None:
        self.script = script
        self.sent: list[str] = []

    async def send(self, message: PushMessage) -> SendResult:
        self.sent.append(message.token)
        queue = self.script.get(message.token, [])
        outcome = queue.pop(0) if queue else SendOutcome.OK
        return SendResult(outcome, None if outcome is SendOutcome.OK else "503")


def _scripted_worker(db: AsyncSession, sender: PerTokenSender) -> OutboxWorker:
    return OutboxWorker(async_sessionmaker(db.bind, expire_on_commit=False), sender)


async def test_retries_only_failed_devices_then_succeeds(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="ok")
    await add_session(db, stay, fcm_token="flaky")
    await _emit(db, stay)
    await db.commit()
    sender = PerTokenSender({"flaky": [SendOutcome.RETRY, SendOutcome.RETRY]})
    worker = _scripted_worker(db, sender)

    await worker.run_once()
    row = (await _outbox(db))[0]
    assert row.delivery_status == DeliveryStatus.PENDING and row.attempts == 1
    assert row.target_tokens == [{"token": "flaky", "lang": "vi"}]
    assert row.next_attempt_at > datetime.now(UTC)
    assert await worker.run_once() == 0  # not due yet

    for _ in range(2):
        await _make_due(db)
        await worker.run_once()

    row = (await _outbox(db))[0]
    assert row.delivery_status == DeliveryStatus.SENT
    assert row.attempts == 3
    assert sorted(sender.sent) == ["flaky", "flaky", "flaky", "ok"]


async def test_fourth_failed_attempt_gives_up(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="down")
    await _emit(db, stay)
    await db.commit()
    worker = _scripted_worker(db, PerTokenSender({"down": [SendOutcome.RETRY] * 4}))
    for _ in range(4):
        await _make_due(db)
        await worker.run_once()
    row = (await _outbox(db))[0]
    assert (row.delivery_status, row.attempts) == (DeliveryStatus.FAILED, 4)


async def test_fatal_error_fails_at_once(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="any")
    await _emit(db, stay)
    await db.commit()
    await _scripted_worker(db, PerTokenSender({"any": [SendOutcome.FATAL]})).run_once()
    row = (await _outbox(db))[0]
    assert (row.delivery_status, row.attempts) == (DeliveryStatus.FAILED, 1)


async def test_fixed_recipients_win_over_current_sessions(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="current")
    await _emit(db, stay, target_tokens=[{"token": "snapshot", "lang": "en"}])
    await db.commit()
    sender = FakePushSender()
    await _worker(db, sender).run_once()
    assert [(m.token, m.title) for m in sender.sent] == [("snapshot", "Test notification")]


async def test_running_worker_delivers_within_two_seconds(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await add_session(db, stay, fcm_token="fast")
    sender = FakePushSender()
    worker = OutboxWorker(async_sessionmaker(db.bind, expire_on_commit=False), sender, interval=0.1)
    worker.start()
    try:
        await _emit(db, stay)
        await db.commit()
        committed = asyncio.get_running_loop().time()
        await _wait_for(lambda: len(sender.sent) == 1, within=2.0)
        assert asyncio.get_running_loop().time() - committed < 2.0
    finally:
        await worker.stop()


def test_every_template_exists_in_both_languages() -> None:
    assert templates.keys("vi") == templates.keys("en")
    for key in templates.keys("vi"):
        entity, status = key.split(".", 1)
        for lang in ("vi", "en"):
            text = templates.render(entity, status, lang)
            assert text and text["title"] and text["body"], (key, lang)
    assert templates.render("STAY", "CLOSED", "ko") == templates.render("STAY", "CLOSED", "vi")


async def test_unknown_stay_id_is_rejected_by_the_database(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="foreign key"):
        await emit_status_changed(
            db,
            entity_type=EntityType.STAY,
            entity_id=uuid.uuid4(),
            stay_id=uuid.uuid4(),
            status="TEST",
            room_number="1",
            actor="SYSTEM",
        )
        await db.commit()
    await db.rollback()


async def test_no_fixed_recipients_is_stored_as_sql_null(db: AsyncSession) -> None:
    stay = await create_stay(db)
    await _emit(db, stay)
    await db.commit()
    db.expire_all()
    stored = await db.scalar(
        select(NotificationOutbox.id).where(NotificationOutbox.target_tokens.is_(None))
    )
    assert stored is not None
