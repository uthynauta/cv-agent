from __future__ import annotations

import html
import os
from pathlib import Path
import stat
import time
from types import SimpleNamespace

import pytest

import cv_agent.knowledge.validation as validation_module
from cv_agent.knowledge.frontmatter import dump_frontmatter
from cv_agent.knowledge.validation import KnowledgeValidationError, validate_knowledge


def _write_page(root: Path, relative: str, metadata: dict[str, object], body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")


def _source_metadata(document_id: str = "doc-123", digest: str = "a" * 64) -> dict[str, object]:
    return {
        "title": "Candidate source",
        "kind": "source",
        "document_id": document_id,
        "content_sha256": digest,
    }


def test_validates_source_identity_and_generated_citation(tmp_path: Path):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "# Candidate\n\n## Extracted Text\n\nPython and Rust experience.",
    )
    _write_page(
        tmp_path,
        "knowledge/projects/rust.md",
        {"title": "Rust", "kind": "project"},
        "## Summary\n\nSee [[sources/doc-123]].",
    )

    assert validate_knowledge(tmp_path) is None


@pytest.mark.parametrize(
    ("evidence", "valid"),
    [("中文经历", True), ("áéíóú", True), ("🙂🙂", False), ("!!!", False)],
)
def test_extracted_text_uses_unicode_aware_meaningful_evidence(
    tmp_path: Path, evidence: str, valid: bool
):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        f"## Extracted Text\n\n{evidence}",
    )

    if valid:
        assert validate_knowledge(tmp_path) is None
    else:
        with pytest.raises(KnowledgeValidationError, match="extracted_text"):
            validate_knowledge(tmp_path)


def test_rejects_deep_empty_directory_before_traversal(tmp_path: Path):
    directory = tmp_path / "knowledge"
    directory.mkdir()
    for index in range(8):
        directory /= f"level-{index}"
        directory.mkdir()

    with pytest.raises(KnowledgeValidationError, match="path"):
        validate_knowledge(tmp_path)


def test_rejects_oversized_empty_directory_component_before_open(tmp_path: Path, monkeypatch):
    (tmp_path / "knowledge").mkdir()
    oversized = "x" * 256
    original_scandir = os.scandir

    class FakeEntry:
        name = oversized

        def stat(self, *, follow_symlinks):
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700)

    class FakeScanner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            return iter([FakeEntry()])

    scans = 0

    def fake_scandir(directory_fd):
        nonlocal scans
        if isinstance(directory_fd, int):
            scans += 1
            if scans == 2:
                return FakeScanner()
        return original_scandir(directory_fd)

    monkeypatch.setattr(validation_module.os, "scandir", fake_scandir)
    original_open_directory_at = validation_module._open_directory_at

    def fail_if_opened(parent_fd, name, relative):
        if relative not in {"root", "knowledge"}:
            pytest.fail("oversized directory must fail before open")
        return original_open_directory_at(parent_fd, name, relative)

    monkeypatch.setattr(validation_module, "_open_directory_at", fail_if_opened)

    with pytest.raises(KnowledgeValidationError, match="path"):
        validate_knowledge(tmp_path)


def test_extracted_text_retains_evidence_after_embedded_heading(tmp_path: Path):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\n# Experience\n\nPython and Rust experience.",
    )

    assert validate_knowledge(tmp_path) is None


@pytest.mark.parametrize(
    ("evidence", "valid"),
    [
        ("&nbsp;", False),
        ("&ensp;", False),
        ("&#160;", False),
        ("<!-- &nbsp; -->", False),
        ("<p></p>", False),
        ("&lt;C++&gt;", True),
        ("<p>Python</p>", True),
    ],
)
def test_html_entities_and_tags_are_normalized_before_meaningfulness_check(
    tmp_path: Path, evidence: str, valid: bool
):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        f"## Extracted Text\n\n{evidence}",
    )

    if valid:
        assert validate_knowledge(tmp_path) is None
    else:
        with pytest.raises(KnowledgeValidationError, match="extracted_text"):
            validate_knowledge(tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="requires byte-level POSIX filenames")
