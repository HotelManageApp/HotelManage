import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.concierge_data.models import KbTopic, PlaceCategory
from app.modules.stay_access.schemas import StrictModel

# Map links the guest app may open (SPEC-concierge-guide "Dữ liệu"): nothing else, so a KB entry
# can never send guests to an arbitrary site.
MAP_URL_PREFIXES = ("https://maps.google.com/", "https://maps.app.goo.gl/")

Title = Field(min_length=1, max_length=200)
Content = Field(min_length=1, max_length=2000)
Description = Field(default=None, max_length=1000)


def _check_map_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not value.startswith(MAP_URL_PREFIXES) or any(c.isspace() for c in value):
        raise ValueError(
            "map_url must be a https://maps.google.com/ or https://maps.app.goo.gl/ link"
        )
    return value


class EntryIn(StrictModel):
    topic: KbTopic
    title_vi: str = Title
    title_en: str = Title
    content_vi: str = Content
    content_en: str = Content
    is_published: bool = True


class EntryPatch(StrictModel):
    topic: KbTopic | None = None
    title_vi: str | None = Field(default=None, min_length=1, max_length=200)
    title_en: str | None = Field(default=None, min_length=1, max_length=200)
    content_vi: str | None = Field(default=None, min_length=1, max_length=2000)
    content_en: str | None = Field(default=None, min_length=1, max_length=2000)
    is_published: bool | None = None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    topic: KbTopic
    title_vi: str
    title_en: str
    content_vi: str
    content_en: str
    is_published: bool
    updated_at: datetime


class PlaceIn(StrictModel):
    category: PlaceCategory
    name: str = Title
    description_vi: str | None = Description
    description_en: str | None = Description
    distance_km: float | None = Field(default=None, ge=0, le=999)
    open_hours: str | None = Field(default=None, max_length=100)
    map_url: str | None = Field(default=None, max_length=500)
    is_published: bool = True

    _map = field_validator("map_url")(_check_map_url)


class PlacePatch(StrictModel):
    category: PlaceCategory | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description_vi: str | None = Description
    description_en: str | None = Description
    distance_km: float | None = Field(default=None, ge=0, le=999)
    open_hours: str | None = Field(default=None, max_length=100)
    map_url: str | None = Field(default=None, max_length=500)
    is_published: bool | None = None

    _map = field_validator("map_url")(_check_map_url)


class PlaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category: PlaceCategory
    name: str
    description_vi: str | None
    description_en: str | None
    distance_km: float | None
    open_hours: str | None
    map_url: str | None
    is_published: bool
    updated_at: datetime


class HotelInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    hotel_name: str
    reception_phone: str
    default_lang: str
    chat_enabled: bool


class HotelInfoPatch(StrictModel):
    hotel_name: str | None = Field(default=None, min_length=1, max_length=120)
    reception_phone: str | None = Field(default=None, pattern=r"^[0-9+() .-]{3,20}$")
    default_lang: Literal["vi", "en"] | None = None
    chat_enabled: bool | None = None
