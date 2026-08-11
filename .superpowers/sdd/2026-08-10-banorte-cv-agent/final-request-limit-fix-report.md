# Final Request-Limit Fix

Status: implemented.

- `/v1/responses` now enforces a 16 KiB request-body ceiling before JSON/Pydantic parsing and returns HTTP 413 when exceeded.
- The ceiling is configurable through `PUBLIC_REQUEST_BODY_LIMIT_BYTES`.
- The optional request `model` field is limited to 128 characters; overlong values return HTTP 422.
- README documents the body and field limits.
- Added regression tests for HTTP 413 and HTTP 422 behavior.

Verification:

- `uv run pytest tests/test_response_schema.py -q`: 7 passed.
- `uv run pytest`: 57 passed.
- `git diff --check`: passed.

Residual concerns: the request-size middleware is intentionally scoped to the public `/v1/responses` route; admin and health endpoints retain their existing behavior. Live OpenAI/evaluation calls were not run.