def test_invalid_bytes_filename_has_bounded_utf8_safe_error(tmp_path: Path):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    parent_fd = os.open(knowledge, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        descriptor = os.open(
            b"invalid-\xff.md",
            os.O_WRONLY | os.O_CREAT,
            0o600,
            dir_fd=parent_fd,
        )
        try:
            os.write(descriptor, b"not frontmatter")
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)

    with pytest.raises(KnowledgeValidationError) as error:
        validate_knowledge(tmp_path)
    message = str(error.value)
    assert "\udcff" not in message
    assert len(message) <= 300
    message.encode("utf-8")


@pytest.mark.parametrize(
    ("attribute", "limit", "relative"),
    [
        ("MAX_VALIDATION_ENTRIES", 1, "sources/doc-123.md"),
        ("MAX_VALIDATION_PAGES", 0, "sources/doc-123.md"),
        ("MAX_VALIDATION_DIRECTORIES", 0, "sources"),
    ],
)
def test_validation_enforces_monkeypatched_resource_limits(
    tmp_path: Path, monkeypatch, attribute: str, limit: int, relative: str
):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    monkeypatch.setattr(validation_module, attribute, limit)

    with pytest.raises(KnowledgeValidationError, match="resource|path"):
        validate_knowledge(tmp_path)


def test_validation_closes_directory_descriptors_after_each_subtree(
    tmp_path: Path, monkeypatch
):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    for index in range(20):
        (knowledge / f"section-{index}").mkdir()

    original_open = validation_module.os.open
    original_close = validation_module.os.close
    live_directories: set[int] = set()
    max_live_directories = 0

    def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal max_live_directories
        if mode == 0o777:
            descriptor = original_open(path, flags, dir_fd=dir_fd)
        else:
            descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if flags & getattr(os, "O_DIRECTORY", 0):
            live_directories.add(descriptor)
            max_live_directories = max(max_live_directories, len(live_directories))
        return descriptor

    def tracked_close(descriptor: int) -> None:
        live_directories.discard(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(validation_module.os, "open", tracked_open)
    monkeypatch.setattr(validation_module.os, "close", tracked_close)
    validate_knowledge(tmp_path)

    assert not live_directories
    assert max_live_directories <= 3


def test_validation_bounds_scandir_consumption_before_sorting(tmp_path: Path, monkeypatch):
    (tmp_path / "knowledge").mkdir()
    original_scandir = validation_module.os.scandir
    scans = 0

    class FakeEntry:
        def __init__(self, name: str):
            self.name = name

        def stat(self, *, follow_symlinks):
            pytest.fail("entry beyond budget must not be stat'ed")

    class BoundedScanner:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __iter__(self):
            yield FakeEntry("candidate-1")
            yield FakeEntry("candidate-2")
            pytest.fail("scanner consumed past budget + 1")

    def bounded_scandir(directory_fd):
        nonlocal scans
        if isinstance(directory_fd, int):
            scans += 1
            if scans == 2:
                return BoundedScanner()
        return original_scandir(directory_fd)

    monkeypatch.setattr(validation_module.os, "scandir", bounded_scandir)
    monkeypatch.setattr(validation_module, "MAX_VALIDATION_ENTRIES", 2)

    with pytest.raises(KnowledgeValidationError, match="resource"):
        validate_knowledge(tmp_path)


def test_validation_rejects_markdown_above_byte_limit_before_parsing(tmp_path: Path, monkeypatch):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    monkeypatch.setattr(validation_module, "MAX_MARKDOWN_BYTES", 32)

    with pytest.raises(KnowledgeValidationError, match="resource"):
        validate_knowledge(tmp_path)


def test_validation_rejects_cumulative_markdown_byte_limit(tmp_path: Path, monkeypatch):
    _write_page(
        tmp_path,
        "sources/first.md",
        _source_metadata("first"),
        "## Extracted Text\n\nfirst source",
    )
    _write_page(
        tmp_path,
        "sources/second.md",
        _source_metadata("second"),
        "## Extracted Text\n\nsecond source",
    )
    monkeypatch.setattr(validation_module, "MAX_TOTAL_MARKDOWN_BYTES", 100)

    with pytest.raises(KnowledgeValidationError, match="resource"):
        validate_knowledge(tmp_path)


def test_validation_nested_entities_and_recognized_tags_follow_literal_text_rules(
    tmp_path: Path,
):
    cases = [
        ("&amp;nbsp;", False),
        ("&amp;amp;nbsp;", False),
        ("&lt;p&gt;&lt;/p&gt;", False),
        ("&lt;p&gt;No text&lt;/p&gt;", False),
        ("&lt;C++&gt;", True),
        ("<p>Python</p>", True),
    ]
    for evidence, valid in cases:
        source = tmp_path / "sources" / "doc-123.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            dump_frontmatter(
                _source_metadata(), f"## Extracted Text\n\n{evidence}"
            ),
            encoding="utf-8",
        )
        try:
            if valid:
                assert validate_knowledge(tmp_path) is None
            else:
                with pytest.raises(KnowledgeValidationError, match="extracted_text"):
                    validate_knowledge(tmp_path)
        finally:
            source.unlink()


