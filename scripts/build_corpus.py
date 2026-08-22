#!/usr/bin/env python3
"""Maintainer tool: rebuild ``corpus/`` from the official sources the rule catalog cites.

The opt-in ``ai explain`` and ``ai draft-fix`` commands (ADR 0002) may quote only text that
is committed here. This script is how that text gets here: it fetches every unique source
URL in the built-in rule catalog (plus the documents listed in ``EXTRA_SOURCES``), records
the SHA-256 of the bytes it received and the retrieval time, extracts plain text, splits the
text into addressable passages, and writes ``corpus/manifest.json``, ``corpus/text/*.txt``,
and ``corpus/passages.json``.

Like ``check_rule_sources.py``, this is deliberately NOT part of ``make verify``, the shipped
CLI, or CI. The product's default path makes no network calls and the test suite blocks
sockets. Run it by hand when a source review finds that official guidance changed, review
the diff, and commit the result together with the updated source review.

    python3 scripts/build_corpus.py [--corpus-dir corpus] [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = str(ROOT / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ceqa_preflight.ai.corpus import (  # noqa: E402
    MANIFEST_NAME,
    PASSAGES_NAME,
    TEXT_DIR_NAME,
    CorpusDocument,
    CorpusManifest,
    Passage,
    normalize_whitespace,
)
from ceqa_preflight.models import SourceKind  # noqa: E402
from ceqa_preflight.rule_registry import default_catalog  # noqa: E402

_DEFAULT_TIMEOUT = 30.0
_USER_AGENT = "ceqa-preflight-corpus-build/1.0 (+https://github.com/ChelseaKR/ceqa-preflight)"
_MAX_BYTES = 20 * 1024 * 1024
_MAX_PASSAGE_CHARS = 1200
_MIN_PASSAGE_CHARS = 60


@dataclass(frozen=True)
class SourceSpec:
    """One document to fetch, and how to name it in the corpus."""

    id: str
    url: str
    title: str
    kind: SourceKind
    local_path: Path | None = None


# Documents that no rule cites directly but that the explanation layer may retrieve for
# filing-form context, plus the project's own reasoning for its self-cited rules.
EXTRA_SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        id="lci-sch-document-submission",
        url="https://lci.ca.gov/sch/document-submission/",
        title="LCI State Clearinghouse document submission guidance",
        kind=SourceKind.OFFICIAL,
    ),
)

# Stable identifiers for the URLs the catalog cites today. A new citation URL must be
# given an identifier here; the script refuses to invent one.
KNOWN_SOURCE_IDS: dict[str, str] = {
    "https://lci.ca.gov/sch/docs/20250911-CEQA_Submit_Pre-Submission_Checklist_2025.pdf": (
        "lci-sch-presubmission-checklist-2025"
    ),
    "https://lci.ca.gov/sch/docs/20250911-Common_Mistakes_to_Avoid_in_CEQA_Submit_2025.pdf": (
        "lci-sch-common-mistakes-2025"
    ),
    "https://lci.ca.gov/sch/faq/": "lci-sch-faq",
    "https://owasp.org/www-community/vulnerabilities/Unrestricted_File_Upload": (
        "owasp-unrestricted-file-upload"
    ),
    "https://github.com/ChelseaKR/ceqa-preflight/blob/main/docs/audits/"
    "rule-source-review-2026-07-27-addendum.md": "ceqa-preflight-source-review-addendum-2026-07-27",
}

# Self-cited project documents are read from the working tree so the corpus text is the
# reviewed file, not whatever a web view renders around it.
LOCAL_SOURCE_PATHS: dict[str, Path] = {
    "ceqa-preflight-source-review-addendum-2026-07-27": (
        ROOT / "docs" / "audits" / "rule-source-review-2026-07-27-addendum.md"
    ),
}

Fetcher = Callable[[str, float], tuple[bytes, str]]


def _fetch(url: str, timeout: float) -> tuple[bytes, str]:
    """Return the response bytes and content type for one absolute HTTP(S) URL."""

    if not url.startswith(("http://", "https://")):
        raise ValueError(f"unsupported URL scheme: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        content_type = str(response.headers.get("Content-Type", "")).split(";")[0].strip()
        data = response.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise ValueError(f"source exceeds {_MAX_BYTES} bytes: {url}")
    return data, content_type


class _BlockTextParser(HTMLParser):
    """Collect block-level text from the main content of an HTML page.

    Headings and accordion summaries become heading blocks; paragraphs and list items
    become paragraph blocks. Script, style, navigation, header, and footer content is
    dropped. Only the first ``<main>`` element is read when one exists.
    """

    _SKIP = frozenset({"script", "style", "nav", "header", "footer", "noscript", "svg"})
    _HEADINGS = frozenset({"h1", "h2", "h3", "h4", "summary"})
    _BLOCKS = frozenset({"p", "li", "td", "th", "pre", "blockquote", "dd", "dt"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._current: list[str] = []
        self._current_kind: str | None = None
        self._seen_main = False
        self._in_main = False
        self._main_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "main":
            self._seen_main = True
            self._in_main = True
            self._main_depth = 0
        if self._in_main:
            self._main_depth += 1
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self._HEADINGS or tag in self._BLOCKS:
            self._flush()
            self._current_kind = "heading" if tag in self._HEADINGS else "paragraph"
        elif tag == "br":
            self._current.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._in_main:
            self._main_depth -= 1
            if tag == "main" or self._main_depth <= 0:
                self._flush()
                self._in_main = False
        if tag in self._HEADINGS or tag in self._BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or (self._seen_main and not self._in_main):
            return
        if self._current_kind is None:
            return
        self._current.append(data)

    def _flush(self) -> None:
        text = normalize_whitespace("".join(self._current))
        if text and self._current_kind is not None:
            self.blocks.append((self._current_kind, text))
        self._current = []
        self._current_kind = None

    def close(self) -> None:
        super().close()
        self._flush()


def html_blocks(document: str) -> list[tuple[str, str]]:
    """Return ``(kind, text)`` blocks from an HTML document's main content."""

    parser = _BlockTextParser()
    parser.feed(document)
    parser.close()
    return parser.blocks


