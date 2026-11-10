"""Booking references: CC- + 6 Crockford base32 characters (no I, L, O or U)."""
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_reference() -> str:
    return "CC-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
