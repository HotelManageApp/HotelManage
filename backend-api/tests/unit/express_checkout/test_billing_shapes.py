import uuid
from datetime import UTC, datetime

from app.modules.express_checkout.billing import Bill, BillLine, BillStay, _order_label


def test_food_lines_name_the_order_briefly() -> None:
    order_id = uuid.UUID("a1b2c3d4-0000-4000-8000-000000000000")
    assert _order_label(order_id, 3) == "Đơn #A1B2 (3 món)"


def test_a_bill_serialises_to_plain_json_for_the_snapshot() -> None:
    now = datetime(2026, 11, 20, 5, tzinfo=UTC)
    bill = Bill(
        stay=BillStay(room_number="101", guest_name=None, checkin_at=now, expected_checkout_at=now),
        lines=[BillLine(type="ROOM", description="Tiền phòng", amount_vnd=1_200_000)],
        total_vnd=1_200_000,
        open_orders=0,
        generated_at=now,
    )
    data = bill.model_dump(mode="json")
    assert data["lines"][0] == {
        "type": "ROOM",
        "description": "Tiền phòng",
        "amount_vnd": 1_200_000,
        "order_id": None,
        "charge_id": None,
    }
    assert data["generated_at"] == "2026-11-20T05:00:00Z"
    assert Bill.model_validate(data) == bill
