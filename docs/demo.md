# Demo

## What To Show

1. `wiki/` contains generated Obsidian-style Markdown pages from source CV material.
2. `POST /v1/responses` is the Open Responses-like API and returns Spanish answers with `Fuentes:` wiki citations when configured with a real OpenAI key.
3. `/healthz`, `/readyz`, and `/metrics` show operational readiness and observability.
4. Docker Compose runs the service locally without Kubernetes.
5. `evals/run_eval.py` validates Spanish output, visible citations, and missing-information behavior; do not run it against OpenAI without a real key.

## Local Walkthrough

```bash
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
```

Use `http://localhost:8000/v1/responses` during local development. Banorte platform URL and registration details are pending; when available, register the public URL's `/v1/responses` path.

## Example Questions

- "Resume el perfil profesional de Othon."
- "¿Qué experiencia tiene Othon construyendo agentes de IA?"
- "¿Qué proyectos demuestran criterio técnico?"
- "¿Qué información no está disponible en las fuentes?"
