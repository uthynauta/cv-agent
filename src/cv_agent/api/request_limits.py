from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse


async def public_request_size_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]], limit: int
) -> Response:
    if request.url.path != "/v1/responses":
        return await call_next(request)

    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                return _too_large_response(limit)
        except ValueError:
            pass

    messages: list[dict[str, object]] = []
    body_size = 0
    while True:
        message = await request.receive()
        messages.append(message)
        if message["type"] == "http.request":
            body_size += len(message.get("body", b""))
            if body_size > limit:
                return _too_large_response(limit)
        if not message.get("more_body", False):
            break

    async def replay_receive() -> dict[str, object]:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    request._receive = replay_receive
    return await call_next(request)


def _too_large_response(limit: int) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": f"request body exceeds {limit} bytes"},
    )
