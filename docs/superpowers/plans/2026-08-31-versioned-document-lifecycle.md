# Versioned Document Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use $subagent-driven-development (recommended) or $executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transactional replacement/deletion/rebuild, immutable retrieval snapshots, local Git history, and safe rollback.

**Architecture:** `DocumentService` serializes mutations with a cross-process lock, builds and validates staged state, commits versioned Markdown, then swaps an immutable active index. Rollback materializes an older tree as a new commit and quarantines binary originals that do not match restored source hashes.

**Tech Stack:** Python 3.12+, stdlib `fcntl`/`threading`/`shutil`, Git CLI, FastAPI, pytest.

---

## File Structure

- Create `src/cv_agent/knowledge/index.py`: immutable snapshots and atomic activation.
- Create `src/cv_agent/knowledge/locking.py`: non-blocking process lock.
- Create `src/cv_agent/knowledge/validation.py`: staged validation.
- Create `src/cv_agent/knowledge/documents_service.py`: lifecycle transaction coordinator.
- Extend `src/cv_agent/knowledge/git_store.py`: history and tree materialization.
- Modify `src/cv_agent/api/admin.py`: lifecycle routes.
- Add focused service/API tests.

### Task 1: Immutable Active Knowledge

**Files:**
- Create: `src/cv_agent/knowledge/index.py`
- Modify: `src/cv_agent/knowledge/search.py`
- Modify: `src/cv_agent/main.py`
- Test: `tests/test_knowledge_index.py`

- [ ] **Step 1: Write failing snapshot tests**

```python
def test_disk_change_requires_reload(repository):
    repository.write_page("knowledge/python.md", "Python", {"kind": "skill"}, "FastAPI")
    active = ActiveKnowledge.load(repository)
    repository.write_page("knowledge/rust.md", "Rust", {"kind": "skill"}, "Systems")
    assert active.search("Rust") == []
    active.reload(repository)
    assert [hit.title for hit in active.search("Rust")] == ["Rust"]


def test_failed_reload_keeps_old_snapshot(repository, monkeypatch):
    repository.write_page("knowledge/python.md", "Python", {"kind": "skill"}, "FastAPI")
    active = ActiveKnowledge.load(repository)
    monkeypatch.setattr(KnowledgeSnapshot, "from_repository", classmethod(
        lambda cls, repo: (_ for _ in ()).throw(ValueError("invalid"))
    ))
    with pytest.raises(ValueError):
        active.reload(repository)
    assert active.search("FastAPI")
```

- [ ] **Step 2: Verify missing types**

```bash
uv run --extra dev pytest tests/test_knowledge_index.py -q
```

Expected: FAIL because snapshot types do not exist.

- [ ] **Step 3: Implement snapshot types**

```python
@dataclass(frozen=True)
class KnowledgeSnapshot:
    pages: tuple[KnowledgePage, ...]

    @classmethod
    def from_repository(cls, repository: KnowledgeRepository) -> "KnowledgeSnapshot":
        return cls(tuple(repository.list_pages()))

    def list_pages(self) -> list[KnowledgePage]:
        return list(self.pages)


class ActiveKnowledge:
    def __init__(self, snapshot: KnowledgeSnapshot) -> None:
        self._snapshot = snapshot
        self._lock = Lock()

    @classmethod
    def load(cls, repository: KnowledgeRepository) -> "ActiveKnowledge":
        return cls(KnowledgeSnapshot.from_repository(repository))

    def reload(self, repository: KnowledgeRepository) -> None:
        candidate = KnowledgeSnapshot.from_repository(repository)
        with self._lock:
            self._snapshot = candidate

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        with self._lock:
            snapshot = self._snapshot
        return KnowledgeSearch(snapshot).search(query, limit)

    @property
    def initialized(self) -> bool:
        with self._lock:
            return bool(self._snapshot.pages)
```

Use `KnowledgePage` consistently. Type `KnowledgeSearch` against a `PageSource` protocol exposing `list_pages()`.

- [ ] **Step 4: Inject and verify**

Build one `ActiveKnowledge` in `create_app`; use it for answers/readiness.

```bash
uv run --extra dev pytest tests/test_knowledge_index.py tests/test_search.py tests/test_agent_service.py tests/test_health.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cv_agent tests/test_knowledge_index.py
git commit -m "refactor(search): activate immutable snapshots"
```

### Task 2: Mutation Lock And Validation

**Files:**
- Create: `src/cv_agent/knowledge/locking.py`
- Create: `src/cv_agent/knowledge/validation.py`
- Test: `tests/test_knowledge_locking.py`
- Test: `tests/test_knowledge_validation.py`

- [ ] **Step 1: Write failing tests**

```python
def test_second_lock_fails_without_waiting(tmp_path):
    first = MutationLock(tmp_path / "locks" / "mutation.lock")
    second = MutationLock(tmp_path / "locks" / "mutation.lock")
    with first:
        with pytest.raises(MutationBusyError):
            with second:
                pass


def test_validation_requires_source_identity(tmp_path):
    (tmp_path / "sources").mkdir()
    (tmp_path / "sources" / "bad.md").write_text(
        "---\nkind: source\n---\n# Bad\n", encoding="utf-8"
    )
    with pytest.raises(KnowledgeValidationError, match="document_id"):
        validate_knowledge(tmp_path)
```

