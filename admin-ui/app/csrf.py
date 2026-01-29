"""CSRF protection middleware for PowerBlockade.

Uses the Double Submit Cookie pattern. For form submissions, the CSRF token
must be sent via X-CSRF-Token header OR via a hidden form field.

NOTE: Reading form data in middleware consumes the request body, preventing
FastAPI's Form() from reading it downstream. To avoid this, we read the raw
body, parse it ourselves, and inject the data back into the request scope.
"""

from __future__ import annotations

import secrets
from typing import Literal
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SameSite = Literal["lax", "strict", "none"]

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
COOKIE_NAME = "csrf_token"
FORM_FIELD = "csrf_token"
HEADER_NAME = "X-CSRF-Token"
TOKEN_LENGTH = 32


class CSRFMiddleware:
    """Pure ASGI CSRF middleware that preserves request body for downstream handlers."""

    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        exempt_paths: list[str] | None = None,
        cookie_secure: bool = False,
        cookie_samesite: SameSite = "lax",
    ):
        self.app = app
        self.secret_key = secret_key
        self.exempt_paths = exempt_paths or []
        self.cookie_secure = cookie_secure
        self.cookie_samesite: SameSite = cookie_samesite

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        method = scope.get("method", "GET")

        csrf_token = request.cookies.get(COOKIE_NAME)
        if not csrf_token:
            csrf_token = secrets.token_hex(TOKEN_LENGTH)

        scope.setdefault("state", {})
        scope["state"]["csrf_token"] = csrf_token

        if self._is_exempt(scope) or method in SAFE_METHODS:
            await self._call_with_cookie(scope, receive, send, csrf_token, request)
            return

        submitted_token = request.headers.get(HEADER_NAME)

        if not submitted_token:
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                body_bytes = await self._read_body(receive)
                scope["_body"] = body_bytes

                try:
                    parsed = parse_qs(body_bytes.decode("utf-8"), keep_blank_values=True)
                    csrf_values = parsed.get(FORM_FIELD, [])
                    if csrf_values:
                        submitted_token = csrf_values[0]
                except Exception:
                    pass

                async def cached_receive() -> Message:
                    return {"type": "http.request", "body": scope["_body"], "more_body": False}

                receive = cached_receive

        if not submitted_token or not secrets.compare_digest(csrf_token, submitted_token):
            response = Response(
                content="CSRF token missing or invalid",
                status_code=403,
                media_type="text/plain",
            )
            await response(scope, receive, send)
            return

        await self._call_with_cookie(scope, receive, send, csrf_token, request)

    def _is_exempt(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        for exempt in self.exempt_paths:
            if path.startswith(exempt):
                return True
        return False

    async def _read_body(self, receive: Receive) -> bytes:
        body_parts: list[bytes] = []
        while True:
            message = await receive()
            body_parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        return b"".join(body_parts)

    async def _call_with_cookie(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        csrf_token: str,
        request: Request,
    ) -> None:
        need_cookie = not request.cookies.get(COOKIE_NAME)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start" and need_cookie:
                headers = list(message.get("headers", []))
                cookie_value = (
                    f"{COOKIE_NAME}={csrf_token}; Path=/; SameSite=Lax; Max-Age={86400 * 7}"
                )
                if self.cookie_secure:
                    cookie_value += "; Secure"
                headers.append((b"set-cookie", cookie_value.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def csrf_token_input(request: Request) -> str:
    """Generate a hidden input field with the CSRF token for templates."""
    token = getattr(request.state, "csrf_token", "")
    return f'<input type="hidden" name="csrf_token" value="{token}">'
