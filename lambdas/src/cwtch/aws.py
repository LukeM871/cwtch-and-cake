"""AWS clients (created once per Lambda container and reused) and table names."""
import functools
import os

import boto3
from botocore.config import Config


@functools.cache
def dynamodb():
    return boto3.client("dynamodb")


@functools.cache
def ses():
    return boto3.client("sesv2")


@functools.cache
def comprehend():
    """Toxicity detection isn't offered in London, so this client points at the
    region in COMPREHEND_REGION (Ireland). Short timeouts and a single retry:
    a slow AI check must never hold up a review for long (it fails open)."""
    return boto3.client(
        "comprehend",
        region_name=os.environ["COMPREHEND_REGION"],
        config=Config(connect_timeout=2, read_timeout=3, retries={"total_max_attempts": 2, "mode": "standard"}),
    )


def bookings_table() -> str:
    return os.environ["BOOKINGS_TABLE"]


def slots_table() -> str:
    return os.environ["SLOTS_TABLE"]


def cafe_table() -> str:
    return os.environ["CAFE_TABLE"]


def reviews_table() -> str:
    return os.environ["REVIEWS_TABLE"]


def reset_clients() -> None:
    """Used by tests so each test gets fresh (mocked) clients. (A test may have
    swapped one for a fake, which has no cache to clear.)"""
    for client in (dynamodb, ses, comprehend):
        clear = getattr(client, "cache_clear", None)
        if clear:
            clear()
