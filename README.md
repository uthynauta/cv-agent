# Banorte Agent

Initial project workspace for the Banorte agent.

## Status

Project repository initialized. Implementation details, setup steps, and usage notes should be added as the project takes shape.

## Local Development

```bash
uv run --extra dev pytest
uv run uvicorn banorte_agent.main:app --reload
```

Runtime configuration is read from environment variables. Start from `.env.example` and keep real `.env` files out of Git.
