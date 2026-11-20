"""What express-checkout hands to other modules through their hooks."""

from app.modules.express_checkout.billing import is_bill_locked
from app.modules.stay_access.events import register_bill_lock_check


def register() -> None:
    # stay_access refuses to change the room charge once the bill is verified.
    register_bill_lock_check(is_bill_locked)
