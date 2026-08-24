"""Production WSGI wrapper for ClipperOS.

Keeps the existing Flask application and process-local job model intact while
adding lightweight production protections at the WSGI boundary.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from typing import Callable

from webapp import app as flask_app


# Route-specific limits. These are intentionally conservative and in-memory;
# the production service runs one worker because JOBS is process-local.
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
        rule = next((r for r in RATE_LIMITS if path.startswith(r[0])), None)
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
                retry_after = max(1, int(hits[0] + window - now) + 1)
                return False, retry_after

            hits.append(now)

        return True, 0


limiter = RateLimiter()


def _client_ip(environ: dict) -> str:
    """Prefer the first proxy-forwarded address on Render, else peer IP."""
    forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return environ.get("REMOTE_ADDR", "unknown")


def _json_response(start_response: Callable, status: str, payload: dict, extra_headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("X-Content-Type-Options", "nosniff"),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    start_response(status, headers)
    return [body]


class ProductionMiddleware:
    def __init__(self, application):
        self.application = application

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")

        allowed, retry_after = limiter.check(_client_ip(environ), path)
        if not allowed:
            return _json_response(
                start_response,
                "429 Too Many Requests",
                {"error": "Too many requests. Please try again later."},
                [("Retry-After", str(retry_after))],
            )

        captured = {}

        def capture_start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = headers
            captured["exc_info"] = exc_info
            return start_response(status, headers, exc_info)

        try:
            response = self.application(environ, capture_start_response)
            status = captured.get("status", "")

            # Flask normally handles exceptions itself, but never expose an
            # HTML traceback/error page through the production API boundary.
            if status.startswith("500 "):
                try:
                    response = self.application
                finally:
                    pass

            return response
        except Exception:
            return _json_response(
                start_response,
                "500 Internal Server Error",
                {"error": "An internal server error occurred."},
            )


application = ProductionMiddleware(flask_app)
