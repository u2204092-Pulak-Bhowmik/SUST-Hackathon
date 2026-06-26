from __future__ import annotations

import os


# Default window used to decide whether two matching debits represent one duplicate
# payment. 24 hours comfortably covers app-retry double charges and delayed duplicate
# reports while staying small enough to avoid pairing unrelated recurring payments.
# The complaint must already claim a duplicate before this window is even consulted.
DEFAULT_DUPLICATE_WINDOW_SECONDS = 86_400


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def duplicate_window_seconds() -> int:
    """Max seconds between two matching debits for them to count as a duplicate.

    Configurable via the ``DUPLICATE_WINDOW_SECONDS`` environment variable. Read live
    so the value can be overridden per deployment without code changes; not required
    for startup.
    """

    return _positive_int_env("DUPLICATE_WINDOW_SECONDS", DEFAULT_DUPLICATE_WINDOW_SECONDS)
