"""Hooks run inside the transaction that closes a stay (check-out at the desk or express checkout).

Other modules register handlers at import time; stay_access never imports them back:

    register_on_stay_closed(cancel_open_orders)   # room-service (T27)
    register_on_stay_closed(create_turnover)      # housekeeping (T34)

A handler that raises aborts the whole close: the stay stays open and nothing is committed.
"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

StayClosedHandler = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]

_handlers: list[StayClosedHandler] = []


def register_on_stay_closed(handler: StayClosedHandler) -> StayClosedHandler:
    if handler not in _handlers:
        _handlers.append(handler)
    return handler


def unregister_on_stay_closed(handler: StayClosedHandler) -> None:
    if handler in _handlers:
        _handlers.remove(handler)


async def run_on_stay_closed(db: AsyncSession, stay_id: uuid.UUID) -> None:
    for handler in list(_handlers):
        await handler(db, stay_id)
