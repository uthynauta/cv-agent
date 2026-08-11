import json
import logging
import re
import time
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from banorte_agent.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("banorte_agent")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


async def request_observability_middleware(request: Request, call_next):
    request_id = _request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    start = time.perf_counter()
    response: Response
    try:
        response = await call_next(request)
    except Exception:
        response = JSONResponse(
            status_code=500,
            content={"detail": "internal server error", "request_id": request_id},
        )
    route = _route_template(request)
    elapsed = time.perf_counter() - start
    HTTP_REQUESTS.labels(request.method, route, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, route).observe(elapsed)
    response.headers["x-request-id"] = request_id
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "route": route,
                "status": response.status_code,
                "latency_seconds": round(elapsed, 6),
            }
        )
    )
    return response


def _request_id(candidate: str | None) -> str:
    if candidate and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", candidate):
        return candidate
    return f"req_{uuid4().hex}"


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) and path.startswith("/") else "unmatched"
