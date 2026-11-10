"""Opening hours, bookable slots and capacities (docs/API.md section 3)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

UK = ZoneInfo("Europe/London")

BOOKING_WINDOW_DAYS = 60
MIN_LEAD_MINUTES = 30

TYPES = ("class", "room", "group")

# Saturday classes: one class per slot, each slot is a fixed class.
CLASS_SLOTS = {"10:00": "latte-art", "14:00": "welsh-cakes"}
CLASS_KINDS = tuple(CLASS_SLOTS.values())

ROOM_TIMES_WEEKDAY = ("08:00", "10:00", "12:00", "14:00", "16:00", "18:00")
ROOM_TIMES_WEEKEND = ("10:00", "12:00", "14:00", "16:00")

CAPACITY = {"class": 8, "room": 2, "group": 1}
PARTY_SIZE = {"class": (1, 4), "room": (2, 6), "group": (5, 20)}


def now_uk() -> datetime:
    """Current UK time. Tests replace this to freeze the clock."""
    return datetime.now(UK)


def slot_times(booking_type: str, day: date) -> tuple[str, ...]:
    """All start times for a type on a given day (empty if not available)."""
    weekend = day.weekday() >= 5
    if booking_type == "class":
        return tuple(CLASS_SLOTS) if day.weekday() == 5 else ()
    if booking_type in ("room", "group"):
        return ROOM_TIMES_WEEKEND if weekend else ROOM_TIMES_WEEKDAY
    return ()


def slot_start(day: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=UK)


def is_far_enough_ahead(day: date, hhmm: str, now: datetime) -> bool:
    """A slot today must start at least MIN_LEAD_MINUTES from now."""
    return slot_start(day, hhmm) - now >= timedelta(minutes=MIN_LEAD_MINUTES)


def units_for(booking_type: str, party_size: int) -> int:
    """How much of a slot's capacity a booking uses: people for classes, 1 room/table otherwise."""
    return party_size if booking_type == "class" else 1


def slot_key(booking_type: str, day: str, hhmm: str) -> str:
    return f"{booking_type}#{day}#{hhmm}"


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def booking_ttl(day: date) -> int:
    """Bookings delete themselves 30 days after the booking date."""
    return epoch(datetime.combine(day + timedelta(days=30), time(0), tzinfo=UK))


def slot_ttl(day: date) -> int:
    return epoch(datetime.combine(day + timedelta(days=1), time(23, 59), tzinfo=UK))
