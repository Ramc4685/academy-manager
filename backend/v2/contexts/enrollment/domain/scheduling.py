"""Period-boundary maths shared by every "at end of period" transition.

``end_of_academy_month`` was ``self_cancel._end_of_month`` (issue #675). Issue
#820 added a second caller — the admin "drop at end of period" — and the two
MUST agree to the microsecond: both stamp ``pending_cancellation_at``, both
hand that instant to billing as ``effective_at``, and billing keys the payable
period off the academy-local month. A second, slightly different
implementation would bill one of the two paths for a month the family was
told they would not be charged for.
"""

from __future__ import annotations

import calendar
import logging
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


def end_of_academy_month(now: datetime, timezone_name: str | None) -> datetime:
    """Last instant of ``now``'s calendar month on the academy's wall clock,
    returned in UTC.

    It must agree with billing's ``period_of`` (academy-local month). A
    Chicago family cancelling at 8pm on the 30th is still in THIS month
    locally even though UTC has rolled over. Unknown / unset zones fall back
    to UTC, exactly as ``period_of`` does.
    """
    zone: tzinfo = UTC
    if timezone_name:
        try:
            zone = ZoneInfo(timezone_name)
        except (KeyError, ValueError):
            log.warning("end_of_academy_month_bad_timezone", extra={"tz": timezone_name})
    local_now = now.astimezone(zone)
    last_day = calendar.monthrange(local_now.year, local_now.month)[1]
    local_end = datetime(local_now.year, local_now.month, last_day, 23, 59, 59, 999999, tzinfo=zone)
    return local_end.astimezone(UTC)


__all__ = ["end_of_academy_month"]
