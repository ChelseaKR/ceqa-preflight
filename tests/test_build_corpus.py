"""Tests for scripts/build_corpus.py.

No test here touches the network: the fetcher is always a fake, per the script's own rule
that the product and its suite make no real network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from ceqa_preflight.ai.corpus import Corpus
from ceqa_preflight.synth import _pdf_bytes

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import build_corpus  # type: ignore[import-not-found]  # noqa: E402

_HTML = """
<html><head><title>t</title><script>var x = 1;</script></head>
<body><nav><p>Skip this navigation text entirely</p></nav>
<main>
<h1>Frequently asked questions</h1>
<details><summary>What can I file?</summary>
<div><p>The NOD form and the final document. This sentence is long enough to keep.</p>
<p>Second paragraph with <strong>bold</strong> text and a<br>break inside it as well.</p></div>
</details>
<ul><li>A list item that is also long enough to be kept as a passage of text.</li></ul>
</main>
<footer><p>Footer text that must not be in the corpus at all, ever.</p></footer>
</body></html>
"""

_MARKDOWN = """# Title

Intro paragraph that is long enough to become a passage in the corpus text.

## Table

| Rule | Source | Decision |
| --- | --- | --- |
| `X-1` thing | No official limit is documented anywhere. | Advisory only. |
"""


def test_html_blocks_keep_main_content_and_drop_chrome() -> None:
    blocks = build_corpus.html_blocks(_HTML)
    kinds = [kind for kind, _ in blocks]
    texts = [text for _, text in blocks]
    assert kinds[:2] == ["heading", "heading"]
    assert texts[0] == "Frequently asked questions"
    assert texts[1] == "What can I file?"
    assert any(text.startswith("The NOD form") for text in texts)
    assert any("break inside it" in text for text in texts)
    assert not any("navigation" in text for text in texts)
    assert not any("Footer" in text for text in texts)
    assert not any("var x" in text for text in texts)


def test_markdown_blocks_split_headings_and_table_rows() -> None:
    blocks = build_corpus.markdown_blocks(_MARKDOWN)
    assert ("heading", "Title") in blocks
    assert ("heading", "Table") in blocks
    rows = [text for kind, text in blocks if text.startswith("`X-1`")]
    assert rows == ["`X-1` thing — No official limit is documented anywhere. — Advisory only."]
    assert not any(set(text) <= {"-", " ", "—"} for _, text in blocks)


def test_pdf_blocks_mark_numbered_section_headings(tmp_path: Path) -> None:
    path = tmp_path / "guide.pdf"
    path.write_bytes(_pdf_bytes(["3. Text Searchability"]))
    blocks = build_corpus.pdf_blocks(path)
    assert ("heading", "3. Text Searchability") in blocks


def test_passages_group_under_headings_and_drop_fragments() -> None:
    long_text = "x" * 700
    blocks = [
        ("paragraph", "12"),  # a page number; dropped
        ("heading", "1. First"),
        ("paragraph", long_text),
        ("paragraph", long_text),  # would exceed the cap, so a new passage starts
        ("heading", "2. Second"),
        ("paragraph", "A short but sufficiently long sentence about the second section here."),
    ]
    passages = build_corpus.passages_from_blocks("doc", blocks)
    assert [passage.id for passage in passages] == ["doc#p001", "doc#p002", "doc#p003"]
    assert passages[0].heading == "1. First"
    assert passages[2].heading == "2. Second"
    assert all(len(passage.text) <= build_corpus._MAX_PASSAGE_CHARS for passage in passages)


def test_build_writes_a_corpus_that_loads(tmp_path: Path) -> None:
    pdf = _pdf_bytes(["Documents are fully text-searchable and flattened before upload."])

    def fetch(url: str, timeout: float) -> tuple[bytes, str]:
        if url.endswith(".pdf"):
            return pdf, "application/pdf"
        return _HTML.encode("utf-8"), "text/html"

    assert build_corpus.main(["--corpus-dir", str(tmp_path), "--no-ccr"], fetch=fetch) == 0
    corpus = Corpus.load(tmp_path)
    ids = {document.id for document in corpus.documents}
    assert "lci-sch-faq" in ids
    assert "ceqa-preflight-source-review-addendum-2026-07-27" in ids
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert all(len(document["source_sha256"]) == 64 for document in manifest["documents"])
    assert not (tmp_path / ".build").exists()


def test_build_reports_fetch_failures(tmp_path: Path) -> None:
    def fetch(url: str, timeout: float) -> tuple[bytes, str]:
        raise ValueError("boom")

    assert build_corpus.main(["--corpus-dir", str(tmp_path), "--no-ccr"], fetch=fetch) == 1


def test_real_fetch_rejects_non_http_schemes() -> None:
    with pytest.raises(ValueError, match="unsupported URL scheme"):
        build_corpus._fetch("file:///etc/passwd", 1.0)


def test_every_catalog_url_has_a_stable_corpus_identifier() -> None:
    specs = build_corpus._source_specs()
    assert {spec.id for spec in specs} >= set(build_corpus.KNOWN_SOURCE_IDS.values())


_CCR_PAGE = """
<div class="co_docHeader"><div class="co_cites">14 CCR § 15062</div>
<h2 class="co_title"><div class="co_headtext">
<strong>§ 15062. Notice of Exemption.</strong></div></h2>
<div class="co_currentness"><a href="#x">Currentness</a></div></div>
<div class="co_contentBlock co_section"><div class="co_contentBlock co_body">
<div class="co_contentBlock co_subsection"><div class="co_paragraph">
<div class="co_paragraphText">
(a) When a public agency decides that a project is exempt from CEQA pursuant to
Section 15061, the agency may file a notice of exemption. Such a notice shall
include:</div></div></div>
<div class="co_contentBlock co_subsection"><div class="co_paragraph">
<div class="co_paragraphText">
(1) A brief description of the project, and the location of the project by street
address.</div></div></div>
</div></div>
<div class="co_headtext co_hAlign2">History</div>
<div class="co_contentBlock x_propagatedBlock"><div class="co_paragraph">
1. Amendment filed 1-1-2000 (Register 2000, No. 1).</div></div>
<div class="co_contentBlock co_includeCurrencyBlock"><div class="co_currency">
This database is current through 8/14/26 Register 2026, No. 33.</div></div>
"""


def test_ccr_parser_keeps_regulation_text_and_edition_and_drops_history() -> None:
    blocks, title, edition = build_corpus.ccr_blocks(_CCR_PAGE)
    assert title == "§ 15062. Notice of Exemption."
    assert edition == (
        "Barclays Official California Code of Regulations, current through 8/14/26 "
        "Register 2026, No. 33."
    )
    assert blocks[0] == ("heading", "§ 15062. Notice of Exemption.")
    assert [kind for kind, _ in blocks[1:]] == ["paragraph", "paragraph"]
    assert blocks[1][1].startswith("(a) When a public agency")
    assert not any("Amendment filed" in text for _, text in blocks)
    assert not any("current through" in text for _, text in blocks)
    assert build_corpus.ccr_document_id(title) == "ccr-14-15062"
    assert build_corpus.ccr_document_id("§ 15064.3. Transportation.") == "ccr-14-15064-3"
    assert build_corpus.ccr_document_id("Appendix E Notice of Exemption") == "ccr-14-appendix-e"
    assert build_corpus.ccr_section_number(title) == "15062"
    assert build_corpus.ccr_section_number("Appendix E") is None
    with pytest.raises(ValueError, match="cannot name"):
        build_corpus.ccr_document_id("Something else")


def test_ccr_documents_are_built_from_a_crawl_cache(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "000.html").write_text(_CCR_PAGE, encoding="utf-8")
    (cache / "001.html").write_text(
        "<div class='co_title'>§ 15999. Repealed.</div>", encoding="utf-8"
    )
    (cache / build_corpus.CCR_CACHE_INDEX).write_text(
        json.dumps(
            [
                {
                    "title": "§ 15062. Notice of Exemption.",
                    "url": "https://govt.westlaw.com/x",
                    "file": "000.html",
                },
                {
                    "title": "§ 15999. Repealed.",
                    "url": "https://govt.westlaw.com/y",
                    "file": "001.html",
                },
            ]
        ),
        encoding="utf-8",
    )

    def fetch(url: str, timeout: float) -> tuple[bytes, str]:
        return _HTML.encode("utf-8"), "text/html"

    out = tmp_path / "corpus"
    assert (
        build_corpus.main(["--corpus-dir", str(out), "--ccr-cache", str(cache)], fetch=fetch) == 0
    )
    corpus = Corpus.load(out)
    section = corpus.document_for_section("15062")
    assert section is not None and section.id == "ccr-14-15062"
    assert section.edition and "Register 2026, No. 33" in section.edition
    assert section.kind.value == "official"
    assert "NOE-001" in section.cited_by  # wired through the rule pack's guidelines field
    assert corpus.document_for_section("15999") is None  # no regulation text: skipped
