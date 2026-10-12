"""Security and reliability middleware.

* ``BodySizeLimitMiddleware`` rejects oversized requests with 413, both when
  ``Content-Length`` is declared and when a chunked body grows past the limit.
* ``RateLimitMiddleware`` applies a per-client sliding-window limit to mutating requests
  (POST/PUT/PATCH/DELETE). It is in-memory and per-process: adequate for a single-instance
  deployment, not a substitute for an edge rate limiter.
* ``SecurityHeadersMiddleware`` adds conservative headers to every response.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def _send_json(
    send: Send,
    status: int,
    body: Mapping[str, object],
    headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    payload = json.dumps(body).encode()
    raw_headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
    ]
    raw_headers += headers or []
    await send({"type": "http.response.start", "status": status, "headers": raw_headers})
    await send({"type": "http.response.body", "body": payload})


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit_message = {
            "error": {
                "code": "payload_too_large",
                "message": f"Request body exceeds {self.max_bytes // (1024 * 1024)} MiB.",
                "request_id": None,
            }
        }
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await _send_json(send, 413, limit_message)
                    return

        received = 0
        exceeded = False
        replied = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # Stop reading; the application sees a disconnect and whatever it
                    # tries to answer is replaced by a 413 below.
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal replied
            if exceeded:
                if not replied:
                    replied = True
                    await _send_json(send, 413, limit_message)
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not replied:
            await _send_json(send, 413, limit_message)


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        per_minute: int,
        *,
        trust_proxy_headers: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.per_minute = per_minute
        self.trust_proxy_headers = trust_proxy_headers
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _client(self, scope: Scope) -> str:
        if self.trust_proxy_headers:
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-for":
                    return str(value.decode("latin-1")).split(",")[0].strip()
        client = scope.get("client")
        return str(client[0]) if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or self.per_minute <= 0
            or scope.get("method", "GET") not in MUTATING_METHODS
        ):
            await self.app(scope, receive, send)
            return
        key = self._client(scope)
        now = self.clock()
        with self._lock:
            window = self._hits[key]
            while window and window[0] <= now - 60.0:
                window.popleft()
            if len(window) >= self.per_minute:
                retry_after = max(1, int(60.0 - (now - window[0])) + 1)
                allowed = False
            else:
                window.append(now)
                allowed = True
            if len(self._hits) > 10_000:  # bound memory: drop idle clients
                for idle in [k for k, v in self._hits.items() if not v]:
                    del self._hits[idle]
        if not allowed:
            await _send_json(
                send,
                429,
                {
                    "error": {
                        "code": "rate_limited",
                        "message": f"Too many requests; limit is {self.per_minute} per minute.",
                        "request_id": None,
                    }
                },
                headers=[(b"retry-after", str(retry_after).encode())],
            )
            return
        await self.app(scope, receive, send)


SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-resource-policy", b"same-site"),
]
API_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_api = scope.get("path", "").startswith("/api/")

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += SECURITY_HEADERS
                if is_api:
                    headers.append(API_CSP)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, with_headers)
