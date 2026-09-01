# Demo

## Walkthrough

A fresh `DATA_DIR` starts with empty mounted storage and reports not ready. After an authenticated upload, the service stores the original document and commits normalized Markdown to the local repository.

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Set `ADMIN_API_KEY`, upload a synthetic CV document, then retry readiness:

```bash
curl -sS http://localhost:8000/admin/documents \
  -H 'Authorization: Bearer YOUR_ADMIN_API_KEY' \
  -F 'file=@/path/to/example-cv.md'
curl http://localhost:8000/readyz
curl -sS http://localhost:8000/v1/responses \
  -H 'Content-Type: application/json' \
  -d '{"input":"Resume el perfil profesional del candidato."}'
```

Use `INGESTION_MODE=deterministic` for repeatable local demonstrations without model synthesis. Use a real OpenAI key only when demonstrating generated knowledge or live answers.

The browser dashboard is available at `http://localhost:8000/admin/login` when UI settings are configured. It supports local uploads and storage status; there is no remote publishing action.

