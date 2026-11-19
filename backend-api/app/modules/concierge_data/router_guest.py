"""Guest-token API used by the AI concierge (ai-service calls it with the guest's own token)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import DbSession
from app.modules.concierge_data.search import SearchResult, ToolTopic, search
from app.modules.stay_access.deps import CurrentStay

router = APIRouter(prefix="/guest/kb", tags=["guest-concierge"])


@router.get("/search", response_model=SearchResult)
async def guest_search(
    ctx: CurrentStay,
    db: DbSession,
    topic: ToolTopic,
    q: Annotated[str, Query(max_length=300)] = "",
    lang: Annotated[str | None, Query(pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")] = None,
) -> SearchResult:
    """Shape of `data` in the `get_hotel_info_and_guide` tool output (chatbot-tools-spec §4.1)."""
    return await search(db, topic, q, (lang or ctx.lang).split("-")[0].lower())
