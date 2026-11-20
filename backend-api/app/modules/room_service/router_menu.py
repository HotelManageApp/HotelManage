"""Menu for guests and kitchen, and room-service settings (spec/SPEC-room-service.md, API)."""

import uuid
from datetime import UTC, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.core.db import DbSession
from app.core.errors import Conflict, NotFound
from app.modules.room_service import hours
from app.modules.room_service.models import MenuCategory, MenuItem
from app.modules.staff_auth.deps import require_roles
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.stay_access.deps import CurrentStay
from app.modules.stay_access.schemas import StrictModel

Kitchen = Annotated[Staff, Depends(require_roles(StaffRole.KITCHEN))]
Reception = Annotated[Staff, Depends(require_roles(StaffRole.RECEPTION))]
KitchenOrReception = Annotated[
    Staff, Depends(require_roles(StaffRole.KITCHEN, StaffRole.RECEPTION))
]

router = APIRouter(tags=["menu"])


# ---------- guest ----------


class GuestCategory(BaseModel):
    code: str
    name: str


class GuestMenuItem(BaseModel):
    item_id: uuid.UUID
    name: str
    category: str
    price_vnd: int
    available: bool
    description: str | None


class GuestMenu(BaseModel):
    """Same shape as the chatbot tool `get_available_menu` (docs/chatbot-tools-spec.md §4.2)."""

    service_hours: str
    is_open_now: bool
    categories: list[GuestCategory]
    items: list[GuestMenuItem]


@router.get("/guest/menu", response_model=GuestMenu)
async def guest_menu(
    ctx: CurrentStay,
    request: Request,
    db: DbSession,
    category: Annotated[str | None, Query(max_length=40)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
) -> GuestMenu:
    lang = ctx.lang
    settings = await hours.load(db)
    stmt = (
        select(MenuItem, MenuCategory)
        .join(MenuCategory, MenuCategory.id == MenuItem.category_id)
        .where(MenuItem.is_archived.is_(False), MenuCategory.is_active.is_(True))
        .order_by(MenuCategory.sort_order, MenuCategory.code, MenuItem.sort_order, MenuItem.name_vi)
    )
    if category:
        stmt = stmt.where(MenuCategory.code == category.upper())
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                func.unaccent(MenuItem.name_vi).ilike(func.unaccent(pattern)),
                func.unaccent(MenuItem.name_en).ilike(func.unaccent(pattern)),
            )
        )
    rows = (await db.execute(stmt)).all()
    categories = {
        c.code: GuestCategory(code=c.code, name=c.name_en if lang == "en" else c.name_vi)
        for _, c in rows
    }
    return GuestMenu(
        service_hours=hours.label(settings.room_service_open, settings.room_service_close),
        is_open_now=hours.accepting_orders(
            settings, datetime.now(UTC), request.app.state.settings.hotel_timezone
        ),
        categories=list(categories.values()),
        items=[
            GuestMenuItem(
                item_id=item.id,
                name=item.name(lang),
                category=cat.code,
                price_vnd=item.price_vnd,
                available=item.available,
                description=item.description(lang),
            )
            for item, cat in rows
        ],
    )


# ---------- kitchen: categories ----------


class CategoryIn(StrictModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z_]+$")
    name_vi: str = Field(min_length=1, max_length=80)
    name_en: str = Field(min_length=1, max_length=80)
    sort_order: int = Field(default=0, ge=0, le=1000)


class CategoryPatch(StrictModel):
    name_vi: str | None = Field(default=None, min_length=1, max_length=80)
    name_en: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    is_active: bool | None = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    code: str
    name_vi: str
    name_en: str
    sort_order: int
    is_active: bool


@router.get("/menu/categories", response_model=list[CategoryOut])
async def list_categories(_: KitchenOrReception, db: DbSession) -> list[MenuCategory]:
    return list(await db.scalars(select(MenuCategory).order_by(MenuCategory.sort_order)))


