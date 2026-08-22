"""Tests for the committed official-source corpus and its verifier."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ceqa_preflight.ai.corpus import (
    Corpus,
    CorpusDocument,
    CorpusError,
    CorpusManifest,
    Passage,
    default_corpus_dir,
    normalize_for_match,
    normalize_whitespace,
)
from ceqa_preflight.models import SourceKind
from ceqa_preflight.rule_registry import default_catalog


def _write_corpus(
    root: Path,
    texts: dict[str, str],
    passages: dict[str, list[Passage]],
    *,
    kind: SourceKind = SourceKind.OFFICIAL,
) -> None:
    (root / "text").mkdir(parents=True, exist_ok=True)
    documents = []
    for document_id, text in texts.items():
        (root / "text" / f"{document_id}.txt").write_text(text, encoding="utf-8")
        documents.append(
            CorpusDocument(
                id=document_id,
                title=f"Title of {document_id}",
                url=f"https://example.test/{document_id}",
                kind=kind,
                retrieved_at=datetime.now(UTC),
                content_type="text/plain",
                source_sha256="0" * 64,
                text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                passage_count=len(passages.get(document_id, [])),
            )
        )
    manifest = CorpusManifest(built_at=datetime.now(UTC), documents=documents)
    (root / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (root / "passages.json").write_text(
        json.dumps(
            {
                document_id: [passage.model_dump(mode="json") for passage in entries]
                for document_id, entries in passages.items()
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def small_corpus(tmp_path: Path) -> Path:
    text = (
        "Documents are fully text-searchable (OCR-enabled).\n\n"
        "Files are flattened and contain no fillable form fields.\n"
    )
    passages = {
        "guide": [
            Passage(
                id="guide#p001",
                heading="Text searchability",
                text="Documents are fully text-searchable (OCR-enabled).",
            ),
            Passage(
                id="guide#p002",
                heading="Text searchability",
                text="Files are flattened and contain no fillable form fields.",
            ),
        ]
    }
    _write_corpus(tmp_path, {"guide": text}, passages)
    return tmp_path


def test_normalize_whitespace_collapses_wrapping() -> None:
    assert normalize_whitespace("  a\n  b\t c ") == "a b c"


def test_normalize_for_match_folds_typography_but_not_words() -> None:
    curly = "categorized as \u201cNotice of Completion.\u201d \u2013 Misclassi\ufb01ed"
    assert normalize_for_match(curly) == 'categorized as "Notice of Completion." - Misclassified'
    assert normalize_for_match("it\u2019s") == "it's"
    assert normalize_for_match("Notice") != normalize_for_match("Notices")


def test_committed_corpus_loads_and_verifies() -> None:
    """The corpus in the repository must verify against its own manifest."""

    corpus = Corpus.load()
    assert default_corpus_dir().is_dir()
    assert corpus.documents
    for document in corpus.documents:
        assert document.passage_count == len(corpus.passages(document.id))
        assert document.retrieved_at.tzinfo is not None


def test_every_catalog_citation_is_held_in_the_corpus() -> None:
    """Explanations can only quote text that is here, so every cited URL must be here."""

    corpus = Corpus.load()
    for rule in default_catalog().rules:
        document = corpus.document_for_url(rule.source.url)
        assert document is not None, rule.id
        assert rule.id in document.cited_by
        assert document.kind is rule.source.kind


def test_self_cited_rules_are_marked_as_project_advisory_in_the_corpus() -> None:
    """Issue #38: a reader must be able to tell a self-citation from an official source."""

    corpus = Corpus.load()
    catalog = {rule.id: rule for rule in default_catalog().rules}
    for rule_id in ("FILE-004", "FILE-005"):
        document = corpus.document_for_url(catalog[rule_id].source.url)
        assert document is not None
        assert document.kind is SourceKind.PROJECT_ADVISORY
        assert any("No official size limit" in p.text for p in corpus.passages(document.id))


def test_quote_verifies_modulo_whitespace(small_corpus: Path) -> None:
    corpus = Corpus.load(small_corpus)
    assert corpus.quote_verifies("guide#p001", "fully   text-searchable\n(OCR-enabled)")
    assert (
        corpus.quote_verifies("guide#p001", "fully text\u2011searchable") is False
    )  # not a typographic fold
    assert corpus.quote_verifies("guide#p001", "text-searchable (OCR\u2010enabled)") is False
    assert not corpus.quote_verifies("guide#p001", "fully text-searchable (OCR enabled)")
    assert not corpus.quote_verifies("guide#p001", "")
    assert not corpus.quote_verifies("guide#p999", "Documents")


def test_retrieve_ranks_by_lexical_overlap_and_is_deterministic(small_corpus: Path) -> None:
    corpus = Corpus.load(small_corpus)
    ranked = corpus.retrieve(["guide"], "fillable form fields flattened", limit=1)
    assert [passage.id for passage in ranked] == ["guide#p002"]
    tie = corpus.retrieve(["guide"], "zzz", limit=5)
    assert [passage.id for passage in tie] == ["guide#p001", "guide#p002"]


