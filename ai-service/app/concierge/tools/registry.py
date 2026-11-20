"""The concierge's tools and which ones the model may see (SPEC-concierge-actions, "Bộ tool").

Write tools are left out of the list sent to the model while the stay is CHECKOUT_PENDING:
the server decides, not the prompt. The orchestrator also refuses a call to a tool that was
not offered, in case a model calls one anyway.
"""

from app.concierge.tools import guide, menu, my_requests
from app.concierge.tools.base import Tool

ALL_TOOLS: tuple[Tool, ...] = (guide.TOOL, menu.TOOL, my_requests.TOOL)


def available(stay_status: str, tools: tuple[Tool, ...] = ALL_TOOLS) -> tuple[Tool, ...]:
    if stay_status == "CHECKOUT_PENDING":
        return tuple(t for t in tools if not t.write)
    return tools


def by_name(tools: tuple[Tool, ...] = ALL_TOOLS) -> dict[str, Tool]:
    return {t.name: t for t in tools}
