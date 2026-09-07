#!/usr/bin/env python3
"""Maintainer tool: report whether each corpus source still says what the corpus retained.

`scripts/check_rule_sources.py` answers "does the link still resolve". That is not the
question a stale citation raises. LCI republishes its checklist and common-mistakes PDFs
each year, the CCR is amended between registers, and a URL that still returns 200 can be
serving text the corpus no longer matches. A rule explained from a superseded checklist is
exactly the confident staleness this project exists to catch, so the corpus that grounds
`ai explain` should not be able to outlive its source silently.

This re-fetches every document in `corpus/manifest.json`, re-derives its text through the
**same** extraction `scripts/build_corpus.py` used to write the corpus, and classifies it:

``unchanged``
    The re-derived text hashes to the ``text_sha256`` the manifest recorded.
``changed``
    It does not. Every retained passage is then checked for verbatim survival in the new
    text, and the rules bound to the document are named.
``unverifiable``
    The source could not be read *at all*, so nothing is claimed about its content. This
    is not "unchanged", it is not "changed", and it never marks a passage lost.

The distinction inside ``unverifiable`` is the one `permit-bearings` ADR 0005 draws and
it is load-bearing: a 404 or 410 is a statement about the *address*, a timeout or a reset
is a statement about the *network*, and a document missing from an offline cache is a
statement about the *cache*. None of the three is evidence about the law. They are
reported as ``not_found``, ``transport`` and ``not_checked``, and a fourth,
``extraction``, covers a document that was fetched but whose text could not be re-derived
-- because "we could not read it" must not render as "it lost every passage".

For that reason a document that is not ``changed`` or ``unchanged`` carries ``null`` in
``passages_surviving``, ``passages_lost`` and ``rules_with_lost_passages``, never ``[]``.
An empty list of lost passages reads as a clean bill of health, and an unread source has
not earned one.

**It adopts nothing.** The output is a dated JSON file. Nothing here rewrites the corpus,
edits a rule, or changes what `check` reports. `corpus/README.md` records what a person
does with a `changed` verdict.

This is deliberately NOT part of `make verify`, the shipped CLI, or CI's per-PR gates:
the product makes no runtime network calls and this must never become a hidden path
around that. Run it by hand, or from a scheduled maintenance job.

    python3 scripts/watch_sources.py [--timeout SECONDS] [--output FILE]
    python3 scripts/watch_sources.py --offline-cache DIR      # replay a recorded crawl
    python3 scripts/watch_sources.py --document lci-sch-faq   # one document (repeatable)

Exit codes:

``0``
    Every document examined was unchanged.
``1``
    At least one document is **not known to be unchanged** -- changed, or unverifiable.
    Unverifiable counts here on purpose: a run that exited 0 while a source could not be
    read would be reporting an absence as a clean result.
``2``
    The watch could not run at all (no corpus, unreadable cache index).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = str(ROOT / "scripts")
SRC = str(ROOT / "src")
for entry in (SRC, SCRIPTS):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from build_corpus import (  # type: ignore[import-not-found]  # noqa: E402
    LOCAL_SOURCE_PATHS,
    ccr_blocks,
    html_blocks,
    markdown_blocks,
    passages_from_blocks,
    pdf_blocks,
)
from build_corpus import _fetch as _network_fetch  # noqa: E402

from ceqa_preflight.ai.corpus import CorpusDocument, CorpusManifest, Passage  # noqa: E402

WATCH_SCHEMA_VERSION = 1
_DEFAULT_TIMEOUT = 30.0
_CCR_PREFIX = "ccr-14-"
_CACHE_INDEX = "index.json"

#: Same signature `build_corpus` publishes, so a caller can inject either script's fake.
Fetcher = Callable[[str, float], tuple[bytes, str]]


class Status(StrEnum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    UNVERIFIABLE = "unverifiable"


class FailureKind(StrEnum):
    """Why a document could not be read. Never why its content changed."""

    NOT_FOUND = "not_found"  # the address answered 404/410: a fact about the address
    TRANSPORT = "transport"  # timeout, reset, DNS: a fact about the network
    NOT_CHECKED = "not_checked"  # absent from the offline cache: a fact about the cache
    EXTRACTION = "extraction"  # fetched, but no text could be re-derived from it


class WatchInputError(Exception):
    """The watch could not start. Distinct from a source it could not read."""


@dataclass(frozen=True)
class Fetched:
    data: bytes
    content_type: str


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: str


@dataclass(frozen=True)
class DocumentWatch:
    """One document's verdict. The `None`s are the point; see the module docstring."""

    id: str
    url: str
    title: str
    status: Status
    detail: str
    failure_kind: FailureKind | None = None
    recorded_text_sha256: str = ""
    observed_text_sha256: str | None = None
    passages_recorded: int = 0
    passages_surviving: list[str] | None = None
    passages_lost: list[str] | None = None
    rules_bound: tuple[str, ...] = ()
    rules_with_lost_passages: list[str] | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "status": str(self.status),
            "failure_kind": None if self.failure_kind is None else str(self.failure_kind),
            "detail": self.detail,
            "recorded_text_sha256": self.recorded_text_sha256,
            "observed_text_sha256": self.observed_text_sha256,
            "passages_recorded": self.passages_recorded,
            "passages_surviving": self.passages_surviving,
            "passages_lost": self.passages_lost,
            "rules_bound": list(self.rules_bound),
            "rules_with_lost_passages": self.rules_with_lost_passages,
        }


