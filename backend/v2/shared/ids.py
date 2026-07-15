import hashlib

from ulid import ULID


def new_ulid() -> str:
    return str(ULID())


def stable_ulid(*parts: str) -> str:
    """Return a deterministic ULID-shaped identifier for an idempotency key."""
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return str(ULID.from_bytes(digest[:16]))
