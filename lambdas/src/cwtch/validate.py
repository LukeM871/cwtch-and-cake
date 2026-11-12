"""Input validation (docs/API.md sections 4 and 6, docs/SECURITY.md section 5)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

from . import reviews, rules, wordfilter

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")
REFERENCE_RE = re.compile(r"^CC-[0-9A-HJKMNP-TV-Z]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Line breaks of every kind: Windows \r\n, old Mac \r, vertical tab, form feed,
# and Unicode's next-line, line-separator and paragraph-separator characters.
_LINE_BREAKS = re.compile(r"\r\n?|[\n\v\f\x85  ]")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")

FRIENDLY = "Please keep reviews friendly"
NAME_BLOCKED = "Please choose a different name"


def _visible(value: str) -> str:
    """NFC-normalise, tabs → spaces, then drop control and invisible format characters
    (NUL, bell, zero-width spaces, right-to-left override tricks...). Keeps \\n, letters, accents and emoji."""
    value = unicodedata.normalize("NFC", value).replace("\t", " ")
    return "".join(ch for ch in value if ch == "\n" or unicodedata.category(ch)[0] != "C")


def clean_text(value) -> str:
    """One-line text: trimmed, control characters removed, any run of spaces or line breaks → one space."""
    if not isinstance(value, str):
        return ""
    return " ".join(_visible(_LINE_BREAKS.sub(" ", value)).split())


def clean_multiline(value) -> str:
    """Text that may have paragraphs (a review, booking notes): like clean_text, but line
    breaks are kept as \\n, with at most one empty line in a row."""
    if not isinstance(value, str):
        return ""
    lines = _visible(_LINE_BREAKS.sub("\n", value)).split("\n")
    joined = "\n".join(" ".join(line.split()) for line in lines)
    return _MANY_BLANK_LINES.sub("\n\n", joined).strip()


def is_honeypot_filled(body: dict) -> bool:
    return bool(clean_text(body.get("website", "")))


def parse_date(value, errors: dict, now: datetime) -> date | None:
    if not isinstance(value, str) or not DATE_RE.match(value):
        errors["date"] = "Choose a date"
        return None
    try:
        day = date.fromisoformat(value)
    except ValueError:
        errors["date"] = "Choose a valid date"
        return None
    today = now.date()
    if day < today:
        errors["date"] = "That date has passed"
    elif day > today + timedelta(days=rules.BOOKING_WINDOW_DAYS):
        errors["date"] = f"Bookings open up to {rules.BOOKING_WINDOW_DAYS} days ahead"
    return day


def any_date(value, errors: dict, field: str = "date") -> date | None:
    """A real YYYY-MM-DD date, past or future (the admin can look at any day)."""
    if isinstance(value, str) and DATE_RE.match(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    errors[field] = "Choose a valid date (YYYY-MM-DD)"
    return None


def email(value, errors: dict, field: str = "email") -> str:
    value = clean_text(value).lower()
    if not value or len(value) > 254 or not EMAIL_RE.match(value):
        errors[field] = "Enter a valid email address"
    return value


def text(body: dict, field: str, errors: dict, *, min_len: int, max_len: int, label: str, multiline: bool = False) -> str:
    value = (clean_multiline if multiline else clean_text)(body.get(field, ""))
    if len(value) < min_len:
        errors[field] = f"Enter {label}"
    elif len(value) > max_len:
        errors[field] = f"Keep this to {max_len} characters or fewer"
    return value


def whole_number(value, lo: int, hi: int) -> int | None:
    """A JSON whole number in [lo, hi] (true/false and 4.0 don't count), else None."""
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        return None
    return value


def booking(body: dict, now: datetime) -> tuple[dict, dict]:
    """Returns (clean_booking, errors). errors is empty when everything is valid."""
    errors: dict[str, str] = {}

    booking_type = body.get("type")
    if booking_type not in rules.TYPES:
        errors["type"] = "Choose what you'd like to book"
        return {}, errors

    day = parse_date(body.get("date"), errors, now)

    hhmm = body.get("time")
    if day and "date" not in errors:
        times = rules.slot_times(booking_type, day)
        if booking_type == "class" and not times:
            errors["date"] = "Classes run on Saturdays only"
        elif hhmm not in times:
            errors["time"] = "Choose one of the available times"
        elif not rules.is_far_enough_ahead(day, hhmm, now):
            errors["time"] = "That time is too soon. Please pick a later slot"

    class_kind = None
    if booking_type == "class" and "time" not in errors and isinstance(hhmm, str) and hhmm in rules.CLASS_SLOTS:
        class_kind = rules.CLASS_SLOTS[hhmm]
        requested = body.get("classKind")
        if requested not in (None, "", class_kind):
            errors["classKind"] = "That class runs at a different time"

    lo, hi = rules.PARTY_SIZE[booking_type]
    party = whole_number(body.get("partySize"), lo, hi)
    if party is None:
        errors["partySize"] = f"Choose between {lo} and {hi} people"

    name = text(body, "name", errors, min_len=1, max_len=80, label="your name")
    mail = email(body.get("email"), errors)
    society = ""
    if booking_type == "group":
        society = text(body, "society", errors, min_len=1, max_len=80, label="the society or group name")
    notes = text(body, "notes", errors, min_len=0, max_len=500, label="notes", multiline=True)

    clean = {
        "type": booking_type,
        "date": day.isoformat() if day else None,
        "time": hhmm,
        "partySize": party,
        "name": name,
        "email": mail,
    }
    if class_kind:
        clean["classKind"] = class_kind
    if society:
        clean["society"] = society
    if notes:
        clean["notes"] = notes
    return clean, errors


def reference(value, errors: dict) -> str:
    value = clean_text(value).upper()
    if not REFERENCE_RE.match(value):
        errors["reference"] = "Enter your booking reference, like CC-7F3K9Q"
    return value


def review(body: dict) -> tuple[dict, dict]:
    """POST /api/reviews fields → (clean_review, errors). Includes the word filter
    (docs/API.md section 6, steps 1 and 2), so every problem comes back in one answer."""
    errors: dict[str, str] = {}

    rating = whole_number(body.get("rating"), 1, 5)
    if rating is None:
        errors["rating"] = "Choose a rating from 1 to 5"

    tags = body.get("tags")
    if tags is None:
        tags = []
    if (
        not isinstance(tags, list)
        or len(tags) > reviews.MAX_TAGS
        or not all(isinstance(t, str) and t in reviews.TAGS for t in tags)
        or len(set(tags)) != len(tags)
    ):
        errors["tags"] = f"Choose up to {reviews.MAX_TAGS} different tags from the list"
        tags = []
    else:
        tags = sorted(tags, key=reviews.TAGS.index)  # one fixed order, whatever order they were ticked in

    comment = clean_multiline(body.get("comment"))
    if len(comment) < reviews.COMMENT_MIN:
        errors["comment"] = f"Write at least {reviews.COMMENT_MIN} characters"
    elif len(comment) > reviews.COMMENT_MAX:
        errors["comment"] = f"Keep your review to {reviews.COMMENT_MAX} characters or fewer"
    elif wordfilter.is_blocked(comment):
        errors["comment"] = FRIENDLY

    display_name = text(body, "displayName", errors, min_len=1, max_len=reviews.NAME_MAX, label="a display name")
    if "displayName" not in errors and wordfilter.is_blocked(display_name):
        errors["displayName"] = NAME_BLOCKED

    course_year = body.get("courseYear")
    if course_year in (None, ""):
        course_year = None
    elif course_year not in reviews.COURSE_YEARS:
        errors["courseYear"] = "Choose one of the options"

    # The "Verified visit" badge: a booking reference and its email, both or neither.
    ref, mail = clean_text(body.get("reference")), clean_text(body.get("email"))
    if ref or mail:
        if ref:
            ref = reference(ref, errors)
        else:
            errors["reference"] = "Add your booking reference too, or leave both empty"
        if mail:
            mail = email(mail, errors)
        else:
            errors["email"] = "Add the email you booked with too, or leave both empty"

    clean = {"rating": rating, "tags": tags, "comment": comment, "displayName": display_name}
    if course_year:
        clean["courseYear"] = course_year
    if ref and mail:
        clean["reference"], clean["email"] = ref, mail
    return clean, errors
