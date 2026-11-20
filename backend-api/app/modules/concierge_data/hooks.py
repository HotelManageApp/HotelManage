"""Concierge data that ends with the stay."""

from app.modules.concierge_data.chat import forget_stay
from app.modules.stay_access.events import register_on_stay_closed


def register() -> None:
    # Runs in the transaction that closes the stay: if anything fails, nothing is deleted.
    register_on_stay_closed(forget_stay)
