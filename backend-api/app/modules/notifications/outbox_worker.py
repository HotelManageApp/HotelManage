"""Background delivery of the notification outbox (spec/SPEC-notifications.md, "Push tới khách").

Every `interval` seconds: lock up to `batch` due PENDING rows (FOR UPDATE SKIP LOCKED, so several
instances could share the work), send one message per device token, and record the outcome:

- OK for every token                      -> SENT
- token rejected (UNREGISTERED/invalid)   -> that session forgets its token
- retryable (429/5xx/network)             -> retry only the failed tokens after 2 s, 10 s, 30 s;
                                             after the 4th failed attempt -> FAILED
- fatal (credentials)                     -> FAILED at once, logged as an error
- no recipient or no template             -> SKIPPED

A failure on one row never stops the loop.
"""

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.modules.notifications import templates
from app.modules.notifications.models import DeliveryStatus, NotificationOutbox
from app.modules.notifications.senders import PushMessage, PushSender, SendOutcome
from app.modules.stay_access.models import StaySession

logger = get_logger(__name__)

RETRY_DELAYS = (timedelta(seconds=2), timedelta(seconds=10), timedelta(seconds=30))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1


async def _recipients(db: AsyncSession, row: NotificationOutbox) -> list[dict[str, str]]:
    if row.target_tokens is not None:
        return [dict(t) for t in row.target_tokens]
    result = await db.execute(
        select(StaySession.fcm_token, StaySession.lang).where(
            StaySession.stay_id == row.stay_id,
            StaySession.revoked_at.is_(None),
            StaySession.fcm_token.is_not(None),
        )
    )
    return [{"token": token, "lang": lang} for token, lang in result.all() if token]


def _message(row: NotificationOutbox, recipient: dict[str, str]) -> PushMessage | None:
    text = templates.render(row.entity_type, row.status, recipient.get("lang", "vi"))
    if text is None:
        return None
    return PushMessage(
        token=recipient["token"],
        title=text["title"],
        body=text["body"],
        data={
            "type": row.entity_type,
            "entity_id": str(row.entity_id),
            "status": row.status,
            "title_key": templates.template_key(row.entity_type, row.status),
            "occurred_at": row.created_at.isoformat(),
        },
    )


async def _forget_token(db: AsyncSession, token: str) -> None:
    await db.execute(
        update(StaySession)
        .where(StaySession.fcm_token == token)
        .values(fcm_token=None, fcm_updated_at=datetime.now(UTC))
    )


async def deliver(db: AsyncSession, row: NotificationOutbox, sender: PushSender) -> None:
    now = datetime.now(UTC)
    recipients = await _recipients(db, row)
    messages = [(m, r) for r in recipients if (m := _message(row, r)) is not None]
    if not messages:
        row.delivery_status = DeliveryStatus.SKIPPED
        row.target_tokens = None
        return

    row.attempts += 1
    retry: list[dict[str, Any]] = []
    fatal: str | None = None
    for message, recipient in messages:
        result = await sender.send(message)
        if result.outcome is SendOutcome.UNREGISTERED:
            await _forget_token(db, message.token)
        elif result.outcome is SendOutcome.RETRY:
            retry.append(recipient)
            row.last_error = result.error
        elif result.outcome is SendOutcome.FATAL:
            fatal = result.error or "fatal"

    if fatal is not None:
        row.delivery_status = DeliveryStatus.FAILED
        row.last_error = fatal
        logger.error("notification_send_fatal", outbox_id=str(row.id), error=fatal)
    elif retry and row.attempts < MAX_ATTEMPTS:
        row.target_tokens = retry
        row.next_attempt_at = now + RETRY_DELAYS[row.attempts - 1]
    elif retry:
        row.delivery_status = DeliveryStatus.FAILED
        logger.warning("notification_failed", outbox_id=str(row.id), error=row.last_error)
    else:
        row.delivery_status = DeliveryStatus.SENT
        row.sent_at = now


class OutboxWorker:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        sender: PushSender,
        *,
        interval: float = 1.0,
        batch: int = 50,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._sender = sender
        self._interval = interval
        self._batch = batch
        self._task: asyncio.Task[None] | None = None

    async def run_once(self) -> int:
        """Deliver one batch of due rows. Returns how many rows were handled."""
        async with self._sessionmaker() as db, db.begin():
            rows: Sequence[NotificationOutbox] = (
                await db.scalars(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.delivery_status == DeliveryStatus.PENDING,
                        NotificationOutbox.next_attempt_at <= datetime.now(UTC),
                    )
                    .order_by(NotificationOutbox.created_at)
                    .limit(self._batch)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                try:
                    async with db.begin_nested():
                        await deliver(db, row, self._sender)
                except Exception:
                    logger.exception("notification_delivery_error", outbox_id=str(row.id))
            return len(rows)

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("notification_worker_error")
            await asyncio.sleep(self._interval)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="notification-outbox")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
