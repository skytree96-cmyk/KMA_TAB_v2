"""Run the response-retention purge in the background, at most once a day per server process."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any


LOGGER = logging.getLogger(__name__)
INTERVAL_SECONDS = 24 * 60 * 60
_LOCK = threading.Lock()
_last_started = 0.0


def schedule_purge(store: Any, *, clock=time.time) -> bool:
    """Start one background purge if a day has passed; the caller never waits for it."""
    global _last_started
    now = clock()
    with _LOCK:
        if now - _last_started < INTERVAL_SECONDS:
            return False
        _last_started = now
    threading.Thread(target=_purge, args=(store,), name="tap-retention", daemon=True).start()
    return True


def _purge(store: Any) -> None:
    try:
        count = store.purge_expired_assessments()
        if count:
            LOGGER.info("Retention purge removed %d assessment records", count)
    except Exception as exc:
        # The next day's run retries; a failure must not reach the user's page.
        LOGGER.warning("Retention purge failed: %s", type(exc).__name__)
