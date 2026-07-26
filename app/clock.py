from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("America/Los_Angeles")

def today() -> date:
    return datetime.now(APP_TIMEZONE).date()