def load_corpus(corpus_dir: Path) -> tuple[CorpusManifest, dict[str, list[Passage]]]:
    """Read the committed manifest and passages, or refuse to run."""

    manifest_path = corpus_dir / "manifest.json"
    passages_path = corpus_dir / "passages.json"
    try:
        manifest = CorpusManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        raw = json.loads(passages_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise WatchInputError(f"corpus could not be read from {corpus_dir}: {error}") from error
    passages = {
        document_id: [Passage.model_validate(item) for item in items]
        for document_id, items in raw.items()
    }
    return manifest, passages


class OfflineCache:
    """A recorded crawl, replayed. Also the only way the tests reach this script.

    The index may record a failure as well as a body, so a `not_found` or a `transport`
    failure can be replayed rather than simulated by deleting a file -- deleting a file
    would replay as `not_checked`, which is a different finding.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        try:
            payload = json.loads((directory / _CACHE_INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise WatchInputError(f"offline cache index could not be read: {error}") from error
        entries = payload.get("documents")
        if not isinstance(entries, dict):
            raise WatchInputError("offline cache index must carry a 'documents' object")
        self.entries: dict[str, dict[str, Any]] = entries

    def get(self, document_id: str) -> Fetched | Failure:
        entry = self.entries.get(document_id)
        if entry is None:
            return Failure(
                FailureKind.NOT_CHECKED,
                "not present in the offline cache; this run says nothing about it",
            )
        if "error" in entry:
            kind = str(entry["error"])
            if kind not in {str(FailureKind.NOT_FOUND), str(FailureKind.TRANSPORT)}:
                raise WatchInputError(f"{document_id}: unknown recorded error {kind!r}")
            return Failure(FailureKind(kind), str(entry.get("detail", kind)))
        try:
            data = (self.directory / str(entry["file"])).read_bytes()
        except (KeyError, OSError) as error:
            raise WatchInputError(f"{document_id}: cache body unreadable: {error}") from error
        return Fetched(data, str(entry.get("content_type", "")))


def fetch_document(
    document: CorpusDocument,
    *,
    fetch: Fetcher,
    timeout: float,
    cache: OfflineCache | None,
) -> Fetched | Failure:
    """Read one document's bytes, classifying any failure by what it is evidence of."""

    if cache is not None:
        return cache.get(document.id)
    local = LOCAL_SOURCE_PATHS.get(document.id)
    if local is not None:
        # A self-cited project document is read from the working tree, exactly as the
        # corpus build reads it. Watching the rendered web view would compare the corpus
        # against a page this project does not control.
        try:
            return Fetched(local.read_bytes(), "text/markdown")
        except OSError as error:
            return Failure(FailureKind.NOT_FOUND, f"local source missing: {error}")
    try:
        data, content_type = fetch(document.url, timeout)
    except urllib.error.HTTPError as error:
        kind = FailureKind.NOT_FOUND if error.code in (404, 410) else FailureKind.TRANSPORT
        return Failure(kind, f"HTTP {error.code}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        return Failure(FailureKind.TRANSPORT, f"{type(error).__name__}: {error}")
    return Fetched(data, content_type)


def _blocks_for(document: CorpusDocument, fetched: Fetched, scratch: Path) -> list[tuple[str, str]]:
    """Re-derive blocks the way `build_corpus` derived them for this document."""

    if document.id in LOCAL_SOURCE_PATHS:
        return markdown_blocks(fetched.data.decode("utf-8"))
    if fetched.content_type == "application/pdf" or fetched.data[:5] == b"%PDF-":
        scratch.mkdir(parents=True, exist_ok=True)
        pdf_path = scratch / f"{document.id}.pdf"
        pdf_path.write_bytes(fetched.data)
        return pdf_blocks(pdf_path)
    page = fetched.data.decode("utf-8", errors="replace")
    if document.id.startswith(_CCR_PREFIX):
        blocks, _title, _edition = ccr_blocks(page)
        return blocks
    return html_blocks(page)


def observe_text(document: CorpusDocument, fetched: Fetched, scratch: Path) -> str | Failure:
    """The document's text as the corpus build would compute it, or why it could not be."""

    try:
        blocks = _blocks_for(document, fetched, scratch)
        passages = passages_from_blocks(document.id, blocks)
    except (ValueError, OSError, UnicodeDecodeError) as error:
        return Failure(FailureKind.EXTRACTION, f"{type(error).__name__}: {error}")
    if not passages:
        # Zero passages from a document that previously had some is not "every passage
        # was removed": it is far more often an extractor that no longer understands the
        # page. Reported as unread, not as total loss.
        return Failure(FailureKind.EXTRACTION, "no passage could be extracted from the response")
    return "\n\n".join(passage.text for passage in passages) + "\n"


def _unverifiable(document: CorpusDocument, failure: Failure) -> DocumentWatch:
    return DocumentWatch(
        id=document.id,
        url=document.url,
        title=document.title,
        status=Status.UNVERIFIABLE,
        failure_kind=failure.kind,
        detail=failure.detail,
        recorded_text_sha256=document.text_sha256,
        observed_text_sha256=None,
        passages_recorded=document.passage_count,
        # null, never []. Nothing was read, so no passage was found or lost.
        passages_surviving=None,
        passages_lost=None,
        rules_bound=tuple(document.cited_by),
        rules_with_lost_passages=None,
    )


def compare(
    document: CorpusDocument,
    recorded_passages: list[Passage],
    observed_text: str,
) -> DocumentWatch:
    """Classify a document whose text was successfully re-derived."""

    observed_sha = hashlib.sha256(observed_text.encode("utf-8")).hexdigest()
    surviving = [passage.id for passage in recorded_passages if passage.text in observed_text]
    lost = [passage.id for passage in recorded_passages if passage.text not in observed_text]
    unchanged = observed_sha == document.text_sha256
    detail = (
        "text hash matches the corpus"
        if unchanged
        else f"{len(lost)} of {len(recorded_passages)} retained passage(s) no longer occur verbatim"
    )
    return DocumentWatch(
        id=document.id,
        url=document.url,
        title=document.title,
        status=Status.UNCHANGED if unchanged else Status.CHANGED,
        detail=detail,
        recorded_text_sha256=document.text_sha256,
        observed_text_sha256=observed_sha,
        passages_recorded=len(recorded_passages),
        passages_surviving=surviving,
        passages_lost=lost,
        rules_bound=tuple(document.cited_by),
        rules_with_lost_passages=sorted(document.cited_by) if lost else [],
    )


def watch_document(
    document: CorpusDocument,
    recorded_passages: list[Passage],
    *,
    fetch: Fetcher,
    timeout: float,
    cache: OfflineCache | None,
    scratch: Path,
) -> DocumentWatch:
    outcome = fetch_document(document, fetch=fetch, timeout=timeout, cache=cache)
    if isinstance(outcome, Failure):
        return _unverifiable(document, outcome)
    observed = observe_text(document, outcome, scratch)
    if isinstance(observed, Failure):
        return _unverifiable(document, observed)
    return compare(document, recorded_passages, observed)


def summarize(watches: list[DocumentWatch]) -> dict[str, Any]:
    """Counts that keep "not examined" apart from "examined and clean"."""

    examined = [w for w in watches if w.passages_lost is not None]
    unread = [w for w in watches if w.passages_lost is None]
    affected: set[str] = set()
    for watch in examined:
        affected.update(watch.rules_with_lost_passages or [])
    return {
        "documents": len(watches),
        "unchanged": sum(1 for w in watches if w.status is Status.UNCHANGED),
        "changed": sum(1 for w in watches if w.status is Status.CHANGED),
        "unverifiable": len(unread),
        "unverifiable_by_kind": {
            str(kind): sum(1 for w in unread if w.failure_kind is kind)
            for kind in FailureKind
            if any(w.failure_kind is kind for w in unread)
        },
        "passages_recorded": sum(w.passages_recorded for w in watches),
        "passages_examined": sum(w.passages_recorded for w in examined),
        # Deliberately separate: adding these two together would present unread
        # passages as passages that survived.
        "passages_not_examined": sum(w.passages_recorded for w in unread),
        "passages_lost": sum(len(w.passages_lost or []) for w in examined),
        "rules_with_lost_passages": sorted(affected),
    }


def run(
    corpus_dir: Path,
    *,
    fetch: Fetcher,
    timeout: float,
    cache_dir: Path | None,
    document_ids: list[str] | None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    manifest, passages = load_corpus(corpus_dir)
    cache = OfflineCache(cache_dir) if cache_dir is not None else None
    selected = sorted(manifest.documents, key=lambda document: document.id)
    if document_ids:
        wanted = set(document_ids)
        selected = [document for document in selected if document.id in wanted]
        missing = sorted(wanted - {document.id for document in selected})
        if missing:
            raise WatchInputError(f"not in the corpus manifest: {', '.join(missing)}")
    watches: list[DocumentWatch] = []
    with tempfile.TemporaryDirectory(prefix="ceqa-source-watch-") as scratch_dir:
        scratch = Path(scratch_dir)
        for document in selected:
            watches.append(
                watch_document(
                    document,
                    passages.get(document.id, []),
                    fetch=fetch,
                    timeout=timeout,
                    cache=cache,
                    scratch=scratch,
                )
            )
    return {
        "watch_schema_version": WATCH_SCHEMA_VERSION,
        "checked_at": (checked_at or datetime.now(UTC)).isoformat().replace("+00:00", "Z"),
        "read_from": "offline-cache" if cache is not None else "network",
        "corpus_built_at": manifest.built_at.isoformat().replace("+00:00", "Z"),
        "adopts_nothing": (
            "This record reports what the sources said when they were read. It changes "
            "no rule, rebuilds no corpus, and is not a review."
        ),
        "summary": summarize(watches),
        "documents": [watch.as_json() for watch in watches],
    }


def _default_output(checked_at: datetime) -> Path:
    return ROOT / "docs" / "audits" / f"source-watch-{checked_at.date().isoformat()}.json"


def _print_report(record: dict[str, Any]) -> None:
    summary = record["summary"]
    for document in record["documents"]:
        if document["status"] == "unchanged":
            continue
        kind = document["failure_kind"]
        label = document["status"] if kind is None else f"{document['status']}/{kind}"
        print(f"[{label}] {document['id']}: {document['detail']}")
        if document["passages_lost"]:
            print(f"    lost passages: {', '.join(document['passages_lost'])}")
            print(f"    rules bound to this document: {', '.join(document['rules_bound']) or '—'}")
    print(
        f"\n{summary['documents']} document(s): {summary['unchanged']} unchanged, "
        f"{summary['changed']} changed, {summary['unverifiable']} unverifiable."
    )
    print(
        f"{summary['passages_examined']} passage(s) examined, "
        f"{summary['passages_lost']} lost; "
        f"{summary['passages_not_examined']} not examined."
    )


def main(argv: list[str] | None = None, fetch: Fetcher = _network_fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "corpus")
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    parser.add_argument(
        "--offline-cache",
        type=Path,
        default=None,
        help=f"replay a recorded crawl from DIR (needs DIR/{_CACHE_INDEX})",
    )
    parser.add_argument(
        "--document",
        action="append",
        default=None,
        help="watch only this corpus document id (repeatable)",
    )
    parser.add_argument("--output", type=Path, default=None, help="where to write the record")
    args = parser.parse_args(argv)

    checked_at = datetime.now(UTC)
    try:
        record = run(
            args.corpus_dir,
            fetch=fetch,
            timeout=args.timeout,
            cache_dir=args.offline_cache,
            document_ids=args.document,
            checked_at=checked_at,
        )
    except WatchInputError as error:
        print(f"source watch could not run: {error}", file=sys.stderr)
        return 2

    destination = args.output or _default_output(checked_at)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    _print_report(record)
    print(f"\nWrote {destination}. This record adopts nothing.")
    summary = record["summary"]
    return 0 if summary["changed"] == 0 and summary["unverifiable"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
