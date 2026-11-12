"""The AI check on reviews: Amazon Comprehend toxicity detection (docs/API.md section 6, step 3).

- score >= 0.8 → rejected straight away, with a polite message
- 0.5 to 0.8   → saved, but "flagged" for the admin to look at first
- below 0.5    → saved as normal (still waits for the admin's approval)

It fails OPEN: if the check is switched off (no COMPREHEND_REGION) or Comprehend
is down or slow, the review is saved without a score. That's safe because every
review waits for the admin's approval anyway; a broken AI service must never
stop people leaving reviews.

Comprehend accepts up to 10 text segments of at most 1 KB of UTF-8 each. A
500-character comment of emoji is 2 KB, and an over-long segment makes the whole
call fail, which would SKIP the check: an easy way to sneak abuse past it. So
the comment is cut into segments that each fit, and the display name (also
shown publicly) is checked as one more segment in the same call.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass

from . import aws

log = logging.getLogger()

REJECT_AT = 0.8
FLAG_AT = 0.5
MAX_SEGMENT_BYTES = 1000  # Comprehend's limit is 1 KB per segment; a little headroom
MAX_SEGMENTS = 10

_PIECES = re.compile(r"\S+\s*|\s+")


@dataclass(frozen=True)
class Verdict:
    checked: bool  # False = switched off or Comprehend unavailable
    comment_score: float = 0.0
    name_score: float = 0.0
    labels: tuple[str, ...] = ()  # e.g. ("INSULT", "PROFANITY"), strongest first

    @property
    def score(self) -> float:
        return max(self.comment_score, self.name_score)

    @property
    def flagged(self) -> bool:
        return self.checked and self.score >= FLAG_AT


def enabled() -> bool:
    return bool(os.environ.get("COMPREHEND_REGION"))


def split_text(text: str, max_bytes: int = MAX_SEGMENT_BYTES) -> list[str]:
    """Cut text into pieces of at most max_bytes of UTF-8, between words where possible."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            chunks.append("".join(current))
        current, size = [], 0

    for piece in _PIECES.findall(text):
        piece_bytes = len(piece.encode("utf-8"))
        if piece_bytes > max_bytes:  # one enormous "word": cut it between characters
            for ch in piece:
                ch_bytes = len(ch.encode("utf-8"))
                if size + ch_bytes > max_bytes:
                    flush()
                current.append(ch)
                size += ch_bytes
            continue
        if size + piece_bytes > max_bytes:
            flush()
        current.append(piece)
        size += piece_bytes
    flush()
    return [c.strip() for c in chunks if c.strip()]


def _score(value) -> float:
    score = float(value)
    if math.isnan(score) or not 0.0 <= score <= 1.0:
        raise ValueError("score out of range")
    return score


def check(comment: str, display_name: str) -> Verdict:
    if not enabled():
        return Verdict(checked=False)
    segments = split_text(comment)
    if not segments or len(segments) >= MAX_SEGMENTS:  # can't happen at 500 characters, but never send a bad call
        return Verdict(checked=False)
    segments.append(display_name)
    try:
        resp = aws.comprehend().detect_toxic_content(
            TextSegments=[{"Text": s} for s in segments], LanguageCode="en"
        )
        results = resp["ResultList"]
        if len(results) != len(segments):
            raise ValueError("wrong number of results")
        scores = [_score(r["Toxicity"]) for r in results]
        strongest: dict[str, float] = {}
        for r in results:
            for label in r.get("Labels", []):
                s = _score(label["Score"])
                if s >= FLAG_AT:
                    strongest[label["Name"]] = max(s, strongest.get(label["Name"], 0.0))
    except Exception as exc:  # noqa: BLE001 - fail open (see the module docstring)
        log.warning(json.dumps({"toxicity": "unavailable", "exception": type(exc).__name__}))
        return Verdict(checked=False)
    labels = tuple(sorted(strongest, key=lambda name: (-strongest[name], name)))
    return Verdict(True, max(scores[:-1]), scores[-1], labels)
