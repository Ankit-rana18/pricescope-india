"""Request ID propagation, access logging, security headers and a request-size cap."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger("access")

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # JSON API: nothing here should ever render as a page or load sub-resources.
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
# Swagger UI and ReDoc load their own scripts and styles, so they keep the browser defaults.
_DOCS_PATHS = ("/docs", "/redoc")
HSTS = "max-age=63072000; includeSubDomains"


class RequestContextMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        # Only trust well-formed client IDs, so logs cannot be polluted.
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = request_id
        for name, value in SECURITY_HEADERS.items():
            if name == "Content-Security-Policy" and request.url.path.startswith(_DOCS_PATHS):
                continue
            response.headers.setdefault(name, value)
        if self._hsts:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        if "authorization" in request.headers:
            # Per-user answers must never be stored by shared caches.
            response.headers["Cache-Control"] = "private, no-store"
        log.info(
            "request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response


class BodySizeLimitMiddleware:
    """Reject request bodies over ``max_bytes`` with 413, including chunked uploads that
    send no Content-Length (counted as they stream in)."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await self._reject(scope, receive, send)
            return

        received = 0
        too_large = False
        replaced = False

        async def counting_receive() -> Message:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    too_large = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            # Frameworks may catch our signal and answer with their own error (FastAPI
            # sends 400 "error parsing the body"); swap that for the real reason.
            nonlocal replaced
            if too_large:
                if not replaced:
                    replaced = True
                    await self._reject(scope, receive, send)
                return
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not too_large:
                raise
            if not replaced:
                await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": f"Request body is larger than {self.max_bytes} bytes.",
                    "details": None,
                    "request_id": None,
                }
            },
        )
        await response(scope, receive, send)


class _BodyTooLarge(Exception):
    pass
