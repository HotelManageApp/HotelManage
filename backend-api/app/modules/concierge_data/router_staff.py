"""Reception manages the knowledge base, nearby places and hotel info (SPEC-concierge-guide)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select

from app.core.db import DbSession
from app.core.errors import NotFound
from app.core.hotel_settings import HotelSettings, load_hotel_settings
from app.modules.concierge_data.models import KbEntry, KbTopic, NearbyPlace, PlaceCategory
from app.modules.concierge_data.schemas import (
    EntryIn,
    EntryOut,
    EntryPatch,
    HotelInfo,
    HotelInfoPatch,
    PlaceIn,
    PlaceOut,
    PlacePatch,
)
from app.modules.concierge_data.search import SearchResult, ToolTopic, search
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole

Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]

router = APIRouter(tags=["knowledge"])

# Fields a PATCH may set to null; any other null in a PATCH body means "leave as is".
NULLABLE_PLACE_FIELDS = {"description_vi", "description_en", "distance_km", "open_hours", "map_url"}


def _apply(target: KbEntry | NearbyPlace, changes: dict, nullable: set[str]) -> None:
    for field, value in changes.items():
        if value is None and field not in nullable:
            continue
        setattr(target, field, value)


# ---------- entries ----------


@router.get("/kb/entries", response_model=list[EntryOut])
async def list_entries(
    _: Reception, db: DbSession, topic: Annotated[KbTopic | None, Query()] = None
) -> list[KbEntry]:
    stmt = select(KbEntry).order_by(KbEntry.topic, KbEntry.title_vi)
    if topic is not None:
        stmt = stmt.where(KbEntry.topic == topic)
    return list(await db.scalars(stmt))


@router.post("/kb/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(body: EntryIn, staff: Reception, db: DbSession) -> KbEntry:
    entry = KbEntry(**body.model_dump(), updated_by=staff.id)
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def _entry(db: DbSession, entry_id: uuid.UUID) -> KbEntry:
    entry = await db.get(KbEntry, entry_id)
    if entry is None:
        raise NotFound("Không tìm thấy mục thông tin")
    return entry


@router.patch("/kb/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: uuid.UUID, body: EntryPatch, staff: Reception, db: DbSession
) -> KbEntry:
    entry = await _entry(db, entry_id)
    _apply(entry, body.model_dump(exclude_unset=True), set())
    entry.updated_by = staff.id
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/kb/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(entry_id: uuid.UUID, _: Reception, db: DbSession) -> Response:
    await db.delete(await _entry(db, entry_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- places ----------


@router.get("/kb/places", response_model=list[PlaceOut])
async def list_places(
    _: Reception, db: DbSession, category: Annotated[PlaceCategory | None, Query()] = None
) -> list[NearbyPlace]:
    stmt = select(NearbyPlace).order_by(NearbyPlace.category, NearbyPlace.name)
    if category is not None:
        stmt = stmt.where(NearbyPlace.category == category)
    return list(await db.scalars(stmt))


@router.post("/kb/places", response_model=PlaceOut, status_code=status.HTTP_201_CREATED)
async def create_place(body: PlaceIn, staff: Reception, db: DbSession) -> NearbyPlace:
    place = NearbyPlace(**body.model_dump(), updated_by=staff.id)
    db.add(place)
    await db.commit()
    await db.refresh(place)
    return place


async def _place(db: DbSession, place_id: uuid.UUID) -> NearbyPlace:
    place = await db.get(NearbyPlace, place_id)
    if place is None:
        raise NotFound("Không tìm thấy địa điểm")
    return place


@router.patch("/kb/places/{place_id}", response_model=PlaceOut)
async def update_place(
    place_id: uuid.UUID, body: PlacePatch, staff: Reception, db: DbSession
) -> NearbyPlace:
    place = await _place(db, place_id)
    _apply(place, body.model_dump(exclude_unset=True), NULLABLE_PLACE_FIELDS)
    place.updated_by = staff.id
    await db.commit()
    await db.refresh(place)
    return place


@router.delete("/kb/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_place(place_id: uuid.UUID, _: Reception, db: DbSession) -> Response:
    await db.delete(await _place(db, place_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- "try a question" and hotel info ----------


@router.get("/kb/search", response_model=SearchResult)
async def staff_search(
    _: Reception,
    db: DbSession,
    topic: ToolTopic,
    q: Annotated[str, Query(max_length=300)] = "",
    lang: Annotated[str, Query(pattern=r"^(vi|en)$")] = "vi",
) -> SearchResult:
    """What the bot would get for this question (no LLM call)."""
    return await search(db, topic, q, lang)


@router.get("/settings/hotel", response_model=HotelInfo)
async def get_hotel_info(_: Reception, db: DbSession) -> HotelSettings:
    return await load_hotel_settings(db)


@router.patch("/settings/hotel", response_model=HotelInfo)
async def update_hotel_info(body: HotelInfoPatch, _: Reception, db: DbSession) -> HotelSettings:
    settings = await load_hotel_settings(db)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, field, value)
    await db.commit()
    await db.refresh(settings)
    return settings
