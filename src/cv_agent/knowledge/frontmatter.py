from typing import Any

import yaml


def dump_frontmatter(metadata: dict[str, object], body: str) -> str:
    yaml_text = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{yaml_text}\n---\n\n{body.strip()}\n"


def load_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text.strip()
    _, yaml_text, body = text.split("---", 2)
    metadata = yaml.safe_load(yaml_text) or {}
    if not isinstance(metadata, dict):
        raise ValueError("frontmatter metadata must be a mapping")
    return metadata, body.strip()
