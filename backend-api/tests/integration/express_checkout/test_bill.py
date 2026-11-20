"""Bill of a stay, extras/discounts and the bill lock (SPEC-express-checkout, T44)."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.express_checkout.models import CheckoutRequest, CheckoutStatus, StayCharge
from app.modules.room_service.models import OrderStatus
from app.modules.staff_auth.models import StaffRole
from app.modules.stay_access.models import Stay, StayStatus
from tests.factories import add_food_order, create_menu, create_staff, create_stay, staff_headers


@pytest.fixture
async def reception(db: AsyncSession) -> dict[str, str]:
    return staff_headers(await create_staff(db, email="rx@h.test", role=StaffRole.RECEPTION))


@pytest.fixture
async def stay(db: AsyncSession) -> Stay:
    return await create_stay(db)


async def lock(db: AsyncSession, stay: Stay, status: CheckoutStatus) -> CheckoutRequest:
    request = CheckoutRequest(stay_id=stay.id, status=status, source="APP")
    db.add(request)
    await db.commit()
    return request


def bill_url(stay: Stay) -> str:
    return f"/api/v1/stays/{stay.id}/bill"


def charges_url(stay: Stay) -> str:
    return f"/api/v1/stays/{stay.id}/charges"


# ---------- build_bill ----------


async def test_bill_counts_completed_orders_and_live_charges(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    menu = await create_menu(db)
    done = await add_food_order(db, stay, OrderStatus.COMPLETED, [(menu["pho"], 2)])
    await add_food_order(db, stay, OrderStatus.CANCELLED, [(menu["cam"], 5)])
    await add_food_order(db, stay, OrderStatus.DELIVERING, [(menu["cam"], 1)])
    await add_food_order(db, stay, OrderStatus.PENDING, [(menu["pho"], 1)])

    minibar = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Minibar: 2 bia", "amount_vnd": 60000},
        headers=reception,
    )
    assert minibar.status_code == 201, minibar.text
    loyal = await client.post(
        charges_url(stay),
        json={"kind": "DISCOUNT", "description": "Khách quen", "amount_vnd": 50000},
        headers=reception,
    )
    removed = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Nhầm", "amount_vnd": 999000},
        headers=reception,
    )
    gone = await client.delete(f"{charges_url(stay)}/{removed.json()['id']}", headers=reception)
    assert gone.status_code == 204

    bill = (await client.get(bill_url(stay), headers=reception)).json()
    assert bill["stay"]["room_number"] == "101"
    assert bill["stay"]["guest_name"] == "Tran Thi B"
    assert [(line["type"], line["amount_vnd"]) for line in bill["lines"]] == [
        ("ROOM", 1_000_000),
        ("FOOD", 130_000),
        ("EXTRA", 60_000),
        ("DISCOUNT", 50_000),
    ]
    food = bill["lines"][1]
    assert food["order_id"] == str(done.id)
    assert food["description"] == f"Đơn #{str(done.id)[:4].upper()} (2 món)"
    assert bill["lines"][2]["charge_id"] == minibar.json()["id"]
    assert bill["lines"][3]["charge_id"] == loyal.json()["id"]
    assert bill["total_vnd"] == 1_000_000 + 130_000 + 60_000 - 50_000
    assert bill["open_orders"] == 2, "delivering + pending: not billed, only counted"
    assert bill["currency"] == "VND"


async def test_a_discount_above_the_bill_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    too_much = await client.post(
        charges_url(stay),
        json={"kind": "DISCOUNT", "description": "Sai", "amount_vnd": 1_000_001},
        headers=reception,
    )
    assert too_much.status_code == 409
    assert too_much.json()["error"]["code"] == "NEGATIVE_TOTAL"
    assert list(await db.scalars(select(StayCharge))) == []


async def test_removing_an_extra_cannot_leave_a_negative_bill(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    extra = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Phòng VIP", "amount_vnd": 500_000},
        headers=reception,
    )
    await client.post(
        charges_url(stay),
        json={"kind": "DISCOUNT", "description": "Giảm", "amount_vnd": 1_400_000},
        headers=reception,
    )
    refused = await client.delete(f"{charges_url(stay)}/{extra.json()['id']}", headers=reception)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "NEGATIVE_TOTAL"
    db.expire_all()
    charge = await db.get(StayCharge, uuid.UUID(extra.json()["id"]))
    assert charge is not None and charge.deleted_at is None


async def test_room_charge_changes_show_in_the_next_bill(
    client: httpx.AsyncClient, stay: Stay, reception: dict
) -> None:
    patched = await client.patch(
        f"/api/v1/stays/{stay.id}", json={"room_charge_vnd": 1_500_000}, headers=reception
    )
    assert patched.status_code == 200
    bill = (await client.get(bill_url(stay), headers=reception)).json()
    assert bill["total_vnd"] == 1_500_000


# ---------- bill lock ----------


async def test_a_verified_bill_locks_charges_and_the_room_charge(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    extra = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Minibar", "amount_vnd": 60000},
        headers=reception,
    )
    await lock(db, stay, CheckoutStatus.BILLING_VERIFIED)

    add = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Thêm", "amount_vnd": 1000},
        headers=reception,
    )
    remove = await client.delete(f"{charges_url(stay)}/{extra.json()['id']}", headers=reception)
    room = await client.patch(
        f"/api/v1/stays/{stay.id}", json={"room_charge_vnd": 1}, headers=reception
    )
    for response in (add, remove, room):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "BILL_LOCKED"
    other = await client.patch(
        f"/api/v1/stays/{stay.id}", json={"note": "Khách cần hóa đơn đỏ"}, headers=reception
    )
    assert other.status_code == 200, "only money is frozen"
    assert (await client.get(bill_url(stay), headers=reception)).json()["total_vnd"] == 1_060_000


async def test_a_request_not_yet_verified_does_not_lock(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    await lock(db, stay, CheckoutStatus.CHECKOUT_REQUESTED)
    add = await client.post(
        charges_url(stay),
        json={"kind": "EXTRA", "description": "Trả phòng trễ", "amount_vnd": 200000},
        headers=reception,
    )
    assert add.status_code == 201


async def test_finished_requests_do_not_lock(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    await lock(db, stay, CheckoutStatus.REJECTED)
    patched = await client.patch(
        f"/api/v1/stays/{stay.id}", json={"room_charge_vnd": 900_000}, headers=reception
    )
    assert patched.status_code == 200


async def test_one_open_request_per_stay(db: AsyncSession, stay: Stay) -> None:
    await lock(db, stay, CheckoutStatus.REJECTED)
    await lock(db, stay, CheckoutStatus.CHECKOUT_REQUESTED)
    with pytest.raises(IntegrityError):
        await lock(db, stay, CheckoutStatus.BILLING_VERIFIED)
    await db.rollback()


# ---------- errors and roles ----------


async def test_closed_and_unknown_stays(
    client: httpx.AsyncClient, db: AsyncSession, reception: dict
) -> None:
    closed = await create_stay(db, room_number="202", status=StayStatus.CLOSED)
    for response in (
        await client.get(bill_url(closed), headers=reception),
        await client.post(
            charges_url(closed),
            json={"kind": "EXTRA", "description": "x", "amount_vnd": 1},
            headers=reception,
        ),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "STAY_CLOSED"
    missing = f"/api/v1/stays/{uuid.uuid4()}/bill"
    assert (await client.get(missing, headers=reception)).status_code == 404


async def test_deleting_an_unknown_or_foreign_charge_is_404(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, reception: dict
) -> None:
    other = await create_stay(db, room_number="303")
    theirs = await client.post(
        charges_url(other),
        json={"kind": "EXTRA", "description": "x", "amount_vnd": 1000},
        headers=reception,
    )
    assert (
        await client.delete(f"{charges_url(stay)}/{theirs.json()['id']}", headers=reception)
    ).status_code == 404
    assert (
        await client.delete(f"{charges_url(stay)}/{uuid.uuid4()}", headers=reception)
    ).status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "EXTRA", "description": "x", "amount_vnd": 0},
        {"kind": "EXTRA", "description": "x", "amount_vnd": -5},
        {"kind": "FEE", "description": "x", "amount_vnd": 1},
        {"kind": "EXTRA", "description": "", "amount_vnd": 1},
        {"kind": "EXTRA", "description": "x", "amount_vnd": 1, "total_vnd": 0},
    ],
)
async def test_invalid_charges_are_400(
    client: httpx.AsyncClient, stay: Stay, reception: dict, body: dict
) -> None:
    assert (await client.post(charges_url(stay), json=body, headers=reception)).status_code == 400


@pytest.mark.parametrize("role", [StaffRole.KITCHEN, StaffRole.HOUSEKEEPING])
async def test_only_reception(
    client: httpx.AsyncClient, db: AsyncSession, stay: Stay, role: StaffRole
) -> None:
    other = staff_headers(await create_staff(db, email=f"{role.value}@h.test", role=role))
    for response in (
        await client.get(bill_url(stay), headers=other),
        await client.post(
            charges_url(stay),
            json={"kind": "EXTRA", "description": "x", "amount_vnd": 1},
            headers=other,
        ),
        await client.delete(f"{charges_url(stay)}/{uuid.uuid4()}", headers=other),
    ):
        assert response.status_code == 403
    assert (await client.get(bill_url(stay))).status_code == 401
