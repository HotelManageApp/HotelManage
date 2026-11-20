"""What express-checkout hands to other modules through their hooks."""

from app.modules.express_checkout.billing import is_bill_locked
from app.modules.express_checkout.service import (
    refuse_desk_checkout,
    reject_open_on_stay_closed,
)
from app.modules.stay_access.events import (
    register_bill_lock_check,
    register_desk_checkout_guard,
    register_on_stay_closed,
)


def register() -> None:
    # stay_access refuses to change the room charge once the bill is verified.
    register_bill_lock_check(is_bill_locked)
    # A desk check-out must not bypass an open express request (409 CHECKOUT_REQUEST_OPEN).
    register_desk_checkout_guard(refuse_desk_checkout)
    # A stay closed any other way leaves no open request behind (REJECTED, reason STAY_CLOSED).
    register_on_stay_closed(reject_open_on_stay_closed)
