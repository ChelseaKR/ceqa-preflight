"""Tests for scripts/watch_sources.py.

No test here opens a socket. Every run is either an offline-cache replay or a run with a
fake `fetch` injected in place of the script's `urllib`-backed default, per the script's
own no-hidden-network-path rule.

The fixtures are a synthetic four-document corpus rather than the committed one, because
`corpus/` retains derived *text*, not the source bytes it came from: an "unchanged"
verdict can only be exercised against a source that reproduces its own recorded hash, and
that means building both halves here.

What these tests are really about is the difference between three verdicts that a careless
implementation collapses into one:

* ``unchanged`` — read, and it hashes to what the corpus recorded.
* ``changed`` — read, and it does not; the retained passages are then checked one by one.
* ``unverifiable`` — **not read**. It has no passage lists at all, because a source nobody
  could read has neither kept nor lost anything.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import watch_sources  # type: ignore[import-not-found]  # noqa: E402
from build_corpus import (  # type: ignore[import-not-found]  # noqa: E402
    html_blocks,
    passages_from_blocks,
)
from watch_sources import FailureKind, Status, WatchInputError  # noqa: E402

_FIRST = "Alpha " * 20
_SECOND = "Beta " * 20
_THIRD = "Gamma " * 20


def _page(*sections: tuple[str, str]) -> str:
    body = "".join(f"<h2>{heading}</h2><p>{text}</p>" for heading, text in sections)
    return f"<html><body>{body}</body></html>"


#: The bytes each document served when the corpus was built.
RECORDED_PAGES: dict[str, str] = {
    "doc-unchanged": _page(("One", _FIRST), ("Two", _SECOND)),
    "doc-changed": _page(("One", _FIRST), ("Two", _SECOND), ("Three", _THIRD)),
    "doc-gone": _page(("One", _FIRST)),
    "doc-flaky": _page(("One", _SECOND)),
}

CITED_BY: dict[str, list[str]] = {
    "doc-unchanged": ["PDF-001"],
    "doc-changed": ["FILE-002", "PDF-006"],
    "doc-gone": ["NOD-001"],
    "doc-flaky": [],
}


def _derive(document_id: str, page: str) -> tuple[str, list[dict[str, object]]]:
    """Text and passages exactly as `build_corpus` derives them."""

    passages = passages_from_blocks(document_id, html_blocks(page))
    text = "\n\n".join(passage.text for passage in passages) + "\n"
    return text, [passage.model_dump(mode="json") for passage in passages]


def _write_corpus(directory: Path) -> None:
    documents = []
    passages: dict[str, list[dict[str, object]]] = {}
    for document_id, page in RECORDED_PAGES.items():
        text, entries = _derive(document_id, page)
        passages[document_id] = entries
        documents.append(
            {
                "id": document_id,
                "title": f"Synthetic {document_id}",
                "url": f"https://example.invalid/{document_id}",
                "kind": "official",
                "retrieved_at": "2026-01-01T00:00:00Z",
                "content_type": "text/html",
                "source_sha256": hashlib.sha256(page.encode("utf-8")).hexdigest(),
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "passage_count": len(entries),
                "cited_by": CITED_BY[document_id],
            }
        )
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": "1.0",
                "built_at": "2026-01-01T00:00:00Z",
                "documents": documents,
            }
        ),
        encoding="utf-8",
    )
    (directory / "passages.json").write_text(json.dumps(passages), encoding="utf-8")


def _write_cache(directory: Path, served: dict[str, object]) -> None:
    """`served` maps a document id to a page string or to a recorded failure dict."""

    entries: dict[str, object] = {}
    for document_id, value in served.items():
        if isinstance(value, dict):
            entries[document_id] = value
            continue
        name = f"{document_id}.html"
        (directory / name).write_text(str(value), encoding="utf-8")
        entries[document_id] = {"file": name, "content_type": "text/html"}
    (directory / "index.json").write_text(json.dumps({"documents": entries}), encoding="utf-8")


class WatchFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.corpus = self.root / "corpus"
        self.cache = self.root / "cache"
        self.corpus.mkdir()
        self.cache.mkdir()
        _write_corpus(self.corpus)

    def run_watch(self, served: dict[str, object]) -> dict[str, object]:
        _write_cache(self.cache, served)
        return watch_sources.run(
            self.corpus,
            fetch=self._forbidden_fetch,
            timeout=1.0,
            cache_dir=self.cache,
            document_ids=None,
            checked_at=datetime(2026, 9, 7, tzinfo=UTC),
        )

    @staticmethod
    def _forbidden_fetch(url: str, timeout: float) -> tuple[bytes, str]:
        raise AssertionError(f"an offline replay must not fetch {url}")

    @staticmethod
    def document(record: dict[str, object], document_id: str) -> dict[str, object]:
        matching = [
            item
            for item in record["documents"]  # type: ignore[index]
            if item["id"] == document_id
        ]
        assert len(matching) == 1, document_id
        return dict(matching[0])


class ClassificationTests(WatchFixture):
    def _mixed_run(self) -> dict[str, object]:
        changed_page = _page(("One", _FIRST), ("Two", _SECOND), ("Three", "Delta " * 20))
        return self.run_watch(
            {
                "doc-unchanged": RECORDED_PAGES["doc-unchanged"],
                "doc-changed": changed_page,
                "doc-gone": {"error": "not_found", "detail": "HTTP 410"},
                "doc-flaky": {"error": "transport", "detail": "TimeoutError: timed out"},
            }
        )

    def test_an_unchanged_document_is_reported_unchanged(self) -> None:
        document = self.document(self._mixed_run(), "doc-unchanged")
        self.assertEqual(document["status"], str(Status.UNCHANGED))
        self.assertIsNone(document["failure_kind"])
        self.assertEqual(document["observed_text_sha256"], document["recorded_text_sha256"])
        self.assertEqual(document["passages_lost"], [])
        self.assertEqual(len(document["passages_surviving"]), 2)  # type: ignore[arg-type]
        self.assertEqual(document["rules_with_lost_passages"], [])

    def test_a_changed_document_names_the_lost_passages_and_the_bound_rules(self) -> None:
        document = self.document(self._mixed_run(), "doc-changed")
        self.assertEqual(document["status"], str(Status.CHANGED))
        self.assertEqual(document["passages_lost"], ["doc-changed#p003"])
        self.assertEqual(document["passages_surviving"], ["doc-changed#p001", "doc-changed#p002"])
        self.assertEqual(document["rules_with_lost_passages"], ["FILE-002", "PDF-006"])

    def test_a_404_is_not_found_and_marks_no_passage_lost(self) -> None:
        document = self.document(self._mixed_run(), "doc-gone")
        self.assertEqual(document["status"], str(Status.UNVERIFIABLE))
        self.assertEqual(document["failure_kind"], str(FailureKind.NOT_FOUND))
        # null, never []: an empty list of lost passages reads as a clean bill of health,
        # and an unread source has not earned one.
        self.assertIsNone(document["passages_lost"])
        self.assertIsNone(document["passages_surviving"])
        self.assertIsNone(document["rules_with_lost_passages"])
        self.assertIsNone(document["observed_text_sha256"])
        # The rules bound to it are still named, because a reader needs to know what is
        # standing on an unread source.
        self.assertEqual(document["rules_bound"], ["NOD-001"])

    def test_a_timeout_is_transport_and_marks_no_passage_lost(self) -> None:
        document = self.document(self._mixed_run(), "doc-flaky")
        self.assertEqual(document["status"], str(Status.UNVERIFIABLE))
        self.assertEqual(document["failure_kind"], str(FailureKind.TRANSPORT))
        self.assertIsNone(document["passages_lost"])

    def test_a_document_missing_from_the_cache_is_not_checked(self) -> None:
        record = self.run_watch({"doc-unchanged": RECORDED_PAGES["doc-unchanged"]})
        document = self.document(record, "doc-changed")
        self.assertEqual(document["failure_kind"], str(FailureKind.NOT_CHECKED))
        self.assertIn("says nothing about it", document["detail"])  # type: ignore[arg-type]
        self.assertIsNone(document["passages_lost"])

    def test_a_response_with_no_extractable_text_is_unread_not_emptied(self) -> None:
        """A page the extractor no longer understands is far more common than a source
        that deleted every passage, and the two must not render the same."""
        record = self.run_watch(
            {
                "doc-unchanged": "<html><body></body></html>",
                "doc-changed": RECORDED_PAGES["doc-changed"],
                "doc-gone": RECORDED_PAGES["doc-gone"],
                "doc-flaky": RECORDED_PAGES["doc-flaky"],
            }
        )
        document = self.document(record, "doc-unchanged")
        self.assertEqual(document["status"], str(Status.UNVERIFIABLE))
        self.assertEqual(document["failure_kind"], str(FailureKind.EXTRACTION))
        self.assertIsNone(document["passages_lost"])

    def test_a_reordered_document_is_changed_even_though_no_passage_is_lost(self) -> None:
        """The hash and the passage check answer different questions, and the record
        keeps both: every passage can survive verbatim while the document as a whole no
        longer matches what was retained."""
        reordered = _page(("Two", _SECOND), ("One", _FIRST))
        record = self.run_watch(
            {
                "doc-unchanged": reordered,
                "doc-changed": RECORDED_PAGES["doc-changed"],
                "doc-gone": RECORDED_PAGES["doc-gone"],
                "doc-flaky": RECORDED_PAGES["doc-flaky"],
            }
        )
        document = self.document(record, "doc-unchanged")
        self.assertEqual(document["status"], str(Status.CHANGED))
        self.assertEqual(document["passages_lost"], [])
        self.assertEqual(document["rules_with_lost_passages"], [])


class SummaryTests(WatchFixture):
    def test_unread_passages_are_counted_apart_from_examined_ones(self) -> None:
        record = self.run_watch(
            {
                "doc-unchanged": RECORDED_PAGES["doc-unchanged"],
                "doc-changed": _page(("One", _FIRST), ("Two", _SECOND)),
                "doc-gone": {"error": "not_found", "detail": "HTTP 404"},
            }
        )
        summary = dict(record["summary"])  # type: ignore[arg-type]
        self.assertEqual(summary["documents"], 4)
        self.assertEqual(summary["unchanged"], 1)
        self.assertEqual(summary["changed"], 1)
        self.assertEqual(summary["unverifiable"], 2)
        self.assertEqual(summary["unverifiable_by_kind"], {"not_found": 1, "not_checked": 1})
        # 2 + 3 examined, 1 + 1 not examined; adding them would present unread passages
        # as passages that survived.
        self.assertEqual(summary["passages_examined"], 5)
        self.assertEqual(summary["passages_not_examined"], 2)
        self.assertEqual(summary["passages_recorded"], 7)
        self.assertEqual(summary["passages_lost"], 1)
        self.assertEqual(summary["rules_with_lost_passages"], ["FILE-002", "PDF-006"])

    def test_the_record_says_it_adopts_nothing(self) -> None:
        record = self.run_watch({})
        self.assertIn("changes no rule", str(record["adopts_nothing"]))
        self.assertEqual(record["read_from"], "offline-cache")
        self.assertEqual(record["watch_schema_version"], watch_sources.WATCH_SCHEMA_VERSION)


class SelectionAndInputTests(WatchFixture):
    def test_only_the_requested_document_is_watched(self) -> None:
        _write_cache(self.cache, {"doc-unchanged": RECORDED_PAGES["doc-unchanged"]})
        record = watch_sources.run(
            self.corpus,
            fetch=self._forbidden_fetch,
            timeout=1.0,
            cache_dir=self.cache,
            document_ids=["doc-unchanged"],
        )
        self.assertEqual([item["id"] for item in record["documents"]], ["doc-unchanged"])

    def test_an_unknown_document_id_refuses_rather_than_watching_nothing(self) -> None:
        _write_cache(self.cache, {})
        with self.assertRaises(WatchInputError):
            watch_sources.run(
                self.corpus,
                fetch=self._forbidden_fetch,
                timeout=1.0,
                cache_dir=self.cache,
                document_ids=["doc-imaginary"],
            )

    def test_a_missing_corpus_refuses_to_run(self) -> None:
        with self.assertRaises(WatchInputError):
            watch_sources.run(
                self.root / "absent",
                fetch=self._forbidden_fetch,
                timeout=1.0,
                cache_dir=None,
                document_ids=None,
            )

    def test_an_unreadable_cache_index_refuses_to_run(self) -> None:
        (self.cache / "index.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(WatchInputError):
            watch_sources.run(
                self.corpus,
                fetch=self._forbidden_fetch,
                timeout=1.0,
                cache_dir=self.cache,
                document_ids=None,
            )

    def test_a_cache_recording_an_unknown_error_kind_refuses_to_run(self) -> None:
        _write_cache(self.cache, {"doc-unchanged": {"error": "probably_fine"}})
        with self.assertRaises(WatchInputError):
            watch_sources.run(
                self.corpus,
                fetch=self._forbidden_fetch,
                timeout=1.0,
                cache_dir=self.cache,
                document_ids=None,
            )


class NetworkFailureClassificationTests(WatchFixture):
    """The same classification, reached through the injected fetcher rather than a cache."""

    def _run_with(self, error: Exception) -> dict[str, object]:
        def fetch(url: str, timeout: float) -> tuple[bytes, str]:
            raise error

        return watch_sources.run(
            self.corpus,
            fetch=fetch,
            timeout=1.0,
            cache_dir=None,
            document_ids=["doc-unchanged"],
        )

    def test_http_404_classifies_as_not_found(self) -> None:
        record = self._run_with(
            urllib.error.HTTPError("https://example.invalid", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        )
        self.assertEqual(
            self.document(record, "doc-unchanged")["failure_kind"], str(FailureKind.NOT_FOUND)
        )

    def test_http_500_classifies_as_transport_not_as_a_missing_document(self) -> None:
        record = self._run_with(
            urllib.error.HTTPError("https://example.invalid", 500, "Server Error", {}, None)  # type: ignore[arg-type]
        )
        self.assertEqual(
            self.document(record, "doc-unchanged")["failure_kind"], str(FailureKind.TRANSPORT)
        )

    def test_a_url_error_classifies_as_transport(self) -> None:
        record = self._run_with(urllib.error.URLError("connection reset"))
        self.assertEqual(
            self.document(record, "doc-unchanged")["failure_kind"], str(FailureKind.TRANSPORT)
        )

    def test_a_successful_fetch_is_compared(self) -> None:
        page = RECORDED_PAGES["doc-unchanged"].encode("utf-8")

        def fetch(url: str, timeout: float) -> tuple[bytes, str]:
            return page, "text/html"

        record = watch_sources.run(
            self.corpus,
            fetch=fetch,
            timeout=1.0,
            cache_dir=None,
            document_ids=["doc-unchanged"],
        )
        self.assertEqual(self.document(record, "doc-unchanged")["status"], str(Status.UNCHANGED))


class ExitCodeTests(WatchFixture):
    def _main(self, served: dict[str, object]) -> int:
        _write_cache(self.cache, served)
        return watch_sources.main(
            [
                "--corpus-dir",
                str(self.corpus),
                "--offline-cache",
                str(self.cache),
                "--output",
                str(self.root / "record.json"),
            ],
            fetch=self._forbidden_fetch,
        )

    def test_all_unchanged_exits_zero(self) -> None:
        self.assertEqual(self._main(dict(RECORDED_PAGES)), 0)

    def test_a_changed_document_exits_one(self) -> None:
        served = dict(RECORDED_PAGES)
        served["doc-changed"] = _page(("One", _FIRST))
        self.assertEqual(self._main(served), 1)

    def test_an_unverifiable_document_also_exits_one(self) -> None:
        """A run that exited 0 while a source could not be read would be reporting an
        absence as a clean result, which is the whole defect this watch exists to name."""
        served: dict[str, object] = dict(RECORDED_PAGES)
        served["doc-gone"] = {"error": "transport", "detail": "TimeoutError"}
        self.assertEqual(self._main(served), 1)

    def test_a_missing_corpus_exits_two(self) -> None:
        code = watch_sources.main(
            ["--corpus-dir", str(self.root / "absent")], fetch=self._forbidden_fetch
        )
        self.assertEqual(code, 2)

    def test_the_written_record_round_trips(self) -> None:
        self._main(dict(RECORDED_PAGES))
        record = json.loads((self.root / "record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["watch_schema_version"], watch_sources.WATCH_SCHEMA_VERSION)
        self.assertEqual([item["id"] for item in record["documents"]], sorted(RECORDED_PAGES))


class CommittedCorpusTests(unittest.TestCase):
    """The real corpus is readable by the watch, without fetching anything."""

    def test_the_committed_corpus_loads_and_binds_rules(self) -> None:
        manifest, passages = watch_sources.load_corpus(
            Path(__file__).resolve().parent.parent / "corpus"
        )
        self.assertGreater(len(manifest.documents), 0)
        for document in manifest.documents:
            self.assertEqual(len(passages.get(document.id, [])), document.passage_count)
        cited = {rule for document in manifest.documents for rule in document.cited_by}
        self.assertGreater(len(cited), 0)


if __name__ == "__main__":
    unittest.main()
