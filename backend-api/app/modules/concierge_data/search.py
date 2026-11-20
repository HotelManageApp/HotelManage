"""Knowledge-base search behind the chatbot tool `get_hotel_info_and_guide`
(docs/chatbot-tools-spec.md §4.1, spec/SPEC-concierge-guide.md "API backend").

- The tool topic picks the tables: ATTRACTIONS / FOOD_NEARBY / TRANSPORT look at nearby places,
  the hotel topics at kb_entry, OTHER at both. TRANSPORT also covers the hotel's own transport
  entries (shuttle, taxi desk), which live in kb_entry.
- Guests write sentences ("Mấy giờ ăn sáng?"), so the query is the OR of the accent-free words
  (prefix match), ranked by ts_rank; titles weigh more than content.
- Nothing matches but the topic has entries -> the topic's entries, so the bot still answers
  from the hotel's data. Only published rows are ever returned.
"""

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import Select, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.concierge_data.models import KbEntry, KbTopic, NearbyPlace, PlaceCategory

MAX_ENTRIES = 5
MAX_PLACES = 8
MAX_TERMS = 12


class ToolTopic(StrEnum):
    """The `topic` enum of the chatbot tool."""

    BREAKFAST = "BREAKFAST"
    FACILITIES = "FACILITIES"
    SERVICES = "SERVICES"
    POLICIES = "POLICIES"
    WIFI = "WIFI"
    TRANSPORT = "TRANSPORT"
    ATTRACTIONS = "ATTRACTIONS"
    FOOD_NEARBY = "FOOD_NEARBY"
    OTHER = "OTHER"


@dataclass(frozen=True)
class Scope:
    kb_topic: KbTopic | None  # None = every topic
    place_category: PlaceCategory | None
    search_kb: bool
    search_places: bool


SCOPES: dict[ToolTopic, Scope] = {
    **{
        ToolTopic(t.value): Scope(t, None, search_kb=True, search_places=False)
        for t in (
            KbTopic.BREAKFAST,
            KbTopic.FACILITIES,
            KbTopic.SERVICES,
            KbTopic.POLICIES,
            KbTopic.WIFI,
        )
    },
    ToolTopic.TRANSPORT: Scope(
        KbTopic.TRANSPORT, PlaceCategory.TRANSPORT, search_kb=True, search_places=True
    ),
    ToolTopic.ATTRACTIONS: Scope(
        None, PlaceCategory.ATTRACTION, search_kb=False, search_places=True
    ),
    ToolTopic.FOOD_NEARBY: Scope(
        None, PlaceCategory.FOOD_NEARBY, search_kb=False, search_places=True
    ),
    ToolTopic.OTHER: Scope(None, None, search_kb=True, search_places=True),
}


class KbHit(BaseModel):
    id: str
    title: str
    content: str
    source: str = "hotel_kb"
    updated_at: str  # date, ISO


class PlaceHit(BaseModel):
    name: str
    category: str
    distance_km: float | None
    open_hours: str | None
    note: str | None
    map_url: str | None


class SearchResult(BaseModel):
    """The `data` of the tool output (§4.1)."""

    found: bool
    entries: list[KbHit]
    places: list[PlaceHit]


def strip_accents(value: str) -> str:
    """ "Ăn sáng ở đâu?" -> "an sang o dau?" (same folding as f_unaccent in the database)."""
    value = value.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Question words that would match almost any entry ("có ... không?", "what ... is"). Accents are
# folded first, so a word may only be here if no useful Vietnamese word folds to it:
# "an" is ăn (eat), "cho" chợ (market), "the" thẻ (card), "toi" tối, "may" máy, "cua" cua (crab),
# "chua" canh chua, "do" đồ, "dau" đau, "ban" bàn — all kept searchable.
STOPWORDS = frozenset(
    "co khong la gi nao bao nhieu duoc thi va hay nhe oi vay nhi khi nay kia roi minh "
    "is are of to in on at for and or what where when how which does can could "
    "you your me my we it there have has please".split()
)
PREFIX_MIN_LENGTH = 4  # "san" (sân) must not match "sang" (sáng)


def to_tsquery_text(query: str) -> str | None:
    """OR of the accent-free words; None when there is no usable word.

    Words of 4+ letters also match as prefixes ("breakfast" -> "breakfasts"); shorter ones only
    exactly. Only [a-z0-9] reaches to_tsquery, so guest input can never inject tsquery syntax.
    """
    words = re.findall(r"[a-z0-9]+", strip_accents(query).lower())
    terms = [w for w in dict.fromkeys(words) if len(w) >= 2 and w not in STOPWORDS][:MAX_TERMS]
    return " | ".join(f"{t}:*" if len(t) >= PREFIX_MIN_LENGTH else t for t in terms) or None


def _ranked(stmt: Select, model: type[KbEntry] | type[NearbyPlace], tsquery: str | None) -> Select:
    if tsquery is None:
        return stmt.where(false())
    query = func.to_tsquery("simple", tsquery)
    return stmt.where(model.search_tsv.op("@@")(query)).order_by(
        func.ts_rank(model.search_tsv, query).desc(), model.updated_at.desc()
    )


def _place_hit(place: NearbyPlace, lang: str) -> PlaceHit:
    distance = place.distance_km
    return PlaceHit(
        name=place.name,
        category=place.category.value,
        distance_km=float(distance) if isinstance(distance, Decimal) else distance,
        open_hours=place.open_hours,
        note=place.description(lang),
        map_url=place.map_url,
    )


def _kb_hit(entry: KbEntry, lang: str) -> KbHit:
    return KbHit(
        id=str(entry.id),
        title=entry.title(lang),
        content=entry.content(lang),
        updated_at=entry.updated_at.date().isoformat(),
    )


async def search(db: AsyncSession, topic: ToolTopic, query: str, lang: str) -> SearchResult:
    """Published entries/places for `topic`, best matches of `query` first."""
    scope = SCOPES[topic]
    content_lang = "vi" if lang == "vi" else "en"  # other languages: the bot translates from en
    tsquery = to_tsquery_text(query)

    entries: list[KbEntry] = []
    if scope.search_kb:
        base = select(KbEntry).where(KbEntry.is_published.is_(True))
        if scope.kb_topic is not None:
            base = base.where(KbEntry.topic == scope.kb_topic)
        entries = list(await db.scalars(_ranked(base, KbEntry, tsquery).limit(MAX_ENTRIES)))
        if not entries and scope.kb_topic is not None:
            entries = list(
                await db.scalars(base.order_by(KbEntry.updated_at.desc()).limit(MAX_ENTRIES))
            )

    places: list[NearbyPlace] = []
    if scope.search_places:
        base = select(NearbyPlace).where(NearbyPlace.is_published.is_(True))
        if scope.place_category is not None:
            base = base.where(NearbyPlace.category == scope.place_category)
        places = list(await db.scalars(_ranked(base, NearbyPlace, tsquery).limit(MAX_PLACES)))
        if not places and scope.place_category is not None:
            places = list(
                await db.scalars(
                    base.order_by(NearbyPlace.distance_km.asc().nulls_last()).limit(MAX_PLACES)
                )
            )

    return SearchResult(
        found=bool(entries or places),
        entries=[_kb_hit(e, content_lang) for e in entries],
        places=[_place_hit(p, content_lang) for p in places],
    )
