from pathlib import Path
import argparse
import sys

import httpx
import yaml


SPANISH_MARKERS = {" el ", " la ", " de ", " que ", " experiencia ", " fuentes:"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--output", default="docs/sample-transcript.md")
    args = parser.parse_args()

    questions = yaml.safe_load(Path("evals/questions.yml").read_text(encoding="utf-8"))["questions"]
    transcript: list[str] = ["# Sample Transcript", ""]
    failures: list[str] = []
    with httpx.Client(timeout=60) as client:
        for item in questions:
            response = client.post(
                f"{args.base_url.rstrip('/')}/v1/responses",
                json={"model": "banorte-cv-agent", "input": item["text"]},
            )
            if response.status_code != 200:
                failures.append(f"{item['id']}: status {response.status_code}")
                continue
            text = response.json()["output_text"]
            transcript.extend([f"## {item['id']}", "", f"**Q:** {item['text']}", "", f"**A:** {text}", ""])
            lowered = f" {text.lower()} "
            if item.get("require_citation") and "Fuentes:" not in text:
                failures.append(f"{item['id']}: missing Fuentes citation line")
            if item.get("require_spanish") and not any(marker in lowered for marker in SPANISH_MARKERS):
                failures.append(f"{item['id']}: Spanish markers not detected")
            if item.get("expect_missing_info") and not any(phrase in lowered for phrase in ["no tengo", "no se especifica", "no aparece"]):
                failures.append(f"{item['id']}: missing-info behavior not detected")

    Path(args.output).write_text("\n".join(transcript), encoding="utf-8")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"eval passed; transcript written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
