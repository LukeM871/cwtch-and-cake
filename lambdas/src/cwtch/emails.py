"""Booking emails via Amazon SES (docs/API.md section 8). Best effort: never fails a booking."""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import date

from . import aws

log = logging.getLogger()

LABELS = {"class": "Saturday class", "room": "Group study room", "group": "Group / society table"}
CLASS_NAMES = {"latte-art": "Latte art class", "welsh-cakes": "Welsh cake baking class"}


def _what(b: dict) -> str:
    return CLASS_NAMES.get(b.get("classKind", ""), LABELS.get(b["type"], b["type"]))


def _nice_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%A ") + str(d.day) + d.strftime(" %B %Y")


def _send(to: str, subject: str, lines: list[str]) -> bool:
    sender = os.environ.get("SENDER_EMAIL", "")
    if not sender:
        return False  # emails switched off (no verified sender yet)
    footer = "Cwtch & Cake is a fictional café, built as a portfolio project."
    text = "\n".join(lines + ["", footer])
    body_html = "".join(f"<p>{html.escape(line)}</p>" for line in lines if line) + (
        f'<p style="color:#6b7280;font-size:12px">{html.escape(footer)}</p>'
    )
    try:
        aws.ses().send_email(
            FromEmailAddress=f"Cwtch & Cake <{sender}>",
            Destination={"ToAddresses": [to]},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": text, "Charset": "UTF-8"}, "Html": {"Data": body_html, "Charset": "UTF-8"}},
                }
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 - email must never break a booking
        log.warning(json.dumps({"email": "failed", "exception": type(exc).__name__}))
        return False


def booking_confirmed(b: dict) -> bool:
    site = os.environ.get("SITE_URL", "")
    lines = [
        f"Hi {b['name']},",
        "",
        f"You're booked in! Your reference is {b['reference']}.",
        "",
        f"What: {_what(b)}",
        f"When: {_nice_date(b['date'])} at {b['time']}",
        f"People: {b['partySize']}",
        "Where: Cwtch & Cake, Cathays, Cardiff",
        "",
        f"Need to cancel? Use your reference and this email address at {site}/cancel",
        "",
        "See you soon. Diolch!",
    ]
    return _send(b["email"], f"Your Cwtch & Cake booking: {b['reference']}", lines)


def booking_cancelled(b: dict) -> bool:
    lines = [
        f"Hi {b['name']},",
        "",
        f"Your booking {b['reference']} ({_what(b)} on {_nice_date(b['date'])} at {b['time']}) has been cancelled.",
        "",
        "Hope to see you another time. Diolch!",
    ]
    return _send(b["email"], f"Booking cancelled: {b['reference']}", lines)
