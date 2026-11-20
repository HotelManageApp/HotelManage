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

RoomHandler = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]
_room_vacant_handlers: list[RoomHandler] = []


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


def register_on_room_marked_vacant(handler: RoomHandler) -> RoomHandler:
    """Called inside the transaction where reception marks a room vacant by hand."""
    if handler not in _room_vacant_handlers:
        _room_vacant_handlers.append(handler)
    return handler


async def run_on_room_marked_vacant(db: AsyncSession, room_id: uuid.UUID) -> None:
    for handler in list(_room_vacant_handlers):
        await handler(db, room_id)


# ---------- bill lock ----------
# express-checkout freezes the room charge once the bill is verified. stay_access asks through
# this hook instead of importing that module.
BillLockCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[bool]]
_bill_lock_checks: list[BillLockCheck] = []


def register_bill_lock_check(check: BillLockCheck) -> BillLockCheck:
    if check not in _bill_lock_checks:
        _bill_lock_checks.append(check)
    return check


async def bill_locked(db: AsyncSession, stay_id: uuid.UUID) -> bool:
    for check in list(_bill_lock_checks):
        if await check(db, stay_id):
            return True
    return False


# ---------- desk check-out guard ----------
# Called before a check-out at the desk (not before close_stay itself, which express checkout
# also uses). A guard raises to refuse, e.g. while an express checkout request is open.
DeskCheckoutGuard = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]
_desk_checkout_guards: list[DeskCheckoutGuard] = []


def register_desk_checkout_guard(guard: DeskCheckoutGuard) -> DeskCheckoutGuard:
    if guard not in _desk_checkout_guards:
        _desk_checkout_guards.append(guard)
    return guard


async def run_desk_checkout_guards(db: AsyncSession, stay_id: uuid.UUID) -> None:
    for guard in list(_desk_checkout_guards):
        await guard(db, stay_id)