_NUMBERED_HEADING = re.compile(r"^\d{1,2}\.\s+[A-Z][^.]{2,80}$")


def pdf_blocks(path: Path) -> list[tuple[str, str]]:
    """Return blocks from a text-layer PDF; short numbered lines are section headings."""

    from pdfminer.high_level import extract_text

    text = extract_text(str(path))
    blocks: list[tuple[str, str]] = []
    for part in re.split(r"\n\s*\n", text):
        normalized = normalize_whitespace(part)
        kind = "heading" if _NUMBERED_HEADING.fullmatch(normalized) else "paragraph"
        blocks.append((kind, normalized))
    return blocks


def markdown_blocks(document: str) -> list[tuple[str, str]]:
    """Return heading and paragraph blocks from a Markdown file."""

    blocks: list[tuple[str, str]] = []
    for part in re.split(r"\n\s*\n", document):
        stripped = part.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            blocks.append(("heading", normalize_whitespace(stripped.lstrip("# "))))
        elif stripped.startswith("|"):
            blocks.extend(_table_row_blocks(stripped))
        else:
            blocks.append(("paragraph", normalize_whitespace(html.unescape(stripped))))
    return blocks


def _table_row_blocks(table: str) -> list[tuple[str, str]]:
    """Turn each Markdown table row into one block: header cells are kept, rules dropped."""

    blocks: list[tuple[str, str]] = []
    for line in table.splitlines():
        cells = [normalize_whitespace(cell) for cell in line.strip().strip("|").split("|")]
        if not cells or all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        blocks.append(("paragraph", " — ".join(cell for cell in cells if cell)))
    return blocks


def passages_from_blocks(document_id: str, blocks: list[tuple[str, str]]) -> list[Passage]:
    """Group blocks into addressable passages under their nearest heading.

    Consecutive paragraphs are merged until a passage would exceed the size cap, so a
    passage usually reads as one complete point of guidance. Fragments shorter than the
    minimum (page numbers, stray glyphs) are dropped rather than cited.
    """

    passages: list[Passage] = []
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        text = " ".join(buffer).strip()
        if len(text) >= _MIN_PASSAGE_CHARS:
            passages.append(
                Passage(id=f"{document_id}#p{len(passages) + 1:03d}", heading=heading, text=text)
            )
        buffer.clear()

    for kind, text in blocks:
        if not text:
            continue
        if kind == "heading":
            flush()
            heading = text
            continue
        if buffer and len(" ".join(buffer)) + len(text) > _MAX_PASSAGE_CHARS:
            flush()
        buffer.append(text)
    flush()
    return passages