def test_validation_decodes_nested_markup_to_stability_with_a_bound(tmp_path: Path):
    def nested_escape(value: str, passes: int) -> str:
        for _ in range(passes):
            value = html.escape(value, quote=False)
        return value

    cases = [
        (nested_escape("<p></p>", 2), False),
        (nested_escape("<p>No text</p>", 2), False),
        (nested_escape("<C++>", 2), True),
        (nested_escape("<p>Python</p>", 10), False),
    ]
    for evidence, valid in cases:
        _write_page(
            tmp_path,
            "sources/doc-123.md",
            _source_metadata(),
            f"## Extracted Text\n\n{evidence}",
        )
        try:
            if valid:
                assert validate_knowledge(tmp_path) is None
            else:
                with pytest.raises(KnowledgeValidationError, match="extracted_text"):
                    validate_knowledge(tmp_path)
        finally:
            (tmp_path / "sources" / "doc-123.md").unlink()


@pytest.mark.parametrize(
    ("metadata", "body", "field"),
    [
        ({"kind": "source", "content_sha256": "a" * 64}, "## Extracted Text\n\ntext", "document_id"),
        ({**_source_metadata(), "kind": "profile"}, "## Extracted Text\n\ntext", "kind"),
        ({**_source_metadata(), "document_id": "../escape"}, "## Extracted Text\n\ntext", "document_id"),
        ({**_source_metadata(), "document_id": "doc.md"}, "## Extracted Text\n\ntext", "document_id"),
        ({**_source_metadata(), "document_id": "a" * 129}, "## Extracted Text\n\ntext", "document_id"),
        ({**_source_metadata(), "content_sha256": "A" * 64}, "## Extracted Text\n\ntext", "content_sha256"),
        ({**_source_metadata(), "content_sha256": "a" * 63}, "## Extracted Text\n\ntext", "content_sha256"),
        ({**_source_metadata(), "content_sha256": "not-a-digest"}, "## Extracted Text\n\ntext", "content_sha256"),
        (_source_metadata(), "# Only a heading", "extracted_text"),
        (_source_metadata(), "## Extracted Text\n\nNo selectable text extracted.", "extracted_text"),
        (_source_metadata(), "## Extracted Text\n\n<!-- placeholder -->", "extracted_text"),
    ],
)
def test_rejects_invalid_source_page(
    tmp_path: Path, metadata: dict[str, object], body: str, field: str
):
    _write_page(tmp_path, "sources/doc-123.md", metadata, body)

    with pytest.raises(KnowledgeValidationError, match=field):
        validate_knowledge(tmp_path)


def test_source_document_ids_are_unique_and_match_canonical_paths(tmp_path: Path):
    _write_page(
        tmp_path,
        "sources/first.md",
        _source_metadata("doc-123"),
        "## Extracted Text\n\nfirst source",
    )
    _write_page(
        tmp_path,
        "sources/second.md",
        _source_metadata("doc-123"),
        "## Extracted Text\n\nsecond source",
    )

    with pytest.raises(KnowledgeValidationError, match="document_id"):
        validate_knowledge(tmp_path)


