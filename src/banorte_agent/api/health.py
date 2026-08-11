from pathlib import Path
import re

from fastapi import APIRouter, Response, status
from fastapi.responses import PlainTextResponse

from banorte_agent.config import Settings, get_settings
from banorte_agent.metrics import render_metrics
from banorte_agent.wiki.frontmatter import load_frontmatter



def build_health_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz(response: Response) -> dict[str, object]:
        missing: list[str] = []
        if not settings.openai_api_key:
            missing.append("OPENAI_API_KEY")
        wiki_root = Path(settings.wiki_dir)
        index_path = wiki_root / "index.md"
        if not _readable_markdown(index_path):
            missing.append("wiki/index.md")
        if not _has_usable_generated_page(wiki_root):
            missing.append("wiki/generated-pages")
        if missing:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "missing": missing}
        return {"status": "ready", "missing": []}

    @router.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics().decode("utf-8"), media_type="text/plain; version=0.0.4")

    return router


def _readable_markdown(path: Path) -> bool:
    try:
        return path.is_file() and bool(path.read_text(encoding="utf-8").strip())
    except OSError:
        return False


def _has_usable_generated_page(wiki_root: Path) -> bool:
    for directory in ("sources", "entities", "concepts", "projects", "skills", "questions"):
        for path in (wiki_root / directory).glob("*.md"):
            try:
                _, body = load_frontmatter(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]{3,}", body):
                return True
    return False


router = build_health_router(get_settings())
