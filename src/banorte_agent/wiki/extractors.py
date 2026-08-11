from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from pypdf import PdfReader


@dataclass(frozen=True)
class ExtractedSource:
    source_path: Path
    text: str
    kind: str
    needs_ocr: bool
    sha256: str


def extract_source(path: Path) -> ExtractedSource:
    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    digest = sha256(raw_bytes).hexdigest()
    if suffix == ".md":
        return ExtractedSource(path, path.read_text(encoding="utf-8"), "markdown", False, digest)
    if suffix == ".tex":
        return ExtractedSource(path, _clean_latex(path.read_text(encoding="utf-8")), "latex", False, digest)
    if suffix == ".pdf":
        text = _extract_pdf_text(path)
        return ExtractedSource(path, text, "pdf", len(text.strip()) < 120, digest)
    raise ValueError(f"unsupported source extension: {suffix}")


def _clean_latex(text: str) -> str:
    text = _strip_latex_comments(text)
    text = text.replace(r"\%", "%")
    text = re.sub(r"\\(section|subsection|subsubsection|textbf|emph)\{([^}]*)\}", r"\2\n", text)
    text = re.sub(r"\\[a-zA-Z]+(\[[^]]*\])?(\{[^}]*\})?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_latex_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        comment_start: int | None = None
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                comment_start = index
                break
        lines.append(line if comment_start is None else line[:comment_start])
    return "".join(lines)


def _extract_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()
