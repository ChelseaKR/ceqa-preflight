"""Tests for grounded generation: the verifier decides what reaches a reader."""

from __future__ import annotations

import json

import pytest

from ceqa_preflight.ai.client import ModelError, ScriptedClient
from ceqa_preflight.ai.corpus import Corpus, Passage
from ceqa_preflight.ai.grounding import (
    Citation,
    Claim,
    generate_grounded,
    parse_claims,
    passages_for_rule,
    render_passages,
    sources_for,
    verify_claims,
)
from ceqa_preflight.rule_registry import default_catalog


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return Corpus.load()


def _claims(*items: tuple[str, list[tuple[str, str]]]) -> str:
    return json.dumps(
        {
            "claims": [
                {"text": text, "citations": [{"passage_id": pid, "quote": q} for pid, q in cites]}
                for text, cites in items
            ]
        }
    )


def test_passages_for_rule_are_scoped_to_the_cited_document(corpus: Corpus) -> None:
    rules = {rule.id: rule for rule in default_catalog().rules}
    shown = passages_for_rule(corpus, rules["PDF-003"], "searchable text OCR")
    assert shown
    assert all(p.id.startswith("lci-sch-common-mistakes-2025#") for p in shown)
    filing = passages_for_rule(corpus, rules["NOE-M001"], "exemption findings")
    assert any(p.id.startswith("lci-sch-document-submission#") for p in filing)
    assert any(p.id.startswith("lci-sch-presubmission-checklist-2025#") for p in filing)
    rendered = render_passages(shown[:1])
    assert rendered.startswith(f"[{shown[0].id}]")


def test_passages_for_rule_is_empty_when_the_source_is_not_held(corpus: Corpus) -> None:
    rule = (
        default_catalog()
        .rules[0]
        .model_copy(
            update={
                "source": default_catalog()
                .rules[0]
                .source.model_copy(update={"url": "https://x.test/"})
            }
        )
    )
    assert passages_for_rule(corpus, rule, "anything") == []


def test_parse_claims_is_strict_about_shape() -> None:
    assert parse_claims('```json\n{"claims": []}\n```') == []
    parsed = parse_claims(_claims(("A sentence.", [("doc#p001", "quote")])))
    assert parsed == [
        Claim(text="A sentence.", citations=[Citation(passage_id="doc#p001", quote="quote")])
    ]
    tolerant = parse_claims(
        '{"claims": [{"text": "  "}, 5, {"text": "ok", "citations": [{"quote": "q"}, "x"]}]}'
    )
    assert tolerant == [Claim(text="ok")]
    with pytest.raises(ModelError, match="not a JSON object"):
        parse_claims("nope")
    with pytest.raises(ModelError, match="claims list"):
        parse_claims('{"answer": "x"}')


def test_verify_claims_keeps_only_fully_verified_non_determinations() -> None:
    shown = [
        Passage(id="g#p001", text="Documents are fully text-searchable (OCR-enabled)."),
        Passage(id="g#p002", text="Files are flattened and contain no fillable form fields."),
    ]
    claims = [
        Claim(
            text="Docs must be searchable.",
            citations=[Citation(passage_id="g#p001", quote="fully text-searchable")],
        ),
        Claim(
            text="Flatten forms.",
            citations=[
                Citation(passage_id="g#p002", quote="fillable form fields"),
                Citation(passage_id="g#p002", quote="not in passage"),
            ],
        ),
        Claim(text="Uncited sentence."),
        Claim(
            text="Cites something unseen.", citations=[Citation(passage_id="other#p009", quote="x")]
        ),
        Claim(
            text="Your filing is legally sufficient.",
            citations=[Citation(passage_id="g#p001", quote="fully text-searchable")],
        ),
    ]

    verified, withheld = verify_claims(shown, claims)

    assert [claim.text for claim in verified] == ["Docs must be searchable."]
    assert all(citation.verified for citation in verified[0].citations)
    reasons = [item.reason for item in withheld]
    assert "1 citation(s) did not verify against the corpus" in reasons
    assert "no citation" in reasons
    assert any(reason.startswith("determination language") for reason in reasons)
    assert sum(item.citation_count for item in withheld) == 4


def test_sources_for_lists_each_cited_passage_once_with_document_provenance(corpus: Corpus) -> None:
    pid = corpus.passages("lci-sch-common-mistakes-2025")[3].id
    claims = [
        Claim(
            text="a",
            citations=[Citation(passage_id=pid, quote="x"), Citation(passage_id=pid, quote="y")],
        ),
        Claim(text="b", citations=[Citation(passage_id="report", quote="z")]),
    ]
    sources = sources_for(corpus, claims)
    assert len(sources) == 1
    assert sources[0].url.startswith("https://lci.ca.gov/")
    assert sources[0].kind.value == "official"


def test_generate_grounded_fails_closed_on_model_errors(corpus: Corpus) -> None:
    shown = corpus.passages("lci-sch-common-mistakes-2025")[:2]
    verified, withheld, error = generate_grounded(
        ScriptedClient([]), corpus, system="s", user="u", shown=shown, max_tokens=10
    )
    assert (verified, withheld) == ([], []) and error
    verified, withheld, error = generate_grounded(
        ScriptedClient(["not json"]), corpus, system="s", user="u", shown=shown, max_tokens=10
    )
    assert error == "model output was not a JSON object"
    quote = shown[0].text[:40]
    verified, withheld, error = generate_grounded(
        ScriptedClient([_claims(("Fine.", [(shown[0].id, quote)]))]),
        corpus,
        system="s",
        user="u",
        shown=shown,
        max_tokens=10,
    )
    assert error is None and [c.text for c in verified] == ["Fine."] and withheld == []
