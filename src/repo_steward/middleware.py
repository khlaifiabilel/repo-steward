"""ASGI request limits, correlation IDs, and sanitized request logging."""

import json
import logging
import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class BodyTooLargeError(Exception):
    """The receive stream exceeded the configured body limit."""


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        supplied_id = headers.get(b"x-correlation-id", b"").decode("ascii", errors="ignore")
        correlation_id = (
            supplied_id if _CORRELATION_RE.fullmatch(supplied_id) else str(uuid.uuid4())
        )
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        response_started = False
        status_code = 500
        body_too_large = False

        async def send_with_context(message: Message) -> None:
            nonlocal response_started, status_code
            if body_too_large:
                return
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (b"x-correlation-id", correlation_id.encode("ascii"))
                )
            await send(message)

        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._error(send_with_context, 400, "Invalid Content-Length")
                self._log(scope, correlation_id, 400)
                return
            if declared_length < 0:
                await self._error(send_with_context, 400, "Invalid Content-Length")
                self._log(scope, correlation_id, 400)
                return
            if declared_length > self.max_body_bytes:
                await self._error(send_with_context, 413, "Request body too large")
                self._log(scope, correlation_id, 413)
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal body_too_large, received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    body_too_large = True
                    raise BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send_with_context)
            if body_too_large:
                status_code = 413
                body_too_large = False
                await self._error(send_with_context, 413, "Request body too large")
        except BodyTooLargeError:
            if response_started:
                raise
            status_code = 413
            body_too_large = False
            await self._error(send_with_context, 413, "Request body too large")
        except Exception:
            logger.exception(
                "Request failed",
                extra={
                    "correlation_id": correlation_id,
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                },
            )
            if response_started:
                raise
            status_code = 500
            await self._error(send_with_context, 500, "Internal server error")
        finally:
            self._log(scope, correlation_id, status_code)

    @staticmethod
    async def _error(send: Send, status_code: int, detail: str) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _log(scope: Scope, correlation_id: str, status_code: int) -> None:
        logger.info(
            "Request completed",
            extra={
                "correlation_id": correlation_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status_code": status_code,
            },
        )
