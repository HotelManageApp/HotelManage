"""`python -m app.cli seed-kb --from-file seeds/kb.example.yaml` (SPEC-concierge-guide).

Loads hotel info, knowledge-base entries and nearby places for a trial hotel. Every row goes
through the same validation as the reception API (bilingual fields, map link allow-list).
Existing rows (same topic + Vietnamese title, or same category + name) are left untouched, so the
command can be re-run safely.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.hotel_settings import load_hotel_settings
from app.modules.concierge_data.models import KbEntry, NearbyPlace
from app.modules.concierge_data.schemas import EntryIn, HotelInfoPatch, PlaceIn


class SeedError(Exception):
    pass


@dataclass
class SeedReport:
    entries_created: int = 0
    entries_skipped: int = 0
    places_created: int = 0
    places_skipped: int = 0
    hotel_updated: bool = False


def _rows(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = data.get(key) or []
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise SeedError(f"'{key}' must be a list of mappings")
    return rows


def _valid[M: BaseModel](model: type[M], row: dict[str, Any], where: str) -> M:
    try:
        return model.model_validate(row)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"])
        raise SeedError(f"{where}: {field}: {first['msg']}") from None


async def seed_kb(db: AsyncSession, path: Path) -> SeedReport:
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        raise SeedError(f"file not found: {path}") from None
    try:
        data = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        raise SeedError(f"not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise SeedError("the file must be a mapping with hotel / entries / places")

    report = SeedReport()
    if data.get("hotel"):
        info = _valid(HotelInfoPatch, data["hotel"], "hotel")
        settings = await load_hotel_settings(db)
        for field, value in info.model_dump(exclude_none=True).items():
            setattr(settings, field, value)
        report.hotel_updated = True

    for index, row in enumerate(_rows(data, "entries"), start=1):
        entry = _valid(EntryIn, row, f"entries[{index}]")
        exists = await db.scalar(
            select(KbEntry.id).where(
                KbEntry.topic == entry.topic, KbEntry.title_vi == entry.title_vi
            )
        )
        if exists:
            report.entries_skipped += 1
            continue
        db.add(KbEntry(**entry.model_dump()))
        report.entries_created += 1

    for index, row in enumerate(_rows(data, "places"), start=1):
        place = _valid(PlaceIn, row, f"places[{index}]")
        exists = await db.scalar(
            select(NearbyPlace.id).where(
                NearbyPlace.category == place.category, NearbyPlace.name == place.name
            )
        )
        if exists:
            report.places_skipped += 1
            continue
        db.add(NearbyPlace(**place.model_dump()))
        report.places_created += 1

    await db.commit()
    return report
