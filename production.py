"""Production WSGI entry point for ClipperOS."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from webapp import app


# In-memory limits are intentional: JOBS is process-local, so production uses
# one worker to preserve the existing job model.
RATE_LIMITS = (
    ("/api/download/", 5, 60),
    ("/api/analyze", 3, 600),
    ("/api/transcript", 5, 600),
    ("/api/detect", 30, 60),
)


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client: str, path: str) -> tuple[bool, int]:
        rule = next((rule for rule in RATE_LIMITS if path.startswith(rule[0])), None)
        if rule is None:
            return True, 0

        prefix, limit, window = rule
        now = time.monotonic()
        key = (client, prefix)
        with self._lock:
            hits = self._hits[key]
            cutoff = now - window
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False, max(1, int(hits[0] + window - now) + 1)
            hits.append(now)
        return True, 0


limiter = RateLimiter()


def _client_ip(environ: dict) -> str:
    forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return environ.get("REMOTE_ADDR", "unknown")


def _rate_limited_response(start_response, retry_after: int):
    body = b'{"error":"Too many requests. Please try again later."}'
    start_response(
        "429 Too Many Requests",
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Retry-After", str(retry_after)),
            ("X-Content-Type-Options", "nosniff"),
        ],
    )
    return [body]


def application(environ, start_response):
    allowed, retry_after = limiter.check(_client_ip(environ), environ.get("PATH_INFO", ""))
    if not allowed:
        return _rate_limited_response(start_response, retry_after)
    return app(environ, start_response)