- [ ] **Step 2: Verify missing modules**

```bash
uv run --extra dev pytest tests/test_knowledge_locking.py tests/test_knowledge_validation.py -q
```

Expected: FAIL because modules are missing.

- [ ] **Step 3: Implement non-blocking lock**

```python
class MutationBusyError(RuntimeError):
    pass


class MutationLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: IO[str] | None = None

    def __enter__(self) -> "MutationLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise MutationBusyError("another knowledge mutation is running") from exc
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        assert self._handle is not None
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None
```

- [ ] **Step 4: Implement validation**

`validate_knowledge(root)` loads all Markdown with the existing frontmatter parser. Require every source page to have `kind: source`, unique `document_id`, lowercase 64-hex `content_sha256`, and non-empty `## Extracted Text`. Reject escaped paths and unknown generated-page source references. Errors contain only bounded path/field data.

- [ ] **Step 5: Verify**

```bash
uv run --extra dev pytest tests/test_knowledge_locking.py tests/test_knowledge_validation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cv_agent/knowledge/locking.py src/cv_agent/knowledge/validation.py tests/test_knowledge_locking.py tests/test_knowledge_validation.py
git commit -m "feat(storage): lock and validate mutations"
```

### Task 3: Transactional Lifecycle Service

**Files:**
- Create: `src/cv_agent/knowledge/documents_service.py`
- Modify: `src/cv_agent/knowledge/ingest.py`
- Modify: `src/cv_agent/knowledge/git_store.py`
- Modify: `src/cv_agent/main.py`
- Test: `tests/test_document_service.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_replace_preserves_id_and_changes_search(document_service):
    first = document_service.add("candidate.md", b"Python")
    second = document_service.replace(first.document_id, "candidate.md", b"Rust")
    assert second.document_id == first.document_id
    assert second.content_sha256 != first.content_sha256
    assert document_service.active.search("Rust")
    assert document_service.active.search("Python") == []


def test_failure_preserves_head_and_index(document_service, monkeypatch):
    added = document_service.add("candidate.md", b"Python")
    monkeypatch.setattr(document_service, "_validate_staged", lambda path: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(DocumentMutationError):
        document_service.replace(added.document_id, "candidate.md", b"Rust")
    assert document_service.git.head() == added.commit
    assert document_service.active.search("Python")
```

- [ ] **Step 2: Verify missing service**

```bash
uv run --extra dev pytest tests/test_document_service.py -q
```

Expected: FAIL because `DocumentService` is missing.

- [ ] **Step 3: Define lifecycle records**

```python
@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    original_filename: str
    media_type: str
    content_sha256: str
    uploaded_at: str
    original_available: bool


@dataclass(frozen=True)
class MutationResult:
    document_id: str
    content_sha256: str
    commit: str
    changed_paths: tuple[str, ...]
```

- [ ] **Step 4: Implement shared transaction**

All `add`, `replace`, `delete`, and `rebuild` methods call `_mutate(operation)`: lock; copy Markdown to staging; stage original changes; extract/ingest; regenerate affected knowledge; validate; record prior head/originals; rename live Markdown directories; commit once; build candidate snapshot; activate originals and index. Any post-replacement error restores prior Git work tree, originals, and snapshot. Always remove staging. Rebuild uses versioned full source text, not original binaries.

Extend `LocalKnowledgeGit` with `restore_head(expected_current: str, prior: str) -> None`. It validates both full commit IDs, atomically moves `refs/heads/main` from `expected_current` to `prior` with `git update-ref`, then restores only `sources/` and `knowledge/` from `prior`. This method is transaction compensation only; user-requested rollback in Task 4 creates a new audit commit.

- [ ] **Step 5: Test every failure boundary**

Inject validation, Git commit, original activation, and snapshot build failures. Each must preserve prior head, inventory, and search.

```bash
uv run --extra dev pytest tests/test_document_service.py tests/test_knowledge_index.py tests/test_git_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cv_agent/knowledge src/cv_agent/main.py tests/test_document_service.py tests/test_knowledge_index.py tests/test_git_store.py
git commit -m "feat(storage): transact document changes"
```

### Task 4: Local History And Safe Rollback

**Files:**
- Modify: `src/cv_agent/knowledge/git_store.py`
- Modify: `src/cv_agent/knowledge/documents_service.py`
- Test: `tests/test_git_history.py`

- [ ] **Step 1: Write failing tests**