def _blocks_for(
    spec: SourceSpec, data: bytes, content_type: str, scratch: Path
) -> list[tuple[str, str]]:
    if spec.local_path is not None:
        return markdown_blocks(data.decode("utf-8"))
    if content_type == "application/pdf" or data[:5] == b"%PDF-":
        scratch.mkdir(parents=True, exist_ok=True)
        pdf_path = scratch / f"{spec.id}.pdf"
        pdf_path.write_bytes(data)
        return pdf_blocks(pdf_path)
    return html_blocks(data.decode("utf-8", errors="replace"))


def _source_specs() -> list[SourceSpec]:
    specs: dict[str, SourceSpec] = {}
    for rule in default_catalog().rules:
        url = rule.source.url
        if url not in KNOWN_SOURCE_IDS:
            raise SystemExit(
                f"{rule.id} cites {url}, which has no corpus identifier; add one to "
                "KNOWN_SOURCE_IDS after reviewing the source"
            )
        identifier = KNOWN_SOURCE_IDS[url]
        if identifier not in specs:
            specs[identifier] = SourceSpec(
                id=identifier,
                url=url,
                title=rule.source.title,
                kind=rule.source.kind,
                local_path=LOCAL_SOURCE_PATHS.get(identifier),
            )
    for extra in EXTRA_SOURCES:
        specs.setdefault(extra.id, extra)
    return [specs[key] for key in sorted(specs)]


def _cited_by() -> dict[str, list[str]]:
    cited: dict[str, list[str]] = {}
    for rule in default_catalog().rules:
        cited.setdefault(KNOWN_SOURCE_IDS[rule.source.url], []).append(rule.id)
    return cited


@dataclass
class BuildResult:
    manifest: CorpusManifest
    passages: dict[str, list[Passage]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)


def build(corpus_dir: Path, *, timeout: float, fetch: Fetcher = _fetch) -> BuildResult:
    """Fetch every source, extract and split its text, and write the corpus files."""

    scratch = corpus_dir / ".build"
    cited_by = _cited_by()
    documents: list[CorpusDocument] = []
    result = BuildResult(manifest=CorpusManifest(built_at=datetime.now(UTC), documents=[]))
    for spec in _source_specs():
        if spec.local_path is not None:
            data, content_type = spec.local_path.read_bytes(), "text/markdown"
        else:
            data, content_type = fetch(spec.url, timeout)
        blocks = _blocks_for(spec, data, content_type, scratch)
        passages = passages_from_blocks(spec.id, blocks)
        text = "\n\n".join(passage.text for passage in passages) + "\n"
        documents.append(
            CorpusDocument(
                id=spec.id,
                title=spec.title,
                url=spec.url,
                kind=spec.kind,
                retrieved_at=datetime.now(UTC),
                content_type=content_type,
                source_sha256=hashlib.sha256(data).hexdigest(),
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                passage_count=len(passages),
                cited_by=sorted(cited_by.get(spec.id, [])),
            )
        )
        result.passages[spec.id] = passages
        result.texts[spec.id] = text
        print(f"[ok] {spec.id}: {len(data)} bytes, {len(passages)} passage(s)")
    result.manifest = CorpusManifest(built_at=datetime.now(UTC), documents=documents)
    _write(corpus_dir, result)
    for leftover in scratch.glob("*"):
        leftover.unlink()
    if scratch.exists():
        scratch.rmdir()
    return result


def _write(corpus_dir: Path, result: BuildResult) -> None:
    text_dir = corpus_dir / TEXT_DIR_NAME
    text_dir.mkdir(parents=True, exist_ok=True)
    for document_id, text in result.texts.items():
        (text_dir / f"{document_id}.txt").write_text(text, encoding="utf-8")
    (corpus_dir / PASSAGES_NAME).write_text(
        json.dumps(
            {
                document_id: [passage.model_dump(mode="json") for passage in passages]
                for document_id, passages in result.passages.items()
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (corpus_dir / MANIFEST_NAME).write_text(
        result.manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None, fetch: Fetcher = _fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    try:
        result = build(args.corpus_dir, timeout=args.timeout, fetch=fetch)
    except (urllib.error.URLError, ValueError, OSError) as error:
        print(f"corpus build failed: {error}", file=sys.stderr)
        return 1
    print(f"\nWrote {len(result.manifest.documents)} document(s) to {args.corpus_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
