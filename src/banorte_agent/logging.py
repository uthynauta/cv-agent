import json
import logging
import time
from uuid import uuid4

from fastapi import Request, Response

from banorte_agent.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("banorte_agent")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


async def request_observability_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
    start = time.perf_counter()
    response: Response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.method, path).observe(elapsed)
    response.headers["x-request-id"] = request_id
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "latency_seconds": round(elapsed, 6),
            }
        )
    )
    return response
