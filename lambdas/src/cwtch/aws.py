"""AWS clients (created once per Lambda container and reused) and table names."""
import functools
import os

import boto3


@functools.cache
def dynamodb():
    return boto3.client("dynamodb")


@functools.cache
def ses():
    return boto3.client("sesv2")


def bookings_table() -> str:
    return os.environ["BOOKINGS_TABLE"]


def slots_table() -> str:
    return os.environ["SLOTS_TABLE"]


def reset_clients() -> None:
    """Used by tests so each test gets fresh (mocked) clients."""
    dynamodb.cache_clear()
    ses.cache_clear()
