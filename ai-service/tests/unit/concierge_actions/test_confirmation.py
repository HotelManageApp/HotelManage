"""Pending actions, signatures, payload hashes and the confirmation classifier (C2.5)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.concierge import confirmation as c
from app.core.backend_client import ChatLine
from app.llm.base import LLMError, LLMResponse
from app.llm.fake import FakeLLMClient

KEY = b"k" * 32
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
PHO = "11111111-1111-4111-8111-111111111111"
CAM = "22222222-2222-4222-8222-222222222222"
SUMMARY = {
    "items": [
        {
            "item_id": PHO,
            "name": "Phở bò",
            "quantity": 2,
            "unit_price_vnd": 65000,
            "line_total_vnd": 130000,
            "note": "ít cay",
        }
    ],
    "total_vnd": 130000,
    "order_note": "Gõ cửa nhẹ",
}


def order(*lines: tuple[str, int, str | None], note: str | None = None) -> dict[str, Any]:
    return c.normalize_order([{"item_id": i, "quantity": q, "note": n} for i, q, n in lines], note)


def pending(**overrides: Any) -> c.PendingAction:
    action = c.issue("FOOD_ORDER", order((PHO, 2, None)), SUMMARY, key=KEY, now=NOW)
    if not overrides:
        return action
    return c.PendingAction(**{**action.to_trace(), **overrides})


def reply_with(*entries: dict[str, Any]) -> ChatLine:
    return ChatLine(role="ASSISTANT", content="...", trace=list(entries))


# ---------- payload hash ----------


def test_the_hash_ignores_line_order_duplicates_case_and_spaces() -> None:
    a = order((PHO, 2, "ít cay"), (CAM, 1, None), note=" Gõ cửa ")
    b = order((CAM.upper(), 1, ""), (PHO, 1, " ít cay "), (PHO, 1, None), note="Gõ cửa")
    assert a == b
    assert c.payload_hash("FOOD_ORDER", a) == c.payload_hash("FOOD_ORDER", b)


@pytest.mark.parametrize(
    "other",
    [
        order((PHO, 3, "ít cay"), (CAM, 1, None), note="Gõ cửa"),
        order((PHO, 2, "ít cay"), note="Gõ cửa"),
        order((PHO, 2, "nhiều cay"), (CAM, 1, None), note="Gõ cửa"),
        order((PHO, 2, "ít cay"), (CAM, 1, None)),
    ],
    ids=["quantity", "dish-removed", "line-note", "order-note"],
)
def test_any_change_changes_the_hash(other: dict[str, Any]) -> None:
    base = order((PHO, 2, "ít cay"), (CAM, 1, None), note="Gõ cửa")
    assert c.payload_hash("FOOD_ORDER", base) != c.payload_hash("FOOD_ORDER", other)


def test_the_kind_is_part_of_the_hash() -> None:
    assert c.payload_hash("FOOD_ORDER", {}) != c.payload_hash("CHECKOUT", {})


# ---------- signature and expiry ----------


def test_a_signed_action_verifies_and_round_trips_through_the_trace() -> None:
    action = pending()
    assert len(action.id) == 32 and action.sig
    assert action.expires_at == (NOW + timedelta(minutes=10)).isoformat()
    assert c.verify(action.to_trace(), key=KEY, now=NOW) == action


@pytest.mark.parametrize(
    "change",
    [
        {"payload_hash": "0" * 64},
        {"summary": {**SUMMARY, "total_vnd": 1}},
        {"expires_at": (NOW + timedelta(days=1)).isoformat()},
        {"kind": "CHECKOUT"},
        {"id": "f" * 32},
        {"sig": "0" * 64},
    ],
    ids=["hash", "summary", "expiry", "kind", "id", "signature"],
)
def test_any_tampering_breaks_the_signature(change: dict[str, Any]) -> None:
    assert c.verify({**pending().to_trace(), **change}, key=KEY, now=NOW) is None


def test_another_key_or_expiry_refuses_it() -> None:
    raw = pending().to_trace()
    assert c.verify(raw, key=b"x" * 32, now=NOW) is None
    assert c.verify(raw, key=KEY, now=NOW + timedelta(minutes=10)) is None
    assert c.verify(raw, key=KEY, now=NOW + timedelta(minutes=9, seconds=59)) is not None


@pytest.mark.parametrize(
    "raw",
    [None, "x", {}, {"id": "a"}, {**{"expires_at": "soon"}, **{"id": "a"}}],
    ids=["none", "string", "empty", "partial", "bad-date"],
)
def test_malformed_actions_are_refused(raw: Any) -> None:
    assert c.verify(raw, key=KEY, now=NOW) is None


def test_a_well_signed_unknown_kind_is_refused() -> None:
    action = c.issue("REFUND", {}, {}, key=KEY, now=NOW)
    assert c.verify(action.to_trace(), key=KEY, now=NOW) is None


def test_bad_date_in_a_full_record_is_refused() -> None:
    assert c.verify({**pending().to_trace(), "expires_at": "soon"}, key=KEY, now=NOW) is None


# ---------- finding the pending action in the history ----------


def test_only_the_previous_bot_reply_counts() -> None:
    action = pending()
    entry = {"pending_action": action.to_trace()}
    found = c.find_pending(
        [ChatLine("GUEST", "2 phở"), reply_with({"tool": "x"}, entry)], key=KEY, now=NOW
    )
    assert found == action
    older = [reply_with(entry), ChatLine("GUEST", "à mà thôi"), reply_with({"tool": "y"})]
    assert c.find_pending(older, key=KEY, now=NOW) is None
    assert c.find_pending([ChatLine("GUEST", "hi")], key=KEY, now=NOW) is None


def test_a_used_or_cancelled_action_is_not_pending() -> None:
    action = pending()
    entry = {"pending_action": action.to_trace()}
    for marker in ({"executed_action": action.id}, {"cancelled_action": action.id}):
        history = [reply_with(marker), reply_with(entry)]
        assert c.find_pending(history, key=KEY, now=NOW) is None


def test_a_trace_that_is_one_dict_or_junk_is_handled() -> None:
    action = pending()
    as_dict = ChatLine("ASSISTANT", "x", trace={"pending_action": action.to_trace()})
    assert c.find_pending([as_dict], key=KEY, now=NOW) == action
    junk = ChatLine("ASSISTANT", "x", trace="nope")
    assert c.find_pending([junk], key=KEY, now=NOW) is None


def test_a_forged_action_in_the_history_is_ignored() -> None:
    forged = {**pending().to_trace(), "sig": "f" * 64}
    assert c.find_pending([reply_with({"pending_action": forged})], key=KEY, now=NOW) is None


# ---------- is it a confirmation? ----------


@pytest.mark.parametrize(
    "text",
    [
        "ok",
        "OK ạ",
        "Đúng rồi",
        "đúng rồi nhé",
        "Xác nhận",
        "đồng ý",
        "Ok đặt đi",
        "có",
        "yes",
        "Yes please!",
        "confirm",
        "Gửi yêu cầu",
    ],
)
def test_confirmation_phrases(text: str) -> None:
    assert c.classify_phrase(text) == "CONFIRM"


@pytest.mark.parametrize("text", ["hủy", "Thôi", "không đặt nữa", "cancel", "no", "Không"])
def test_cancel_phrases(text: str) -> None:
    assert c.classify_phrase(text) == "CANCEL"


@pytest.mark.parametrize(
    "text",
    [
        "không đúng",
        "chưa",
        "đúng nhưng thêm 1 trà",
        "đừng đặt",
        "ok nhưng bớt 1 phở",
        "đổi sang 1 phở",
        "not yet",
        "ok, mà phở có cay không vậy, nếu không cay thì đặt giúp tôi",
        "giá bao nhiêu",
        "...",
    ],
)
def test_anything_else_goes_to_the_model(text: str) -> None:
    assert c.classify_phrase(text) is None


async def test_the_model_decides_unclear_replies_and_errors_never_confirm() -> None:
    llm = FakeLLMClient()
    llm.queue(
        LLMResponse(structured={"label": "CHANGE"}),
        LLMResponse(structured={"label": "MAYBE"}),
        LLMError("down"),
        LLMResponse(structured={"label": "CONFIRM"}),
    )
    assert await c.classify("đổi sang 1 phở", llm) == "CHANGE"
    assert await c.classify("hmm thế nào nhỉ", llm) == "OTHER"
    assert await c.classify("ừm được rồi đặt giúp", llm) == "OTHER"
    assert await c.classify("vâng đặt giúp tôi luôn nha bạn ơi", llm) == "CONFIRM"
    request = llm.requests[0]
    assert request.response_schema == c.CLASSIFIER_SCHEMA and request.temperature == 0.0
    assert await c.classify("ok", llm) == "CONFIRM"
    assert len(llm.requests) == 4, "a known phrase needs no model call"


# ---------- the summary the guest sees ----------


def test_the_order_summary_uses_backend_numbers() -> None:
    text = c.render(pending(), "vi")
    assert text.splitlines() == [
        "Tóm tắt đơn của Quý khách:",
        "- Phở bò × 2: 65.000đ × 2 = 130.000đ",
        "  Ghi chú: ít cay",
        "Ghi chú cho đơn: Gõ cửa nhẹ",
        "Tổng cộng: 130.000đ",
        "Quý khách xác nhận đặt đơn này chứ?",
    ]
    assert "130,000 VND" in c.render(pending(), "en")
    assert c.render(pending(), "ko-KR") == c.render(pending(), "en")


def test_the_checkout_summary() -> None:
    summary = {
        "lines": [
            {"type": "ROOM", "description": "Tiền phòng", "amount_vnd": 1200000},
            {"type": "DISCOUNT", "description": "Khách quen", "amount_vnd": 50000},
        ],
        "total_vnd": 1150000,
        "open_orders": 1,
    }
    action = c.issue("CHECKOUT", {}, summary, key=KEY, now=NOW)
    text = c.render(action, "vi")
    assert "- Tiền phòng: 1.200.000đ" in text
    assert "- Khách quen: −50.000đ" in text
    assert "Còn 1 đơn đồ ăn đang xử lý" in text
    assert text.endswith("Quý khách xác nhận gửi yêu cầu trả phòng chứ?")
    no_open = c.issue("CHECKOUT", {}, {**summary, "open_orders": 0}, key=KEY, now=NOW)
    assert "đang xử lý" not in c.render(no_open, "vi")
