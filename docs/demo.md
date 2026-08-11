# Demo

## What To Show

1. `wiki/` contains cleaned, generated Obsidian-style Markdown from committed LaTeX CV sources.
2. The Continental/radar query retrieves a matching experience passage rather than the generic profile header.
3. `POST /v1/responses` returns Spanish answers with retrieved `Fuentes:` citations when configured with a real OpenAI key.
4. `/healthz`, `/readyz`, and `/metrics` show liveness, strict readiness, bounded route metrics, search hits, and OpenAI latency.
5. Docker Compose runs the service locally without Kubernetes.
6. `evals/run_eval.py` checks Spanish output, citations, and missing-information behavior; do not run it without a real key.

## Local Walkthrough

```bash
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Call examples with and without `AGENT_API_KEY` are in the [README](../README.md) and [deployment guide](deployment.md). `POST /admin/ingest` remains disabled until `ADMIN_API_KEY` is set.

Use `http://localhost:8000/v1/responses` during local development. No live OpenAI key, public deployment, Banorte platform URL, or confirmed Banorte registration contract is currently available.

## Example Questions

- "Resume el perfil profesional de Othon."
- "¿Qué experiencia tiene Othon construyendo agentes de IA?"
- "¿Qué hizo Othon en Continental con radares?"
- "¿Qué proyectos demuestran criterio técnico?"
- "¿Qué información no está disponible en las fuentes?"
