"""Offline conversion of fixed GitLab Handbook snapshots; never uploads data."""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify


CORPUS_ROOT = Path(__file__).resolve().parent.parent / "data" / "gitlab_hr" / "v1"
NOISE_SELECTOR = (
    "script, style, nav, header, footer, .td-page-meta, .td-content__lastmod, "
    ".text-muted.mt-5.border-top, .text-muted.pt-3:has(.td-page-meta--view)"
)


def policy_body(html: str, expected_title: str):
    soup = BeautifulSoup(html, "html.parser")
    bodies = soup.select("main .td-content")
    if len(bodies) != 1:
        raise ValueError("Expected exactly one GitLab policy body.")
    body = bodies[0]
    titles = body.find_all("h1")
    if len(titles) != 1 or titles[0].get_text(" ", strip=True) != expected_title:
        raise ValueError("Policy title does not match the source manifest.")
    for element in body.select(NOISE_SELECTOR):
        element.decompose()
    return body


def extract_policy(html: str, source_url: str, expected_title: str) -> str:
    body = policy_body(html, expected_title)
    for link in body.find_all("a", href=True):
        link["href"] = urljoin(source_url, link["href"])
    return markdownify(str(body), heading_style="ATX", bullets="-").strip() + "\n"


def build_corpus(root: Path = CORPUS_ROOT):
    snapshot = json.loads((root / "snapshot_manifest.json").read_text(encoding="utf-8"))
    prepared = []
    for doc in snapshot["documents"]:
        raw_path = (root / doc["file"]).resolve()
        if not raw_path.is_relative_to(root.resolve()):
            raise ValueError("Snapshot path escapes the corpus directory.")
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != doc["sha256"]:
            raise ValueError("Raw snapshot hash mismatch: " + doc["document_id"])
        html = raw.decode("utf-8")
        body = policy_body(html, doc["title"])
        markdown = extract_policy(html, doc["source_url"], doc["title"])
        attribution = (
            f"> Source: GitLab Handbook — {doc['source_url']}\n"
            "> License: CC BY-SA 4.0 — https://creativecommons.org/licenses/by-sa/4.0/\n"
            "> Changes: extracted policy body; HTML converted to Markdown; relative links resolved.\n\n"
        )
        output = (attribution + markdown).encode("utf-8")
        filename = doc["document_id"] + ".md"
        if Path(filename).name != filename:
            raise ValueError("Invalid document identifier.")
        record = {
            "document_id": doc["document_id"], "source_url": doc["source_url"],
            "raw_sha256": doc["sha256"], "cleaned_file": "cleaned/" + filename,
            "cleaned_sha256": hashlib.sha256(output).hexdigest(), "cleaned_bytes": len(output),
            "headings": [{"level": int(tag.name[1]), "text": tag.get_text(" ", strip=True)}
                         for tag in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])],
            "list_items": len(body.find_all("li")), "tables": len(body.find_all("table")),
            "status": "cleaned", "indexed": False,
        }
        prepared.append((filename, output, record))
    # Validate every raw file before writing derived artifacts; raw snapshots stay intact.
    cleaned = root / "cleaned"
    cleaned.mkdir(exist_ok=True)
    for filename, output, _ in prepared:
        (cleaned / filename).write_bytes(output)
    manifest = {
        "corpus_id": snapshot["corpus_id"], "converter_version": "1",
        "tools": {name: version(name) for name in ("beautifulsoup4", "markdownify")},
        "documents": [record for _, _, record in prepared],
    }
    (root / "processing_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    result = build_corpus()
    for doc in result["documents"]:
        print(doc["document_id"], doc["cleaned_bytes"], "bytes", "indexed:", doc["indexed"])
