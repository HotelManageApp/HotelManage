"""/eval-bot S3 — express checkout through the concierge (confirmation, no duplicate, lock).

Live (real LLM + running backend-api): uv run pytest -q -m "live and eval_bot" tests/eval
Pass bar: every step of every run (3 runs).
"""

import pytest

from tests.eval.live_stack import RUNS, Guest, Report, pending_of, tool_names

pytestmark = [pytest.mark.live, pytest.mark.eval_bot]


@pytest.mark.parametrize("run", RUNS)
async def test_s3_express_checkout(run: int, guests: dict[str, Guest]) -> None:
    a = guests["A"]
    report = Report("S3", run)

    # 1. The estimate and a question; nothing sent.
    body = await a.say("Tôi muốn trả phòng.")
    request = await a.checkout()
    report.add(
        "ask",
        "explains reception verifies the bill, shows the estimate, asks; nothing sent",
        pending_of(body, "CHECKOUT") is not None and request is None,
        f"pending={pending_of(body, 'CHECKOUT') is not None} request={request}",
        body,
    )

    # 2. Yes: the request is sent.
    body = await a.say("Xác nhận.")
    request = await a.checkout()
    report.add(
        "confirm",
        "a CHECKOUT_REQUESTED request for stay A",
        request is not None and request["status"] == "CHECKOUT_REQUESTED",
        f"request={request and request['status']}",
        body,
    )
    first_id = request["id"] if request else None

    # 3. Asking again: no second request.
    body = await a.say("Trả phòng giúp tôi.")
    again = await a.checkout()
    report.add(
        "again",
        "says it was already sent; still the same single request",
        again is not None and again["id"] == first_id,
        f"request={again and again['id']} first={first_id}",
        body,
    )

    # 4. Ordering while waiting for check-out: refused, nothing created.
    body = await a.say("Cho thêm 1 cà phê sữa đá.")
    orders = await a.orders()
    report.add(
        "order-locked",
        "refuses a new order while checkout is pending; no order",
        not orders and "create_room_service_order" not in tool_names(body),
        f"orders={len(orders)} tools={tool_names(body)}",
        body,
    )
    report.assert_passed()
