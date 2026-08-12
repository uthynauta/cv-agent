# Demo

## What To Show

1. `wiki/` contains cleaned, generated Obsidian-style Markdown from committed LaTeX CV sources.
2. The Continental/radar query retrieves a matching experience passage rather than the generic profile header.
3. `POST /v1/responses` returns terminal Open Responses-compatible JSON with Spanish answers and retrieved `Fuentes:` citations.
4. Answers are concise by default and include one grounded follow-up question when useful.
5. Transcript replay supports follow-ups such as `si por favor` without server-side conversation storage.
6. `/healthz`, `/readyz`, and `/metrics` show liveness, strict readiness, bounded route metrics, search hits, and OpenAI latency.
7. Docker Compose runs the service locally without Kubernetes.
8. `evals/run_eval.py` checks Spanish output, citations, and missing-information behavior; do not run it without a real key.

## Local Walkthrough

```bash
uv run uvicorn banorte_agent.main:app --host 127.0.0.1 --port 8000
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Call examples with and without `AGENT_API_KEY` are in the [README](../README.md) and [deployment guide](deployment.md). `POST /admin/ingest` remains disabled until `ADMIN_API_KEY` is set.

Use `http://localhost:8000/v1/responses` during local development. The public Render deployment is:

```text
https://banorte-cv-agent.onrender.com/v1/responses
```

The agent card is:

```text
https://banorte-cv-agent.onrender.com/.well-known/agent-card.json
```

## Example Questions

- "Resume el perfil profesional de Othon."
- "¿Qué experiencia tiene Othon construyendo agentes de IA?"
- "¿Qué hizo Othon en Continental con radares?"
- "¿Qué proyectos demuestran criterio técnico?"
- "¿Qué información no está disponible en las fuentes?"
- "¿En qué empresas ha laborado?"
- "Sí, por favor."

## Banorte Platform Notes

Use transcript replay/stateless mode. The API extracts the latest reviewer message and keeps bounded prior context only for follow-up references. If the platform offers capability content as inline Base64, prefer it so the agent is not required to fetch Parley during execution.
