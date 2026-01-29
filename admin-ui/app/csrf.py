"""CSRF protection middleware for PowerBlockade.

Uses the Double Submit Cookie pattern via starlette-csrf.
"""

from __future__ import annotations

import secrets
from typing import Callable, Literal

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

SameSite = Literal["lax", "strict", "none"]


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection using Double Submit Cookie pattern.

    - Sets a `csrf_token` cookie on first request
    - Validates that POST/PUT/PATCH/DELETE requests include a matching token
      in either a form field `csrf_token` or header `X-CSRF-Token`
    - Exempts safe methods (GET, HEAD, OPTIONS, TRACE)
    - Exempts configured paths (e.g., API endpoints with their own auth)
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
    COOKIE_NAME = "csrf_token"
    FORM_FIELD = "csrf_token"
    HEADER_NAME = "X-CSRF-Token"
    TOKEN_LENGTH = 32

    def __init__(
        self,
        app,
        secret_key: str,
        exempt_paths: list[str] | None = None,
        cookie_secure: bool = False,
        cookie_samesite: SameSite = "lax",
    ):
        super().__init__(app)
        self.secret_key = secret_key
        self.exempt_paths = exempt_paths or []
        self.cookie_secure = cookie_secure
        self.cookie_samesite: SameSite = cookie_samesite

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate CSRF token
        csrf_token = request.cookies.get(self.COOKIE_NAME)
        if not csrf_token:
            csrf_token = secrets.token_hex(self.TOKEN_LENGTH)

        # Store token in request state for templates
        request.state.csrf_token = csrf_token

        # Check if path is exempt
        if self._is_exempt(request):
            response = await call_next(request)
            return self._set_cookie_if_needed(response, csrf_token, request)

        # Safe methods don't need CSRF validation
        if request.method in self.SAFE_METHODS:
            response = await call_next(request)
            return self._set_cookie_if_needed(response, csrf_token, request)

        # Validate CSRF token for state-changing requests
        submitted_token = await self._get_submitted_token(request)
        if not submitted_token or not secrets.compare_digest(csrf_token, submitted_token):
            return Response(
                content="CSRF token missing or invalid",
                status_code=403,
                media_type="text/plain",
            )

        response = await call_next(request)
        return self._set_cookie_if_needed(response, csrf_token, request)

    def _is_exempt(self, request: Request) -> bool:
        """Check if the request path is exempt from CSRF protection."""
        path = request.url.path
        for exempt in self.exempt_paths:
            if path.startswith(exempt):
                return True
        return False

    async def _get_submitted_token(self, request: Request) -> str | None:
        """Extract CSRF token from form data or header."""
        # Check header first (for AJAX requests)
        token = request.headers.get(self.HEADER_NAME)
        if token:
            return token

        # Check form data
        try:
            # Need to read body for form data
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                form = await request.form()
                token = form.get(self.FORM_FIELD)
                if token:
                    return str(token)
            elif "multipart/form-data" in content_type:
                form = await request.form()
                token = form.get(self.FORM_FIELD)
                if token:
                    return str(token)
        except Exception:
            pass

        return None

    def _set_cookie_if_needed(
        self, response: Response, csrf_token: str, request: Request
    ) -> Response:
        if not request.cookies.get(self.COOKIE_NAME):
            response.set_cookie(
                self.COOKIE_NAME,
                csrf_token,
                httponly=False,
                secure=self.cookie_secure,
                samesite="lax",
                max_age=86400 * 7,
            )
        return response


def csrf_token_input(request: Request) -> str:
    """Generate a hidden input field with the CSRF token for templates."""
    token = getattr(request.state, "csrf_token", "")
    return f'<input type="hidden" name="csrf_token" value="{token}">'
