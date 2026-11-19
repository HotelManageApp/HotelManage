import pytest

from app.concierge.grounding import Fact, extract, has_facts, unsupported
from app.concierge.orchestrator import fallback_reply, suggested


@pytest.mark.parametrize(
    ("text", "facts"),
    [
        ("Bữa sáng 06:30–09:30 tại tầng 1.", {"time:06:30", "time:09:30"}),
        ("Breakfast is 6h30 to 9h.", {"time:06:30", "time:09:00"}),
        ("Hồ bơi mở 6 giờ sáng đến 21:00", {"time:06:00", "time:21:00"}),
        ("Phở 65.000đ, cà phê 35k, nước 20 nghìn", {"price:65000", "price:35000", "price:20000"}),
        ("Total 130,000 VND", {"price:130000"}),
        ("Chợ cách 1,2 km", {"distance:1200"}),
        ("about 800 m away", {"distance:800"}),
        ("Gọi Lễ tân 028 3822 1234", {"phone:02838221234"}),
        ("Call +84 90 123 4567", {"phone:84901234567"}),
        ("Phòng 101 tầng 2, Wi-Fi 24/7", set()),
        ("Đi bộ khoảng 15 phút", set()),
    ],
)
def test_extract(text: str, facts: set[str]) -> None:
    assert {str(f) for f in extract(text)} == facts
    assert has_facts(text) is bool(facts)


def test_facts_found_in_the_sources_in_another_format_are_grounded() -> None:
    sources = [
        '{"content": "Bữa sáng 06:30–09:30", "price_vnd": 65000}',
        '{"places": [{"name": "Chợ", "distance_km": 1.2}]}',
        "028 3822 1234",
    ]
    reply = "Bữa sáng 6h30 đến 9h30, phở 65k, chợ cách 1.2km; gọi 02838221234."
    assert unsupported(reply, sources) == set()


def test_invented_facts_are_reported() -> None:
    sources = ['{"content": "Bữa sáng 06:30–09:30"}']
    assert unsupported("Bữa sáng 7:00–10:00", sources) == {
        Fact("time", "07:00"),
        Fact("time", "10:00"),
    }
    assert unsupported("Phòng tổng thống 5.000.000đ", sources) == {Fact("price", "5000000")}
    assert unsupported("Không có giờ cụ thể", sources) == set()


def test_suggested_actions_are_filtered() -> None:
    assert suggested(["ROOM_SERVICE", "DELETE_ALL", "ROOM_SERVICE", "CALL_RECEPTION", 3]) == [
        {"type": "OPEN_SCREEN", "target": "ROOM_SERVICE"},
        {"type": "CALL", "target": "CALL_RECEPTION"},
    ]
    assert suggested("ROOM_SERVICE") == []


def test_fallback_reply_by_language() -> None:
    assert "Lễ tân (028 1234)" in fallback_reply("vi", "028 1234")
    assert fallback_reply("ko", "").endswith("Please contact reception for help.")
