import secrets
from collections.abc import Awaitable, Callable
from typing import Any

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class RequestBodyTooLarge(Exception):
    """The HTTP request body exceeds the configured ingress limit."""


class RequestBodyLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_bytes: int,
        api_key: str | None = None,
        protected_paths: tuple[str, ...] = (),
    ):
        self.app = app
        self.max_bytes = max_bytes
        self.api_key = api_key
        self.protected_paths = protected_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if self._requires_api_key(scope) and not self._has_valid_api_key(scope):
            await self._send_unauthorized(send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_bytes:
            await self._send_too_large(send)
            return

        total = 0
        too_large = False

        async def limited_receive() -> Message:
            nonlocal total, too_large
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    too_large = True
                    await self._send_too_large(send)
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Message) -> None:
            if too_large:
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except RequestBodyTooLarge:
            await self._send_too_large(send)

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    def _requires_api_key(self, scope: Scope) -> bool:
        return scope.get("method") == "POST" and scope.get("path") in self.protected_paths

    def _has_valid_api_key(self, scope: Scope) -> bool:
        if not self.api_key:
            return False
        supplied_key = None
        for name, value in scope.get("headers", []):
            if name.lower() == b"x-api-key":
                supplied_key = value.decode("latin-1")
                break
        return bool(supplied_key) and secrets.compare_digest(supplied_key, self.api_key)

    @staticmethod
    async def _send_unauthorized(send: Send) -> None:
        body = b'{"detail":"Invalid API key"}'
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        body = b'{"detail":"Request exceeds the maximum allowed size"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