def test_document_lookup_errors(small_corpus: Path) -> None:
    corpus = Corpus.load(small_corpus)
    assert corpus.document_for_url("https://example.test/missing") is None
    assert corpus.passage("guide#p001") is not None
    with pytest.raises(CorpusError, match="unknown corpus document"):
        corpus.passages("missing")


def test_tampered_text_is_refused(small_corpus: Path) -> None:
    path = small_corpus / "text" / "guide.txt"
    path.write_text(path.read_text(encoding="utf-8") + "An invented sentence.\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="does not match its manifest hash"):
        Corpus.load(small_corpus)


def test_missing_text_is_refused(small_corpus: Path) -> None:
    (small_corpus / "text" / "guide.txt").unlink()
    with pytest.raises(CorpusError, match="missing"):
        Corpus.load(small_corpus)


def test_passage_count_drift_is_refused(small_corpus: Path) -> None:
    passages = json.loads((small_corpus / "passages.json").read_text(encoding="utf-8"))
    passages["guide"].pop()
    (small_corpus / "passages.json").write_text(json.dumps(passages), encoding="utf-8")
    with pytest.raises(CorpusError, match="passage count"):
        Corpus.load(small_corpus)


def test_passage_filed_under_the_wrong_document_is_refused(small_corpus: Path) -> None:
    passages = json.loads((small_corpus / "passages.json").read_text(encoding="utf-8"))
    passages["guide"][0]["id"] = "other#p001"
    (small_corpus / "passages.json").write_text(json.dumps(passages), encoding="utf-8")
    with pytest.raises(CorpusError, match="is filed under"):
        Corpus.load(small_corpus)


def test_passage_text_absent_from_document_is_refused(small_corpus: Path) -> None:
    passages = json.loads((small_corpus / "passages.json").read_text(encoding="utf-8"))
    passages["guide"][0]["text"] = "Text that the document does not contain."
    (small_corpus / "passages.json").write_text(json.dumps(passages), encoding="utf-8")
    with pytest.raises(CorpusError, match="not in its document text"):
        Corpus.load(small_corpus)


def test_malformed_manifest_and_passages_are_refused(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="manifest could not be loaded"):
        Corpus.load(tmp_path)
    (tmp_path / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(CorpusError, match="manifest could not be loaded"):
        Corpus.load(tmp_path)
    shutil.copytree(default_corpus_dir(), tmp_path / "copy")
    (tmp_path / "copy" / "passages.json").write_text("[]", encoding="utf-8")
    with pytest.raises(CorpusError, match="passages must be a mapping"):
        Corpus.load(tmp_path / "copy")
    (tmp_path / "copy" / "passages.json").write_text('{"x": [{"bad": 1}]}', encoding="utf-8")
    with pytest.raises(CorpusError, match="passages could not be loaded"):
        Corpus.load(tmp_path / "copy")


def test_document_for_section_finds_ccr_sections(small_corpus: Path) -> None:
    corpus = Corpus.load(small_corpus)
    assert corpus.document_for_section("15062") is None
    ccr_text = "(a) A notice of exemption shall include a brief description of the project.\n"
    passages = {
        "ccr-14-15062": [Passage(id="ccr-14-15062#p001", heading="§ 15062.", text=ccr_text.strip())]
    }
    _write_corpus(small_corpus / "ccr", {"ccr-14-15062": ccr_text}, passages)
    manifest = json.loads((small_corpus / "ccr" / "manifest.json").read_text(encoding="utf-8"))
    manifest["documents"][0]["section"] = "15062"
    manifest["documents"][0]["edition"] = "current through 8/14/26 Register 2026, No. 33."
    (small_corpus / "ccr" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    held = Corpus.load(small_corpus / "ccr").document_for_section("15062")
    assert held is not None and held.edition and held.id == "ccr-14-15062"


def test_committed_corpus_holds_the_guidelines_sections_the_rules_are_wired_to() -> None:
    """Every section a rule pack names must be held, labeled official, with an edition."""

    corpus = Corpus.load()
    for rule in default_catalog().rules:
        for section in rule.guidelines:
            document = corpus.document_for_section(section)
            assert document is not None, f"{rule.id} is wired to 14 CCR § {section}"
            assert document.kind is SourceKind.OFFICIAL
            assert document.edition and "current through" in document.edition
            assert rule.id in document.cited_by
            assert document.url.startswith("https://govt.westlaw.com/calregs/")
    assert corpus.document_for_section("15000") is not None  # the chapter starts here
    # The form appendices (A, C, D, E) are images in the official edition; no text to hold.
    assert not any(document.id == "ccr-14-appendix-e" for document in corpus.documents)
    assert any(document.id == "ccr-14-appendix-g" for document in corpus.documents)
    editions = {document.edition for document in corpus.documents if document.section}
    assert len(editions) == 1, "every section must come from one retrieval of one edition"
