"""/eval-bot S2 — ordering food through the concierge, with the confirmation step (C2.5).

Live (real LLM + running backend-api): uv run pytest -q -m "live and eval_bot" tests/eval
Pass bar: every step of every run (3 runs).
"""

import pytest

from tests.eval.live_stack import RUNS, Guest, Report, pending_of, price_of, tool_names

pytestmark = [pytest.mark.live, pytest.mark.eval_bot]


@pytest.mark.parametrize("run", RUNS)
async def test_s2_order_with_confirmation(run: int, guests: dict[str, Guest]) -> None:
    a = guests["A"]
    menu = await a.menu()
    if not menu["is_open_now"]:
        pytest.fail("S2 needs the kitchen open: set the service hours to include now")
    pho, cam = price_of(menu, "Phở bò"), price_of(menu, "Nước cam")
    report = Report("S2", run)

    # 1. Proposal only: the summary with the backend's total, nothing placed.
    body = await a.say("Cho tôi 2 phở bò và 1 nước cam.")
    pending = pending_of(body, "FOOD_ORDER")
    total = (pending or {}).get("summary", {}).get("total_vnd")
    orders = await a.orders()
    report.add(
        "summary",
        "summary with the 2 phở + 1 cam total, asks to confirm, no order yet",
        pending is not None and total == 2 * pho + cam and not orders,
        f"pending={bool(pending)} total={total} orders={len(orders)}",
        body,
    )

    # 2. A change: a new summary, still nothing placed.
    body = await a.say("Đổi thành 1 phở thôi.")
    pending = pending_of(body, "FOOD_ORDER")
    changed = (pending or {}).get("summary", {}).get("total_vnd")
    orders = await a.orders()
    report.add(
        "change",
        "a new summary (1 phở, with or without the cam), no order yet",
        pending is not None and changed in (pho, pho + cam) and not orders,
        f"pending={bool(pending)} total={changed} orders={len(orders)}",
        body,
    )

    # 3. Yes: exactly one order, with the confirmed total.
    body = await a.say("Đúng rồi, đặt đi.")
    orders = await a.orders()
    report.add(
        "confirm",
        "exactly one PENDING order from the chatbot with the confirmed total",
        len(orders) == 1
        and orders[0]["status"] == "PENDING"
        and orders[0]["total_vnd"] == changed
        and orders[0]["source"] == "CHATBOT",
        f"orders={[(o['status'], o['total_vnd'], o['source']) for o in orders]}",
        body,
    )

    # 4. A dish that is not on the menu: nothing new.
    body = await a.say("Cho thêm 1 tôm hùm.")
    after = await a.orders()
    report.add(
        "unknown-dish",
        "says it is not on the menu; no new order",
        len(after) == 1,
        f"orders={len(after)} tools={tool_names(body)}",
        body,
    )
    report.assert_passed()
