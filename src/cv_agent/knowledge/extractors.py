from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader
from pypdf.errors import PdfReadError


@dataclass(frozen=True)
class ExtractedSource:
    source_path: Path
    text: str
    kind: str
    needs_ocr: bool
    sha256: str


class SourceExtractionError(ValueError):
    """Raised when submitted source bytes cannot be decoded or parsed."""

    def __init__(self, message: str) -> None:
        bounded = str(message).replace("\n", " ").replace("\r", " ")[:120]
        super().__init__(bounded)


def extract_source(path: Path) -> ExtractedSource:
    suffix = path.suffix.lower()
    raw_bytes = path.read_bytes()
    digest = sha256(raw_bytes).hexdigest()
    if suffix == ".md":
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceExtractionError("document text is invalid") from exc
        return ExtractedSource(path, text, "markdown", False, digest)
    if suffix == ".tex":
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceExtractionError("document text is invalid") from exc
        return ExtractedSource(path, _clean_latex(text), "latex", False, digest)
    if suffix == ".pdf":
        try:
            text = _extract_pdf_text(path)
        except PdfReadError as exc:
            raise SourceExtractionError("document PDF is invalid") from exc
        return ExtractedSource(path, text, "pdf", len(text.strip()) < 120, digest)
    raise ValueError(f"unsupported source extension: {suffix}")


def _clean_latex(text: str) -> str:
    text = _strip_latex_comments(text)
    document = re.search(r"\\begin\s*\{document\}(.*?)\\end\s*\{document\}", text, re.DOTALL)
    if document:
        text = document.group(1)

    text = _replace_accents(text)
    text = re.sub(
        r"\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}",
        r"\1",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(r"\\subsubsection\*?\s*\{([^{}]*)\}", r"\n#### \1\n", text)
    text = re.sub(r"\\subsection\*?\s*\{([^{}]*)\}", r"\n### \1\n", text)
    text = re.sub(r"\\section\*?\s*\{([^{}]*)\}", r"\n## \1\n", text)
    text = re.sub(r"\\(?:textbf|textit|emph)\s*\{([^{}]*)\}", r" \1", text)
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", "\n", text)
    text = re.sub(r"\\\\(?:\[[^]]*\])?", "\n", text)
    text = re.sub(r"\\item\b", "\n- ", text)
    text = re.sub(r"\\(?:vspace|hspace)\*?\s*\{[^{}]*\}", " ", text)
    text = re.sub(r"\\rule\s*\{[^{}]*\}\s*\{[^{}]*\}", " ", text)
    text = re.sub(r"\\setlength\s*\{[^{}]*\}\s*\{[^{}]*\}", " ", text)
    text = re.sub(
        r"\\(?:LARGE|Large|large|normalsize|small|bfseries|raggedright|hfill|enspace|"
        r"noindent|par|newpage|today)\b",
        " ",
        text,
    )
    text = re.sub(r"\\[a-zA-Z@]+\*?", " ", text)
    text = text.replace(r"\&", "&").replace(r"\_", "_").replace(r"\#", "#")
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"(?<!\w)[+-]?\d+(?:\.\d+)?(?:pt|em|in|cm|mm)\b", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _replace_accents(text: str) -> str:
    combining = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303"}

    def replace(match: re.Match[str]) -> str:
        return unicodedata.normalize("NFC", match.group(2) + combining[match.group(1)])

    text = re.sub(r"\\(['`^\"~])\{?([A-Za-z])\}?", replace, text)
    return text.replace(r"\%", "%")


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