@pytest.mark.parametrize(
    "citation",
    [
        "[[sources/unknown]]",
        "[[sources/doc-123.md]]",
        "[[sources/doc-123/extra]]",
        "[[sources/../doc-123]]",
        "[[sources\\doc-123]]",
    ],
)
def test_rejects_unknown_or_malformed_generated_source_citations(tmp_path: Path, citation: str):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    _write_page(tmp_path, "knowledge/projects/project.md", {}, f"See {citation}.")

    with pytest.raises(KnowledgeValidationError, match="source_citations"):
        validate_knowledge(tmp_path)


def test_generated_page_requires_a_source_citation(tmp_path: Path):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    _write_page(tmp_path, "knowledge/projects/project.md", {}, "A claim without evidence.")

    with pytest.raises(KnowledgeValidationError, match="source_citations"):
        validate_knowledge(tmp_path)


@pytest.mark.parametrize("directory", ["sources", "knowledge"])
def test_rejects_symlinked_knowledge_tree(tmp_path: Path, directory: str):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (tmp_path / directory).symlink_to(outside, target_is_directory=True)

    with pytest.raises(KnowledgeValidationError, match="path"):
        validate_knowledge(tmp_path)


def test_rejects_ancestor_swap_between_scan_and_descent(tmp_path: Path, monkeypatch):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_page(
        outside,
        "secret.md",
        _source_metadata("secret"),
        "## Extracted Text\n\noutside source",
    )
    original_scandir = os.scandir
    swapped = False

    def race_scandir(path):
        nonlocal swapped
        iterator = original_scandir(path)
        if not swapped:
            sources = tmp_path / "sources"
            moved = tmp_path / "sources.real"
            sources.rename(moved)
            sources.symlink_to(outside, target_is_directory=True)
            swapped = True
        return iterator

    monkeypatch.setattr("cv_agent.knowledge.validation.os.scandir", race_scandir)
    with pytest.raises(KnowledgeValidationError, match="path"):
        validate_knowledge(tmp_path)


def test_rejects_fifo_replacement_without_blocking(tmp_path: Path, monkeypatch):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    original_open = os.open
    replaced = False

    def race_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        if dir_fd is not None and path == "doc-123.md" and not replaced:
            (tmp_path / "sources" / "doc-123.md").unlink()
            os.mkfifo(tmp_path / "sources" / "doc-123.md")
            replaced = True
        if mode == 0o777:
            return original_open(path, flags, dir_fd=dir_fd)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("cv_agent.knowledge.validation.os.open", race_open)
    started = time.monotonic()
    with pytest.raises(KnowledgeValidationError, match="path|frontmatter"):
        validate_knowledge(tmp_path)
    assert time.monotonic() - started < 1


def test_rejects_special_files_and_out_of_scope_markdown(tmp_path: Path):
    (tmp_path / "sources").mkdir()
    os.mkfifo(tmp_path / "sources" / "input.fifo")

    with pytest.raises(KnowledgeValidationError, match="path"):
        validate_knowledge(tmp_path)


def test_validation_errors_do_not_include_document_contents(tmp_path: Path):
    secret = "private candidate text that must not appear"
    source = tmp_path / "sources" / "doc-123.md"
    source.parent.mkdir()
    source.write_text(f"---\nkind: [broken\n---\n{secret}\n", encoding="utf-8")

    with pytest.raises(KnowledgeValidationError) as error:
        validate_knowledge(tmp_path)
    assert secret not in str(error.value)


def test_reserved_index_and_log_do_not_need_source_citations(tmp_path: Path):
    _write_page(
        tmp_path,
        "sources/doc-123.md",
        _source_metadata(),
        "## Extracted Text\n\nsource text",
    )
    _write_page(tmp_path, "knowledge/index.md", {}, "# Wiki Index")
    _write_page(tmp_path, "knowledge/log.md", {}, "# Wiki Log\n\nsource ingestion")

    assert validate_knowledge(tmp_path) is None
