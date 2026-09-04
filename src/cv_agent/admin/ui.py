import base64, hashlib, hmac, json, time
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.responses import Response
from cv_agent.admin.templates import dashboard_page, login_page
from cv_agent.api.admin import _backup_payload, build_admin_status_payload, replace_document_payload, upload_document_payload
from cv_agent.config import Settings
from cv_agent.knowledge.backup import BackupService, BackupTooLargeError
from cv_agent.knowledge.git_store import LocalKnowledgeGit
from cv_agent.knowledge.ingest import IngestionService
from cv_agent.knowledge.locking import MutationBusyError
from cv_agent.knowledge.restore import RestoreService
from cv_agent.knowledge.storage import DataPaths
from cv_agent.knowledge.documents_service import DocumentIdentifierError, DocumentNotFoundError, DocumentService, DocumentValidationError, RevisionNotFoundError

SESSION_COOKIE = "cv_agent_admin_session"

def build_admin_ui_router(settings: Settings, paths: DataPaths, git_store: LocalKnowledgeGit, ingestion: IngestionService, document_service: DocumentService, backup_service: BackupService | None = None, restore_service: RestoreService | None = None) -> APIRouter:
    router = APIRouter()
    backup_service = backup_service or BackupService(paths, git_store, settings)
    restore_service = restore_service or getattr(document_service, "restore_service", None) or RestoreService(paths, git_store, settings, document_service, backup_service)
    def enabled(): return bool(settings.admin_ui_password and settings.admin_ui_session_secret)
    def valid(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        if not token or "." not in token or not settings.admin_ui_session_secret: return False
        payload, signature = token.rsplit(".", 1)
        try:
            expected = hmac.new(settings.admin_ui_session_secret.encode(), payload.encode("ascii"), hashlib.sha256).digest()
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return hmac.compare_digest(base64.urlsafe_b64encode(expected).decode().rstrip("="), signature) and isinstance(data, dict) and isinstance(data.get("exp"), int) and data["exp"] >= int(time.time())
        except (ValueError, TypeError, UnicodeError, json.JSONDecodeError): return False
    def auth(request):
        if not enabled(): return JSONResponse({"detail":"admin UI is disabled"}, status_code=503)
        if not valid(request): return JSONResponse({"detail":"invalid session"}, status_code=401)
    async def confirm(request):
        try: return bool((await request.json()).get("confirm"))
        except (ValueError, TypeError): return False
    def error(exc):
        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if isinstance(exc, MutationBusyError): return JSONResponse({"detail":"another mutation is running"}, status_code=409)
        if isinstance(exc, (DocumentNotFoundError, RevisionNotFoundError)): return JSONResponse({"detail":"resource was not found"}, status_code=404)
        if isinstance(exc, (DocumentIdentifierError, DocumentValidationError, ValueError)): return JSONResponse({"detail":"request is invalid"}, status_code=422)
        if isinstance(exc, BackupTooLargeError): return JSONResponse({"detail":"backup exceeds configured size limit"}, status_code=413)
        return JSONResponse({"detail":"operation could not be completed"}, status_code=503)
    def make_token():
        now = int(time.time()); raw = base64.urlsafe_b64encode(json.dumps({"iat":now,"exp":now + settings.admin_ui_session_max_age_seconds}, separators=(",", ":")).encode()).decode().rstrip("=")
        sig = hmac.new(settings.admin_ui_session_secret.encode(), raw.encode(), hashlib.sha256).digest()
        return raw + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")
    @router.get("/admin/login", response_class=HTMLResponse)
    async def get_login():
        if not enabled(): return HTMLResponse("Admin UI is disabled", status_code=503)
        html, code = login_page(); return HTMLResponse(html, status_code=code)
    @router.post("/admin/login")
    async def post_login(request: Request):
        if not enabled(): return HTMLResponse("Admin UI is disabled", status_code=503)
        form = await request.form(); password = str(form.get("password", ""))
        if not hmac.compare_digest(password.encode(), settings.admin_ui_password.encode()):
            html, code = login_page("Invalid password", 401); return HTMLResponse(html, status_code=code)
        response = RedirectResponse("/admin/ui", status_code=303); response.set_cookie(SESSION_COOKIE, make_token(), httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/admin", max_age=settings.admin_ui_session_max_age_seconds); return response
    @router.post("/admin/logout")
    async def logout():
        response = RedirectResponse("/admin/login", status_code=303); response.delete_cookie(SESSION_COOKIE, path="/admin", samesite="lax"); return response
    @router.get("/admin/ui", response_class=HTMLResponse)
    async def dashboard(request: Request):
        if not enabled(): return HTMLResponse("Admin UI is disabled", status_code=503)
        return HTMLResponse(dashboard_page()) if valid(request) else RedirectResponse("/admin/login", status_code=303)
    @router.get("/admin/ui/status")
    async def ui_status(request: Request):
        if (r := auth(request)): return r
        return build_admin_status_payload(settings, paths, git_store, ingestion.repository, document_service)
    @router.get("/admin/ui/documents")
    async def ui_documents(request: Request):
        if (r := auth(request)): return r
        try: return {"status":"ok", "documents":[x.__dict__ for x in document_service.list_documents()]}
        except Exception as exc: return error(exc)
    @router.post("/admin/ui/documents")
    async def ui_add(request: Request, file: UploadFile = File(...)):
        if (r := auth(request)): return r
        try: return await upload_document_payload(settings, paths, git_store, ingestion, file, document_service)
        except Exception as exc: return error(exc)
    @router.put("/admin/ui/documents/{document_id}")
    async def ui_replace(request: Request, document_id: str, file: UploadFile = File(...)):
        if (r := auth(request)): return r
        try: return await replace_document_payload(settings, paths, file, document_id, document_service)
        except Exception as exc: return error(exc)
    @router.delete("/admin/ui/documents/{document_id}")
    async def ui_delete(request: Request, document_id: str):
        if (r := auth(request)): return r
        if not await confirm(request): return JSONResponse({"detail":"confirmation required"}, status_code=409)
        try: return {"status":"ok", "revision":{"commit":document_service.delete(document_id).commit}}
        except Exception as exc: return error(exc)
    @router.post("/admin/ui/rebuild")
    async def ui_rebuild(request: Request):
        if (r := auth(request)): return r
        try: return {"status":"ok", "revision":{"commit":document_service.rebuild().commit}}
        except Exception as exc: return error(exc)
    @router.get("/admin/ui/revisions")
    async def ui_revisions(request: Request):
        if (r := auth(request)): return r
        try: return {"status":"ok", "revisions":[{"commit":x.commit,"authored_at":x.authored_at,"subject":x.subject,"changed_paths":list(x.changed_paths)} for x in document_service.history(20)]}
        except Exception as exc: return error(exc)
    @router.post("/admin/ui/revisions/{commit}/rollback")
    async def ui_rollback(request: Request, commit: str):
        if (r := auth(request)): return r
        if not await confirm(request): return JSONResponse({"detail":"confirmation required"}, status_code=409)
        try: return {"status":"ok", "revision":{"commit":document_service.rollback(commit, confirmed=True).commit}}
        except Exception as exc: return error(exc)
    @router.get("/admin/ui/backups")
    async def ui_backups(request: Request):
        if (r := auth(request)): return r
        try: return {"status":"ok", "backups":[_backup_payload(x) for x in backup_service.list()]}
        except Exception as exc: return error(exc)
    async def create_backup(request: Request, kind: str):
        if (r := auth(request)): return r
        try: return {"status":"ok", "backup":_backup_payload(backup_service.create_knowledge_bundle() if kind == "knowledge" else backup_service.create_full_backup())}
        except Exception as exc: return error(exc)
    @router.post("/admin/ui/backups/knowledge")
    async def create_knowledge_backup(request: Request):
        return await create_backup(request, "knowledge")
    @router.post("/admin/ui/backups/full")
    async def create_full_backup(request: Request):
        return await create_backup(request, "full")
    @router.get("/admin/ui/backups/{name}")
    async def ui_download(request: Request, name: str):
        if (r := auth(request)): return r
        try:
            record, handle = backup_service.open_download(name); return StreamingResponse(handle, media_type="application/octet-stream", headers={"Content-Disposition":f'attachment; filename="{record.name}"'})
        except Exception as exc: return error(exc)
    @router.delete("/admin/ui/backups/{name}")
    async def ui_backup_delete(request: Request, name: str):
        if (r := auth(request)): return r
        if not await confirm(request): return JSONResponse({"detail":"confirmation required"}, status_code=409)
        try: backup_service.delete(name, confirmed=True); return {"status":"ok","name":name}
        except Exception as exc: return error(exc)
    @router.post("/admin/ui/restore")
    async def ui_restore(request: Request, file: UploadFile = File(...), confirm: bool = Form(False)):
        if (r := auth(request)): return r
        if not confirm: return JSONResponse({"detail":"confirmation required"}, status_code=409)
        target = paths.staging / f"ui-restore-{time.time_ns()}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(await file.read(settings.admin_backup_max_bytes + 1))
            if target.stat().st_size > settings.admin_backup_max_bytes: raise BackupTooLargeError()
            result = restore_service.restore_knowledge(target, confirmed=True) if (file.filename or "").lower().endswith(".bundle") else restore_service.restore_full(target, confirmed=True)
            return {"status":"ok","active_commit":result.active_commit,"quarantined":list(result.quarantined)}
        except Exception as exc: return error(exc)
        finally: target.unlink(missing_ok=True)
    return router
