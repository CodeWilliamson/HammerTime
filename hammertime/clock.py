"""Clock indirection.

The server always uses *local* wall-clock time (see ``db.get_current_draw``), exactly
like the Node original which relies on ``new Date()``. Wrapping it in one function lets
the parity test-suite freeze time through ``HAMMERTIME_FAKE_NOW`` without changing any
production behaviour (the env var is never set in production).
"""

import os
from datetime import datetime

#: Hardcoded English weekday names, indexed Sunday=0 (mirrors `Date#getDay()`).
#: Deliberately not `strftime("%A")` so a non-English locale cannot change the values
#: stored/compared in the database.
WEEKDAYS = (
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
)


def now() -> datetime:
    """Current local time as a naive datetime (JS ``new Date()``)."""
    fake = os.environ.get("HAMMERTIME_FAKE_NOW")
    if fake:
        return datetime.fromisoformat(fake)
    return datetime.now()


def weekday_name(moment: datetime) -> str:
    """English weekday name for ``moment`` (JS ``toLocaleDateString("en-CA", ...)``)."""
    return WEEKDAYS[moment.isoweekday() % 7]
