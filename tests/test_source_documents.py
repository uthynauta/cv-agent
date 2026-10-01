from hashlib import sha256
from pathlib import Path

import pytest

from cv_agent.knowledge.index import ActiveKnowledge
from cv_agent.knowledge.public_pdfs import ProcessedPdfCatalog
from cv_agent.knowledge.repository import KnowledgeRepository
from cv_agent.knowledge.storage import ensure_data_storage


@pytest.fixture
def sources(tmp_path: Path):
    paths = ensure_data_storage(tmp_path / "data")
    repository = KnowledgeRepository(paths.repository)
    for document_id, title, filename in [
        ("first", "First source", "First.pdf"),
        ("second", "Second source", "Second.pdf"),
        ("notes", "Notes", "Notes.md"),
        ("latex", "LaTeX", "Research.tex"),
    ]:
        payload = b"%PDF-1.4\n" + document_id.encode() + b"\n%%EOF\n"
        repository.write_page(
            f"sources/{document_id}.md",
            title,
            {"kind": "source", "document_id": document_id,
             "original_filename": filename, "content_sha256": sha256(payload).hexdigest()},
            "## Extracted Text\n\nCandidate has Python experience.",
        )
        (paths.documents / f"{document_id}{Path(filename).suffix}").write_bytes(payload)
    active = ActiveKnowledge.load(repository)
    return repository, paths, ProcessedPdfCatalog(paths, active)


def resolve(answer, sources):
    from cv_agent.agent.source_documents import resolve_source_documents

    repository, _, catalog = sources
    return resolve_source_documents(answer, repository.list_pages(), catalog)


@pytest.mark.parametrize("label", ["Fuentes:", "Sources:", "**Fuentes:**", "**Sources**:"])
def test_direct_source_has_server_verified_original(sources, label):
    assert resolve(f"Candidate tiene experiencia.\n{label} [[First source]]\n", sources) == [
        {"title": "First source", "documents": [
            {"filename": "First.pdf", "path": "/v1/documents/first/original"}
        ]}
    ]


def test_generated_page_resolves_two_pdfs_in_reference_order(sources):
    repository, _, _ = sources
    repository.write_page("knowledge/profile.md", "Profile", {"kind": "entity"},
                          "Evidence [[sources/second]], then [[sources/first]].")
    assert resolve("Respuesta.\nFuentes: [[Profile]]", sources) == [
        {"title": "Profile", "documents": [
            {"filename": "Second.pdf", "path": "/v1/documents/second/original"},
            {"filename": "First.pdf", "path": "/v1/documents/first/original"},
        ]}
    ]


@pytest.mark.parametrize("non_pdf", ["notes", "latex"])
def test_generated_page_omits_non_pdf_originals(sources, non_pdf):
    repository, _, _ = sources
    repository.write_page("knowledge/profile.md", "Profile", {"kind": "entity"},
                          f"[[sources/{non_pdf}]] [[sources/first]]")
    assert resolve("Respuesta.\nFuentes: [[Profile]]", sources)[0]["documents"] == [
        {"filename": "First.pdf", "path": "/v1/documents/first/original"}
    ]


def test_repeated_citations_and_references_are_stably_deduplicated(sources):
    repository, _, _ = sources
    repository.write_page("knowledge/profile.md", "Profile", {"kind": "entity"},
                          "[[sources/first]] [[sources/second]] [[sources/first]]")
    result = resolve("Respuesta.\nFuentes: [[Profile]], [[Profile]], [[First source]]", sources)
    assert result == [
        {"title": "Profile", "documents": [
            {"filename": "First.pdf", "path": "/v1/documents/first/original"},
            {"filename": "Second.pdf", "path": "/v1/documents/second/original"},
        ]},
        {"title": "First source", "documents": [
            {"filename": "First.pdf", "path": "/v1/documents/first/original"}
        ]},
    ]


def test_duplicate_title_is_visible_without_an_ambiguous_link(sources):
    repository, _, _ = sources
    repository.write_page("knowledge/duplicate.md", "First source", {"kind": "entity"},
                          "[[sources/second]]")
    assert resolve("Respuesta.\nFuentes: [[First source]]", sources) == [
        {"title": "First source", "documents": []}
    ]


@pytest.mark.parametrize("title", ["Unknown", "first source", "https://evil.test/document.pdf"])
def test_unknown_or_nonexact_title_is_visible_without_a_link(sources, title):
    assert resolve(f"Respuesta.\nFuentes: [[{title}]]", sources) == [
        {"title": title, "documents": []}
    ]


@pytest.mark.parametrize("answer", [
    "Candidate menciona [[First source]] en prosa.",
    "Fuentes: [[First source]]\nMás prosa después de la cita.",
    "Candidate menciona [[First source]].\nFuentes: ninguna.",
    "",
])
def test_only_citations_on_the_final_sources_line_produce_metadata(sources, answer):
    assert resolve(answer, sources) == []


def test_absent_original_retains_title_without_a_link(sources):
    _, paths, _ = sources
    (paths.documents / "first.pdf").unlink()
    assert resolve("Respuesta.\nFuentes: [[First source]]", sources) == [
        {"title": "First source", "documents": []}
    ]


@pytest.mark.parametrize("relative_path", ["sources/impostor.md", "knowledge/impostor.md"])
def test_direct_source_cannot_borrow_another_sources_document_id(sources, relative_path):
    repository, _, _ = sources
    repository.write_page(
        relative_path, "Impostor", {"kind": "source", "document_id": "first"},
        "## Extracted Text\n\nCandidate has Python experience.",
    )
    assert resolve("Respuesta.\nFuentes: [[Impostor]]", sources) == [
        {"title": "Impostor", "documents": []}
    ]


def test_model_urls_and_invalid_source_references_cannot_supply_links(sources):
    repository, _, _ = sources
    repository.write_page(
        "knowledge/profile.md", "Profile", {"kind": "entity"},
        "https://evil.test/x.pdf [[sources/../first]] [[sources/first.pdf]] "
        "[[sources/first|alias]] [[sources/first#heading]] [[sources/first]]",
    )
    assert resolve("Respuesta.\nFuentes: [[Profile]] https://evil.test/y.pdf", sources) == [
        {"title": "Profile", "documents": [
            {"filename": "First.pdf", "path": "/v1/documents/first/original"}
        ]}
    ]
