"""Unit tests for the two review checks: the word filter and the Comprehend toxicity check."""
import json
import re

import pytest

from conftest import FakeComprehend
from cwtch import toxicity, validate, wordfilter
from test_menu import MENU_DATA


@pytest.fixture
def test_word(monkeypatch):
    monkeypatch.setattr(wordfilter, "BLOCKED", wordfilter.BLOCKED | {wordfilter.word_hash("grumbleweed")})


# --- word filter --------------------------------------------------------------------------------

def test_blocklist_is_hashes_only():
    assert len(wordfilter.BLOCKED) > 50
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in wordfilter.BLOCKED)


@pytest.mark.parametrize("text", [
    "grumbleweed", "Grumbleweed!", "GRUMBLEWEED", "grümblewéed", "grumb1eweed", "grumbl3w33d", "9rumbleweed",
    "grumbleweeeeeeeed", "grumbleweeds", "g r u m b l e w e e d", "g-r-u-m-b-l-e-w-e-e-d",
    "a g r u m b l e w e e d", "ｇｒｕｍｂｌｅｗｅｅｄ",  # full-width letters
    "grumblеwееd",  # Cyrillic е
])
def test_disguises_are_caught(test_word, text):
    assert wordfilter.is_blocked(f"Honestly, {text} staff.")


@pytest.mark.parametrize("text", ["grumbleweedy", "megagrumbleweed", "grumble weed", "grumbleweed".replace("e", "")])
def test_only_whole_words_match(test_word, text):
    assert not wordfilter.is_blocked(text)


@pytest.mark.parametrize("text", [
    "Scunthorpe", "a classic Welsh cake", "assessment week", "Walked Offa's Dyke then came here",
    "Penistone", "Cockett", "pros and cons", "spick and span", "raccoon", "Niger", "Nigeria", "snigger",
    "the spice latte", "flame retardant", "among friends", "Mongolian", "J. R. R. Tolkien fans", "1 2 3 4 5",
    "bloody good coffee", "damn fine Welsh cakes", "Diolch yn fawr, gwych!", "Llanishen", "Splott", "Cathays",
    "Shitake mushrooms", "Sussex", "Essex", "manuscript", "therapist", "cocktail", "Dickens", "assassin",
])
def test_innocent_words_pass_the_real_filter(text):
    assert not wordfilter.is_blocked(text)


def test_the_whole_menu_passes_the_real_filter():
    assert not wordfilter.is_blocked(json.dumps(MENU_DATA, ensure_ascii=False))


# --- cleaning text --------------------------------------------------------------------------------

@pytest.mark.parametrize("raw, one_line, multi_line", [
    ("  Ffion\x00\x07  R. ", "Ffion R.", "Ffion R."),
    ("Line one\r\nLine two", "Line one Line two", "Line one\nLine two"),
    ("a\n\n\n\n\nb", "a b", "a\n\nb"),
    ("tab\there", "tab here", "tab here"),
    ("zero​width", "zerowidth", "zerowidth"),
    ("‮evil", "evil", "evil"),  # right-to-left override (used to disguise text)
    ("é", "é", "é"),  # é as e + accent → one character (NFC), so lengths are fair
    ("emoji 🍪 kept", "emoji 🍪 kept", "emoji 🍪 kept"),
    ("para graph", "para graph", "para\ngraph"),
    (None, "", ""),
    (42, "", ""),
])
def test_text_cleaning(raw, one_line, multi_line):
    assert validate.clean_text(raw) == one_line
    assert validate.clean_multiline(raw) == multi_line


# --- toxicity: cutting text to fit Comprehend ---------------------------------------------------------

def test_short_text_is_one_segment():
    assert toxicity.split_text("Lovely place to study.") == ["Lovely place to study."]


def test_long_text_splits_between_words():
    text = " ".join(["cwtch"] * 400)  # 2,399 bytes
    parts = toxicity.split_text(text)
    assert len(parts) == 3
    assert all(len(p.encode()) <= toxicity.MAX_SEGMENT_BYTES for p in parts)
    assert " ".join(parts) == text


def test_one_giant_word_is_cut_between_characters():
    text = "🍪" * 500  # 2,000 bytes, no spaces
    parts = toxicity.split_text(text)
    assert all(len(p.encode()) <= toxicity.MAX_SEGMENT_BYTES for p in parts)
    assert "".join(parts) == text


# --- toxicity: talking to Comprehend --------------------------------------------------------------------

def test_switched_off_means_no_call(monkeypatch):
    fake = FakeComprehend()
    monkeypatch.setattr("cwtch.aws.comprehend", lambda: fake)
    verdict = toxicity.check("A perfectly nice review.", "Ffion R.")
    assert verdict.checked is False and verdict.flagged is False and fake.calls == []


def test_labels_strongest_first(comprehend):
    comprehend.labels = lambda text, score: [
        {"Name": "PROFANITY", "Score": 0.55}, {"Name": "INSULT", "Score": 0.71}, {"Name": "GRAPHIC", "Score": 0.1},
    ]
    comprehend.scores = lambda text: 0.6
    verdict = toxicity.check("Some borderline review text here.", "Ffion R.")
    assert verdict.checked and verdict.flagged
    assert verdict.labels == ("INSULT", "PROFANITY")  # GRAPHIC is under 0.5, so left out


@pytest.mark.parametrize("bad", [float("nan"), 1.5, -0.1, "high"])
def test_nonsense_scores_count_as_unavailable(comprehend, bad):
    comprehend.scores = lambda text: bad
    assert toxicity.check("Some review text that is long enough.", "Ffion R.").checked is False


def test_wrong_number_of_results_counts_as_unavailable(comprehend, monkeypatch):
    monkeypatch.setattr(comprehend, "detect_toxic_content", lambda **kw: {"ResultList": [{"Toxicity": 0.1, "Labels": []}]})
    assert toxicity.check("Some review text that is long enough.", "Ffion R.").checked is False