```python
def test_history_is_newest_first(document_service):
    first = document_service.add("candidate.md", b"Python")
    second = document_service.replace(first.document_id, "candidate.md", b"Rust")
    assert [item.commit for item in document_service.history(10)[:2]] == [second.commit, first.commit]


def test_rollback_creates_commit_and_quarantines_wrong_binary(document_service):
    first = document_service.add("candidate.pdf", b"first PDF")
    second = document_service.replace(first.document_id, "candidate.pdf", b"second PDF")
    rolled_back = document_service.rollback(first.commit, confirmed=True)
    assert rolled_back.commit not in {first.commit, second.commit}
    assert document_service.list_documents()[0].original_available is False
    assert list(document_service.paths.quarantine.rglob("*.pdf"))
```

- [ ] **Step 2: Verify missing history API**

```bash
uv run --extra dev pytest tests/test_git_history.py -q
```

Expected: FAIL.

- [ ] **Step 3: Extend bounded Git API**

Add immutable `Revision` fields `commit`, `authored_at`, `subject`, and `changed_paths`. Add typed methods `history(limit: int = 20) -> list[Revision]`, `contains_commit(commit: str) -> bool`, and `checkout_tree(commit: str, destination: Path) -> None`.

Require full lowercase 40-hex commit IDs, cap history at 100, parse paths with NUL delimiters, and allow only `sources/` and `knowledge/` paths.

- [ ] **Step 4: Implement rollback as a normal transaction**

Materialize target tree in staging, validate it, activate it, then commit `Rollback knowledge to <short-sha>`. Compare current originals with restored `content_sha256`; move mismatches to `documents/quarantine/<operation-id>/`. Require `confirmed=True`; do not reset history backward.

- [ ] **Step 5: Verify**

```bash
uv run --extra dev pytest tests/test_git_history.py tests/test_document_service.py tests/test_git_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cv_agent/knowledge tests/test_git_history.py tests/test_document_service.py tests/test_git_store.py
git commit -m "feat(storage): add local revision rollback"
```

### Task 5: Lifecycle Admin API

**Files:**
- Modify: `src/cv_agent/api/models.py`
- Modify: `src/cv_agent/api/admin.py`
- Modify: `src/cv_agent/main.py`
- Create: `tests/test_admin_lifecycle.py`
- Modify: `tests/test_admin.py`

- [ ] **Step 1: Write failing route tests**

```python
def test_document_crud_and_rebuild(admin_client):
    created = admin_client.upload("candidate.md", b"Python")
    document_id = created["document"]["document_id"]
    assert admin_client.get("/admin/documents").json()["documents"][0]["document_id"] == document_id
    assert admin_client.put_file(f"/admin/documents/{document_id}", "candidate.md", b"Rust").status_code == 200
    assert admin_client.post("/admin/rebuild").status_code == 200
    assert admin_client.delete(f"/admin/documents/{document_id}", json={"confirm": True}).status_code == 200


def test_rollback_requires_confirmation(admin_client):
    commit = admin_client.upload("candidate.md", b"Python")["revision"]["commit"]
    response = admin_client.post(f"/admin/revisions/{commit}/rollback", json={"confirm": False})
    assert response.status_code == 409
```

- [ ] **Step 2: Verify missing routes**

```bash
uv run --extra dev pytest tests/test_admin_lifecycle.py -q
```

Expected: FAIL.

- [ ] **Step 3: Add model and routes**

```python
class ConfirmationRequest(BaseModel):
    confirm: bool = False
```

Expose authenticated routes:

```text
GET    /admin/documents
POST   /admin/documents
PUT    /admin/documents/{document_id}
DELETE /admin/documents/{document_id}
POST   /admin/rebuild
GET    /admin/revisions?limit=20
POST   /admin/revisions/{commit}/rollback
```

Map not-found to `404`, confirmation/lock contention to `409`, invalid source/knowledge to `422`, upload size to `413`, and redacted mutation failure to `503` with operation ID.

- [ ] **Step 4: Replace status payload**

Return generic `storage`, `knowledge`, and `ingestion` objects with writability, initialization, document count, and active commit. Never return absolute data paths, document text, secrets, or Git stderr.

- [ ] **Step 5: Verify**

```bash
uv run --extra dev pytest tests/test_admin.py tests/test_admin_lifecycle.py tests/test_document_service.py tests/test_git_history.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/cv_agent/api src/cv_agent/main.py tests/test_admin.py tests/test_admin_lifecycle.py
git commit -m "feat(admin): manage versioned documents"
```

### Task 6: Integration Verification

**Files:**
- Modify only files required by observed failures.

- [ ] **Step 1: Run all tests**

```bash
uv run --extra dev pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Repeat lifecycle tests**

```bash
for run in {1..10}; do uv run --extra dev pytest tests/test_document_service.py tests/test_admin_lifecycle.py -q || exit 1; done
```

Expected: ten successful runs.

- [ ] **Step 3: Assert Git tracks Markdown only**

Add an end-to-end test that uploads and replaces a synthetic PDF, reads `LocalKnowledgeGit.tracked_paths()`, and asserts every path ends in `.md` and begins with `sources/` or `knowledge/`.

- [ ] **Step 4: Commit observed fixes only**

```bash
git add src tests
git diff --cached --quiet || git commit -m "fix(storage): stabilize lifecycle integration"
```
