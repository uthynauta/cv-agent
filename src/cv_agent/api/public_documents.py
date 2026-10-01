from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog


def build_public_documents_router(catalog: ProcessedPdfCatalog) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/documents/{document_id}/original")
    def original_document(document_id: str) -> StreamingResponse:
        verified = catalog.open_pdf(document_id)
        if verified is None:
            raise HTTPException(status_code=404, detail="document not found")
        return StreamingResponse(
            verified.iter_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{verified.filename}"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
            background=BackgroundTask(verified.close),
        )

    return router