@router.post("/menu/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(body: CategoryIn, _: Kitchen, db: DbSession) -> MenuCategory:
    code = body.code.upper()
    if await db.scalar(select(MenuCategory.id).where(MenuCategory.code == code)):
        raise Conflict(f"Nhóm món {code} đã tồn tại", code="CATEGORY_CODE_TAKEN")
    category = MenuCategory(**body.model_dump(exclude={"code"}), code=code)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


@router.patch("/menu/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID, body: CategoryPatch, _: Kitchen, db: DbSession
) -> MenuCategory:
    category = await db.get(MenuCategory, category_id)
    if category is None:
        raise NotFound("Không tìm thấy nhóm món")
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(category, field, value)
    await db.commit()
    await db.refresh(category)
    return category


# ---------- kitchen: items ----------


class ItemIn(StrictModel):
    category_id: uuid.UUID
    name_vi: str = Field(min_length=1, max_length=120)
    name_en: str = Field(min_length=1, max_length=120)
    description_vi: str | None = Field(default=None, max_length=500)
    description_en: str | None = Field(default=None, max_length=500)
    price_vnd: int = Field(ge=0, le=100_000_000)
    available: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)


class ItemPatch(StrictModel):
    category_id: uuid.UUID | None = None
    name_vi: str | None = Field(default=None, min_length=1, max_length=120)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    description_vi: str | None = Field(default=None, max_length=500)
    description_en: str | None = Field(default=None, max_length=500)
    price_vnd: int | None = Field(default=None, ge=0, le=100_000_000)
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    is_archived: bool | None = None


class Availability(StrictModel):
    available: bool


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category_id: uuid.UUID
    name_vi: str
    name_en: str
    description_vi: str | None
    description_en: str | None
    price_vnd: int
    available: bool
    is_archived: bool
    sort_order: int


async def _category_exists(db: DbSession, category_id: uuid.UUID) -> None:
    if await db.get(MenuCategory, category_id) is None:
        raise NotFound("Không tìm thấy nhóm món")


async def _item(db: DbSession, item_id: uuid.UUID) -> MenuItem:
    item = await db.get(MenuItem, item_id)
    if item is None:
        raise NotFound("Không tìm thấy món")
    return item


@router.get("/menu/items", response_model=list[ItemOut])
async def list_items(
    _: KitchenOrReception,
    db: DbSession,
    include_archived: Annotated[bool, Query()] = False,
) -> list[MenuItem]:
    stmt = select(MenuItem).order_by(MenuItem.sort_order, MenuItem.name_vi)
    if not include_archived:
        stmt = stmt.where(MenuItem.is_archived.is_(False))
    return list(await db.scalars(stmt))


@router.post("/menu/items", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_item(body: ItemIn, _: Kitchen, db: DbSession) -> MenuItem:
    await _category_exists(db, body.category_id)
    item = MenuItem(**body.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/menu/items/{item_id}", response_model=ItemOut)
async def update_item(item_id: uuid.UUID, body: ItemPatch, _: Kitchen, db: DbSession) -> MenuItem:
    item = await _item(db, item_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("category_id"):
        await _category_exists(db, changes["category_id"])
    for field, value in changes.items():
        if value is None and field not in {"description_vi", "description_en"}:
            continue
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/menu/items/{item_id}/availability", response_model=ItemOut)
async def set_availability(
    item_id: uuid.UUID, body: Availability, _: Kitchen, db: DbSession
) -> MenuItem:
    item = await _item(db, item_id)
    item.available = body.available
    await db.commit()
    await db.refresh(item)
    return item


# ---------- settings ----------


class RoomServiceSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    room_service_open: time
    room_service_close: time
    room_service_paused: bool
    default_prep_minutes: int


class PausePatch(StrictModel):
    paused: bool


class HoursPatch(StrictModel):
    open: time
    close: time
    default_prep_minutes: int = Field(default=25, ge=5, le=180)


@router.get("/settings/room-service", response_model=RoomServiceSettings)
async def get_settings(_: KitchenOrReception, db: DbSession) -> object:
    return await hours.load(db)


@router.patch("/settings/room-service", response_model=RoomServiceSettings)
async def pause(body: PausePatch, _: Kitchen, db: DbSession) -> object:
    settings = await hours.load(db)
    settings.room_service_paused = body.paused
    await db.commit()
    await db.refresh(settings)
    return settings


@router.patch("/settings/room-service/hours", response_model=RoomServiceSettings)
async def set_hours(body: HoursPatch, _: Reception, db: DbSession) -> object:
    settings = await hours.load(db)
    settings.room_service_open = body.open
    settings.room_service_close = body.close
    settings.default_prep_minutes = body.default_prep_minutes
    await db.commit()
    await db.refresh(settings)
    return settings
