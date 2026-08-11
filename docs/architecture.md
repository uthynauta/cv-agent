# Architecture

The Banorte CV Agent is a Dockerized FastAPI service. It exposes an Open Responses-like `/v1/responses` endpoint, searches a local Obsidian-style Markdown wiki, calls OpenAI, and returns Spanish answers with visible wiki citations.

The system separates raw sources from generated knowledge. LaTeX CV files under `wiki/raw/` can be committed. PDFs and other full documents under `wiki/raw/` are local-only. Generated Markdown pages under `wiki/sources`, `wiki/entities`, `wiki/concepts`, `wiki/projects`, `wiki/skills`, and `wiki/questions` are committed.

MVP retrieval is lexical search over Markdown. This keeps the system transparent and easy to operate for the challenge. The search module has a narrow interface so embeddings can be added after the MVP.
