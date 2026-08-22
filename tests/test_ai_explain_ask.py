"""Tests for explanations, correction drafts, and guarded questions over a real report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ceqa_preflight.ai.ask import MODEL_REFUSAL_CATEGORY, ask, findings_summary
from ceqa_preflight.ai.client import ScriptedClient
from ceqa_preflight.ai.corpus import Corpus
from ceqa_preflight.ai.explain import (
    ExplainMode,
    explain_report,
    findings_to_explain,
)
from ceqa_preflight.checker import check_package
from ceqa_preflight.cli import app
from ceqa_preflight.models import FilingType, InspectionReport
from ceqa_preflight.reporting import render_json
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return Corpus.load()


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> InspectionReport:
    package = tmp_path_factory.mktemp("pkg") / "synthetic"
    write_synthetic_package(
        package, FilingType.NOE, [SyntheticDefect.SCANNED, SyntheticDefect.FILLABLE_FORM]
    )
    built, _ = check_package(package, FilingType.NOE)
    return built


@pytest.fixture
def report_path(tmp_path: Path, report: InspectionReport) -> Path:
    path = tmp_path / "report.json"
    path.write_text(render_json(report), encoding="utf-8")
    return path


def _claims_for(corpus: Corpus, document_id: str, index: int, text: str) -> str:
    passage = corpus.passages(document_id)[index]
    return json.dumps(
        {
            "claims": [
                {
                    "text": text,
                    "citations": [{"passage_id": passage.id, "quote": passage.text[:50]}],
                },
                {"text": "Your filing is legally sufficient.", "citations": []},
            ]
        }
    )


def test_findings_to_explain_skips_passes_and_honors_rule_filter(report: InspectionReport) -> None:
    everything = findings_to_explain(report, None)
    assert everything and all(finding.status.value != "pass" for finding in everything)
    only = findings_to_explain(report, {"PDF-003"})
    assert [finding.rule_id for finding in only] == ["PDF-003"]


def test_explain_report_grounds_every_shown_claim_and_counts_withheld(
    corpus: Corpus, report: InspectionReport
) -> None:
    targets = findings_to_explain(report, {"PDF-003", "PDF-007"})
    responses = [
        _claims_for(corpus, "lci-sch-common-mistakes-2025", 3, "The guidance says to run OCR."),
        _claims_for(corpus, "lci-sch-presubmission-checklist-2025", 5, "Flatten the form."),
    ]
    client = ScriptedClient(responses)

    result = explain_report(
        client,
        corpus,
        report,
        default_catalog(),
        mode=ExplainMode.EXPLAIN,
        rule_ids={"PDF-003", "PDF-007"},
        commit="abc1234",
    )

    assert result.counts.findings == len(targets) == 2
    assert result.counts.claims_shown == 2 and result.counts.claims_withheld == 2
    assert result.counts.model_errors == 0
    assert result.provenance.prompt_version == "explain-v1"
    for item in result.items:
        assert all(citation.verified for claim in item.claims for citation in claim.citations)
        assert item.sources and item.sources[0].kind.value == "official"
        assert item.passages_shown
        assert all(
            citation.passage_id in item.passages_shown
            for claim in item.claims
            for citation in claim.citations
        )
    assert "Finding\nRule: PDF-003" in client.calls[0]["user"]
    assert "Passages\n[lci-sch-common-mistakes-2025#" in client.calls[0]["user"]


def test_explain_notes_self_cited_rules_and_empty_results(corpus: Corpus, tmp_path: Path) -> None:
    package = tmp_path / "big"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.WEAK_FILENAME])
    (package / "x!.pdf").write_bytes(
        (package / "NOE.pdf").read_bytes() if (package / "NOE.pdf").exists() else b"%PDF-1.4\n"
    )
    built, _ = check_package(package, FilingType.NOE)
    assert any(finding.rule_id == "FILE-005" for finding in built.findings)

    draft = explain_report(
        ScriptedClient(['{"claims": []}']),
        corpus,
        built,
        default_catalog(),
        mode=ExplainMode.DRAFT_FIX,
        rule_ids={"FILE-005"},
    )

    item = draft.items[0]
    assert item.source_kind.value == "project_advisory"
    assert item.note and "self-cited" in item.note and "did not support" in item.note
    assert draft.provenance.prompt_version == "draft-fix-v1"


def test_explain_fails_closed_per_finding(corpus: Corpus, report: InspectionReport) -> None:
    result = explain_report(
        ScriptedClient(["garbage"]),
        corpus,
        report,
        default_catalog(),
        mode=ExplainMode.EXPLAIN,
        rule_ids={"PDF-003"},
    )
    assert result.counts.model_errors == 1 and result.items[0].claims == []
    assert result.items[0].model_error == "model output was not a JSON object"


def test_explain_skips_rules_the_catalog_does_not_know(
    corpus: Corpus, report: InspectionReport
) -> None:
    foreign = report.model_copy(
        update={
            "findings": [
                report.findings[0].model_copy(update={"rule_id": "ZZZ-999", "status": "warning"})
            ],
            "manual_review": [],
        }
    )
    result = explain_report(
        ScriptedClient([]), corpus, foreign, default_catalog(), mode=ExplainMode.EXPLAIN
    )
    assert result.counts.findings == 0


def test_ask_refuses_before_the_model_and_redirects(
    corpus: Corpus, report: InspectionReport
) -> None:
    client = ScriptedClient([])
    answer = ask(client, corpus, report, default_catalog(), "Is this filing legally sufficient?")
    assert answer.refused and answer.refusal_category == "legal sufficiency"
    assert client.calls == []  # never sent
    assert answer.claims == []
    assert findings_summary(report) and all(
        "[pass]" not in line for line in findings_summary(report)
    )


def test_ask_answers_allowed_questions_with_verified_claims(
    corpus: Corpus, report: InspectionReport
) -> None:
    passage = corpus.passages("lci-sch-common-mistakes-2025")[3]
    payload = json.dumps(
        {
            "refused": False,
            "claims": [
                {
                    "text": "The guidance says to run OCR.",
                    "citations": [{"passage_id": passage.id, "quote": passage.text[:40]}],
                },
                {
                    "text": "PDF-003 flagged a scanned file.",
                    "citations": [
                        {
                            "passage_id": "report",
                            "quote": "No searchable text was found on any sampled page",
                        }
                    ],
                },
                {
                    "text": "Invented.",
                    "citations": [{"passage_id": "report", "quote": "this is not in the report"}],
                },
                {
                    "text": "Your package complies with CEQA.",
                    "citations": [{"passage_id": passage.id, "quote": passage.text[:40]}],
                },
            ],
        }
    )
    client = ScriptedClient([payload])

    question = "What does the guidance say about non-text-searchable documents and OCR for PDF-003?"
    answer = ask(client, corpus, report, default_catalog(), question)

    assert not answer.refused
    assert [claim.text for claim in answer.claims] == [
        "The guidance says to run OCR.",
        "PDF-003 flagged a scanned file.",
    ]
    assert len(answer.withheld) == 2
    assert answer.sources[0].passage_id == passage.id
    assert "report" in answer.passages_shown
    assert "[report] (Findings in this report)" in client.calls[0]["user"]


def test_ask_honors_the_models_own_refusal_and_fails_closed(
    corpus: Corpus, report: InspectionReport
) -> None:
    refused = ask(
        ScriptedClient(['{"refused": true, "reason": "asks for sufficiency", "claims": []}']),
        corpus,
        report,
        default_catalog(),
        "Tell me about the warnings, please.",
        guard=False,
    )
    assert refused.refused and refused.refusal_category == MODEL_REFUSAL_CATEGORY
    assert refused.refusal_matched == "asks for sufficiency"

    broken = ask(ScriptedClient(["??"]), corpus, report, default_catalog(), "What is PDF-003?")
    assert broken.model_error and not broken.claims

    bypassed = ask(
        ScriptedClient(['{"claims": []}']),
        corpus,
        report,
        default_catalog(),
        "Is this legally sufficient?",
        guard=False,
    )
    assert not bypassed.refused and bypassed.claims == []


def test_ask_scopes_project_advisory_sources_to_questions_that_name_their_rule(
    corpus: Corpus, tmp_path: Path
) -> None:
    package = tmp_path / "adv"
    write_synthetic_package(package, FilingType.NOE, [])
    built, _ = check_package(package, FilingType.NOE)
    client = ScriptedClient(['{"claims": []}', '{"claims": []}'])

    ask(client, corpus, built, default_catalog(), "What does the guidance say about file names?")
    ask(client, corpus, built, default_catalog(), "Where does FILE-004's threshold come from?")

    assert "ceqa-preflight-source-review-addendum" not in client.calls[0]["user"]
    assert "ceqa-preflight-source-review-addendum" in client.calls[1]["user"]


def test_cli_explain_draft_fix_and_ask(
    report_path: Path, corpus: Corpus, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    passage = corpus.passages("lci-sch-common-mistakes-2025")[3]
    grounded = json.dumps(
        {
            "claims": [
                {
                    "text": "Run OCR on the scanned file.",
                    "citations": [{"passage_id": passage.id, "quote": passage.text[:40]}],
                }
            ]
        }
    )
    client = ScriptedClient(
        [grounded, grounded, grounded.replace('{"claims"', '{"refused": false, "claims"')]
    )
    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", lambda *a, **k: client)

    explained = runner.invoke(app, ["ai", "explain", str(report_path), "--rules", "PDF-003"])
    assert explained.exit_code == 0, explained.output
    assert "CEQA Preflight AI explanations" in explained.output
    assert "1. Run OCR on the scanned file." in explained.output
    assert f"[{passage.id}]" in explained.output
    assert "Source: LCI CEQA Submit common mistakes (official)" in explained.output

    out = tmp_path / "fix.json"
    drafted = runner.invoke(
        app,
        [
            "ai",
            "draft-fix",
            str(report_path),
            "--rules",
            "PDF-003",
            "--format",
            "json",
            "--output",
            str(out),
        ],
    )
    assert drafted.exit_code == 0, drafted.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert (
        payload["mode"] == "draft_fix" and payload["provenance"]["prompt_version"] == "draft-fix-v1"
    )

    asked = runner.invoke(
        app,
        [
            "ai",
            "ask",
            str(report_path),
            "What does the guidance say about non-text-searchable documents and OCR for PDF-003?",
        ],
    )
    assert asked.exit_code == 0, asked.output
    assert "Run OCR on the scanned file." in asked.output

    refused = runner.invoke(app, ["ai", "ask", str(report_path), "Will this be accepted?"])
    assert refused.exit_code == 0, refused.output
    assert "does not determine legal sufficiency" in refused.output
    assert "acceptance prediction" in refused.output
    assert "PDF-003 [warning]" in refused.output
    assert "sends document text" not in refused.output  # nothing was sent
    assert len(client.calls) == 3


def test_cli_explain_and_ask_input_errors(
    report_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", lambda *a, **k: ScriptedClient([]))
    assert runner.invoke(app, ["ai", "explain", str(report_path), "--format", "xml"]).exit_code == 2
    assert (
        runner.invoke(app, ["ai", "ask", str(report_path), "q", "--format", "xml"]).exit_code == 2
    )
    assert runner.invoke(app, ["ai", "ask", str(report_path), "   "]).exit_code == 2
    assert runner.invoke(app, ["ai", "explain", str(report_path), "--rules", " , "]).exit_code == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    broken = runner.invoke(app, ["ai", "explain", str(bad)])
    assert broken.exit_code == 2 and "could not load report" in broken.output

    failed = runner.invoke(app, ["ai", "explain", str(report_path), "--rules", "PDF-003"])
    assert failed.exit_code == 2 and "Model error" in failed.output
    empty = runner.invoke(app, ["ai", "explain", str(report_path), "--rules", "CORE-001"])
    assert empty.exit_code == 0 and "No failure, warning, or manual-review finding" in empty.output

    monkeypatch.setattr(
        "ceqa_preflight.ai.cli.Corpus.load",
        lambda *a, **k: (_ for _ in ()).throw(
            __import__("ceqa_preflight.ai.corpus", fromlist=["CorpusError"]).CorpusError(
                "bad corpus"
            )
        ),
    )
    assert (
        "Corpus error"
        in runner.invoke(app, ["ai", "ask", str(report_path), "What is PDF-003?"]).output
    )
