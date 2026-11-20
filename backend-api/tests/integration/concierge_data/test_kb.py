"""Knowledge base, nearby places, search and hotel info (SPEC-concierge-guide, T37)."""

import re
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.modules.concierge_data.models import KbEntry, NearbyPlace
from app.modules.concierge_data.search import strip_accents, to_tsquery_text
from app.modules.staff_auth.models import StaffRole
from tests.conftest import make_settings
from tests.factories import create_staff, staff_headers
from tests.guests import Guest, check_in_guest

ENTRIES = "/api/v1/kb/entries"
PLACES = "/api/v1/kb/places"
GUEST_SEARCH = "/api/v1/guest/kb/search"
SEEDS = Path(__file__).resolve().parents[3] / "seeds"

BREAKFAST = {
    "topic": "BREAKFAST",
    "title_vi": "Giờ ăn sáng",
    "title_en": "Breakfast hours",
    "content_vi": "Bữa sáng 06:30–09:30 tại tầng 1.",
    "content_en": "Breakfast 06:30–09:30 on the ground floor.",
}
POOL = {
    "topic": "FACILITIES",
    "title_vi": "Hồ bơi",
    "title_en": "Swimming pool",
    "content_vi": "Hồ bơi tầng thượng mở 06:00–21:00.",
    "content_en": "Rooftop pool open 06:00–21:00.",
}
MARKET = {
    "category": "ATTRACTION",
    "name": "Chợ Bến Thành",
    "description_vi": "Chợ truyền thống",
    "description_en": "Traditional market",
    "distance_km": 1.2,
    "open_hours": "06:00–18:00",
    "map_url": "https://maps.google.com/?q=Ben+Thanh",
}


@pytest.fixture
async def guest(client: httpx.AsyncClient, db: AsyncSession) -> Guest:
    return await check_in_guest(client, db)


async def _add(client: httpx.AsyncClient, url: str, body: dict, reception: dict) -> dict:
    response = await client.post(url, json=body, headers=reception)
    assert response.status_code == 201, response.text
    return response.json()


async def _search(client: httpx.AsyncClient, guest: Guest, **params: str) -> dict:
    response = await client.get(GUEST_SEARCH, params=params, headers=guest.headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- pure helpers ----------


def test_accents_fold_like_the_database() -> None:
    assert strip_accents("Mấy giờ ĂN SÁNG ở Đà Nẵng?") == "May gio AN SANG o Da Nang?"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Mấy giờ ăn sáng?", "may | gio | an | sang:*"),
        ("wifi & password | !x", "wifi:* | password:*"),  # tsquery operators never pass through
        ("a ? !", None),
        ("Có không?", None),  # only question words
        ("sân golf", "san | golf:*"),  # short words match exactly: "san" is not "sang"
        (
            "Chợ ở đâu? Thẻ phòng? Đồ ăn tối",
            "cho | dau | the | phong:* | do | an | toi",
        ),  # not stopwords
    ],
)
def test_to_tsquery_text(query: str, expected: str | None) -> None:
    assert to_tsquery_text(query) == expected


# ---------- guest search ----------


async def test_breakfast_question_finds_the_entry_with_or_without_accents(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(client, ENTRIES, BREAKFAST, guest.reception)
    await _add(client, ENTRIES, POOL, guest.reception)

    for question in ("Mấy giờ ăn sáng?", "an sang luc may gio"):
        data = await _search(client, guest, topic="OTHER", q=question)
        assert data["found"] is True
        assert data["entries"][0]["title"] == "Giờ ăn sáng"
        assert data["entries"][0]["content"] == BREAKFAST["content_vi"]
        assert data["entries"][0]["source"] == "hotel_kb"


async def test_answers_in_the_requested_language(client: httpx.AsyncClient, guest: Guest) -> None:
    await _add(client, ENTRIES, BREAKFAST, guest.reception)
    en = await _search(client, guest, topic="BREAKFAST", q="breakfast time", lang="en")
    assert en["entries"][0]["content"] == BREAKFAST["content_en"]
    # Languages without a translation get the English text (the bot translates it).
    ko = await _search(client, guest, topic="BREAKFAST", q="아침", lang="ko")
    assert ko["entries"][0]["title"] == "Breakfast hours"
    # Without lang: the session language (vi).
    vi = await _search(client, guest, topic="BREAKFAST", q="sáng")
    assert vi["entries"][0]["title"] == "Giờ ăn sáng"


async def test_falls_back_to_the_topic_when_words_do_not_match(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(client, ENTRIES, BREAKFAST, guest.reception)
    await _add(client, ENTRIES, POOL, guest.reception)
    data = await _search(client, guest, topic="BREAKFAST", q="buffet có món chay không")
    assert [e["title"] for e in data["entries"]] == ["Giờ ăn sáng"]
    # OTHER has no topic to fall back to: nothing found, the bot says it has no information.
    nothing = await _search(client, guest, topic="OTHER", q="sân golf")
    assert nothing == {"found": False, "entries": [], "places": []}


async def test_unpublished_entries_and_places_are_never_returned(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(client, ENTRIES, {**BREAKFAST, "is_published": False}, guest.reception)
    await _add(client, PLACES, {**MARKET, "is_published": False}, guest.reception)
    assert (await _search(client, guest, topic="BREAKFAST", q="ăn sáng"))["found"] is False
    assert (await _search(client, guest, topic="ATTRACTIONS", q="chợ"))["found"] is False
    assert (await _search(client, guest, topic="OTHER", q="ăn sáng chợ"))["found"] is False


async def test_places_by_category_with_the_tool_shape(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(client, PLACES, MARKET, guest.reception)
    await _add(
        client,
        PLACES,
        {"category": "FOOD_NEARBY", "name": "Phở Hòa", "distance_km": 0.6},
        guest.reception,
    )
    await _add(client, ENTRIES, BREAKFAST, guest.reception)

    attractions = await _search(client, guest, topic="ATTRACTIONS", q="cho ben thanh")
    assert attractions["entries"] == []
    assert attractions["places"] == [
        {
            "name": "Chợ Bến Thành",
            "category": "ATTRACTION",
            "distance_km": 1.2,
            "open_hours": "06:00–18:00",
            "note": "Chợ truyền thống",
            "map_url": "https://maps.google.com/?q=Ben+Thanh",
        }
    ]
    # Topic fallback for places: closest first.
    food = await _search(client, guest, topic="FOOD_NEARBY", q="quán nào ngon")
    assert [p["name"] for p in food["places"]] == ["Phở Hòa"]


async def test_transport_covers_the_desk_and_nearby_stations(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(
        client,
        ENTRIES,
        {**POOL, "topic": "TRANSPORT", "title_vi": "Xe sân bay", "title_en": "Airport car"},
        guest.reception,
    )
    await _add(
        client, PLACES, {"category": "TRANSPORT", "name": "Ga Metro Bến Thành"}, guest.reception
    )
    data = await _search(client, guest, topic="TRANSPORT", q="đi sân bay")
    assert [e["title"] for e in data["entries"]] == ["Xe sân bay"]
    assert [p["name"] for p in data["places"]] == ["Ga Metro Bến Thành"]


async def test_limits_five_entries(client: httpx.AsyncClient, guest: Guest) -> None:
    for i in range(7):
        await _add(client, ENTRIES, {**BREAKFAST, "title_vi": f"Ăn sáng {i}"}, guest.reception)
    data = await _search(client, guest, topic="BREAKFAST", q="ăn sáng")
    assert len(data["entries"]) == 5


async def test_guest_search_needs_a_guest_token_and_a_known_topic(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    assert (await client.get(GUEST_SEARCH, params={"topic": "OTHER"})).status_code == 401
    staff = staff_headers(await create_staff(db, email="k@h.test", role=StaffRole.KITCHEN))
    assert (
        await client.get(GUEST_SEARCH, params={"topic": "OTHER"}, headers=staff)
    ).status_code == 401
    bad = await client.get(GUEST_SEARCH, params={"topic": "ROOMS"}, headers=guest.headers)
    assert bad.status_code == 400


async def test_search_reflects_an_edit_at_once(client: httpx.AsyncClient, guest: Guest) -> None:
    """SC 1: reception changes the breakfast hours -> the next answer uses the new hours."""
    entry = await _add(client, ENTRIES, BREAKFAST, guest.reception)
    patched = await client.patch(
        f"{ENTRIES}/{entry['id']}",
        json={"content_vi": "Bữa sáng 07:00–10:00 tại tầng 1."},
        headers=guest.reception,
    )
    assert patched.status_code == 200
    data = await _search(client, guest, topic="BREAKFAST", q="ăn sáng")
    assert data["entries"][0]["content"] == "Bữa sáng 07:00–10:00 tại tầng 1."


# ---------- reception CRUD ----------


async def test_reception_manages_entries(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest
) -> None:
    rx = guest.reception
    entry = await _add(client, ENTRIES, BREAKFAST, rx)
    await _add(client, ENTRIES, POOL, rx)
    listed = (await client.get(ENTRIES, params={"topic": "BREAKFAST"}, headers=rx)).json()
    assert [e["id"] for e in listed] == [entry["id"]]

    hidden = await client.patch(
        f"{ENTRIES}/{entry['id']}", json={"is_published": False, "title_vi": None}, headers=rx
    )
    assert hidden.json()["is_published"] is False
    assert hidden.json()["title_vi"] == "Giờ ăn sáng", "null means unchanged for required fields"
    stored = await db.get(KbEntry, uuid.UUID(entry["id"]))
    assert stored is not None and stored.updated_by is not None

    assert (await client.delete(f"{ENTRIES}/{entry['id']}", headers=rx)).status_code == 204
    assert (await client.delete(f"{ENTRIES}/{entry['id']}", headers=rx)).status_code == 404
    assert (await client.patch(f"{ENTRIES}/{entry['id']}", json={}, headers=rx)).status_code == 404


async def test_reception_manages_places_and_can_clear_optional_fields(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    rx = guest.reception
    place = await _add(client, PLACES, MARKET, rx)
    cleared = await client.patch(
        f"{PLACES}/{place['id']}", json={"map_url": None, "distance_km": None}, headers=rx
    )
    assert cleared.status_code == 200
    assert cleared.json()["map_url"] is None and cleared.json()["distance_km"] is None
    listed = (await client.get(PLACES, params={"category": "ATTRACTION"}, headers=rx)).json()
    assert [p["name"] for p in listed] == ["Chợ Bến Thành"]
    assert (await client.delete(f"{PLACES}/{place['id']}", headers=rx)).status_code == 204
    assert (await client.get(PLACES, headers=rx)).json() == []


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/?q=market",
        "http://maps.google.com/?q=x",  # not https
        "https://maps.google.com.evil.io/x",
        "https://maps.google.com/ x",
        "javascript:alert(1)",
    ],
)
async def test_map_links_outside_the_allow_list_are_400(
    client: httpx.AsyncClient, guest: Guest, url: str
) -> None:
    response = await client.post(PLACES, json={**MARKET, "map_url": url}, headers=guest.reception)
    assert response.status_code == 400


@pytest.mark.parametrize(
    "body",
    [
        {**BREAKFAST, "content_vi": "x" * 2001},
        {**BREAKFAST, "title_en": ""},
        {**BREAKFAST, "topic": "ROOMS"},
        {**BREAKFAST, "room_id": "101"},  # unknown fields are refused
        {k: v for k, v in BREAKFAST.items() if k != "content_en"},  # both languages required
    ],
)
async def test_invalid_entries_are_400(client: httpx.AsyncClient, guest: Guest, body: dict) -> None:
    assert (await client.post(ENTRIES, json=body, headers=guest.reception)).status_code == 400


@pytest.mark.parametrize("role", [StaffRole.KITCHEN, StaffRole.HOUSEKEEPING])
async def test_only_reception_edits_knowledge(
    client: httpx.AsyncClient, db: AsyncSession, guest: Guest, role: StaffRole
) -> None:
    entry = await _add(client, ENTRIES, BREAKFAST, guest.reception)
    other = staff_headers(await create_staff(db, email=f"{role.value}@h.test", role=role))
    calls = [
        client.get(ENTRIES, headers=other),
        client.post(ENTRIES, json=POOL, headers=other),
        client.patch(f"{ENTRIES}/{entry['id']}", json={"title_vi": "x"}, headers=other),
        client.delete(f"{ENTRIES}/{entry['id']}", headers=other),
        client.post(PLACES, json=MARKET, headers=other),
        client.get("/api/v1/kb/search", params={"topic": "OTHER"}, headers=other),
        client.patch("/api/v1/settings/hotel", json={"chat_enabled": False}, headers=other),
    ]
    for call in calls:
        assert (await call).status_code == 403
    assert (await client.post(ENTRIES, json=POOL, headers=guest.headers)).status_code == 401, (
        "a guest token is not a staff token"
    )


async def test_staff_try_a_question_matches_the_guest_search(
    client: httpx.AsyncClient, guest: Guest
) -> None:
    await _add(client, ENTRIES, BREAKFAST, guest.reception)
    staff = await client.get(
        "/api/v1/kb/search", params={"topic": "OTHER", "q": "ăn sáng"}, headers=guest.reception
    )
    assert staff.status_code == 200
    assert staff.json() == await _search(client, guest, topic="OTHER", q="ăn sáng")


# ---------- hotel info ----------


async def test_hotel_info_defaults_and_update(client: httpx.AsyncClient, guest: Guest) -> None:
    rx = guest.reception
    assert (await client.get("/api/v1/settings/hotel", headers=rx)).json() == {
        "hotel_name": "Hotel",
        "reception_phone": "",
        "default_lang": "vi",
        "chat_enabled": True,
    }
    updated = await client.patch(
        "/api/v1/settings/hotel",
        json={"hotel_name": "Khách sạn Hoa Sen", "reception_phone": "+84 28 3822 1234"},
        headers=rx,
    )
    assert updated.status_code == 200
    assert updated.json()["hotel_name"] == "Khách sạn Hoa Sen"
    assert updated.json()["chat_enabled"] is True
    for bad in (
        {"reception_phone": "call me"},
        {"default_lang": "fr"},
        {"hotel_name": ""},
        {"room_service_paused": True},  # other settings have their own endpoints
    ):
        assert (
            await client.patch("/api/v1/settings/hotel", json=bad, headers=rx)
        ).status_code == 400


# ---------- seed-kb ----------


async def test_seed_kb_loads_the_example_once(db: AsyncSession) -> None:
    out: list[str] = []
    argv = ["seed-kb", "--from-file", str(SEEDS / "kb.example.yaml")]
    await cli.run(argv, settings=make_settings(), out=out.append)
    await cli.run(argv, settings=make_settings(), out=out.append)
    assert out[0].startswith("entries created: 7, already existed: 0; places created: 5")
    assert out[0].endswith("hotel info updated")
    assert out[1].startswith("entries created: 0, already existed: 7; places created: 0")
    assert await db.scalar(select(func.count()).select_from(KbEntry)) == 7
    assert await db.scalar(select(func.count()).select_from(NearbyPlace)) == 5


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("entries: [{topic: BREAKFAST}]", "entries[1]: title_vi"),
        (
            "places: [{category: ATTRACTION, name: X, map_url: 'https://x.io'}]",
            "places[1]: map_url",
        ),
        ("entries: 3", "'entries' must be a list"),
        ("- just\n- a list", "must be a mapping"),
        ("entries: [", "not valid YAML"),
    ],
)
async def test_seed_kb_reports_bad_files(
    db: AsyncSession, tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "kb.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(cli.CliError, match=re.escape(message)):
        await cli.run(["seed-kb", "--from-file", str(path)], settings=make_settings())
    with pytest.raises(cli.CliError, match="file not found"):
        await cli.run(
            ["seed-kb", "--from-file", str(tmp_path / "missing.yaml")], settings=make_settings()
        )
