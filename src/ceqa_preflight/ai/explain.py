"""Plain-language explanations and correction drafts for findings (ADR 0002, role 3).

Both modes take an existing JSON report, retrieve passages from the corpus documents the
rule cites, and ask the model for claims that each quote a passage verbatim. The verifier
in ``grounding`` decides what is shown. Nothing here changes a finding; the report is read,
never written.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ceqa_preflight.ai.client import ModelClient
from ceqa_preflight.ai.corpus import Corpus
from ceqa_preflight.ai.grounding import (
    Claim,
    SourceSummary,
    WithheldClaim,
    generate_grounded,
    passages_for_rule,
    render_passages,
    sources_for,
)
from ceqa_preflight.ai.provenance import AI_GENERATED_LABEL, Provenance, provenance_for
from ceqa_preflight.models import (
    FilingType,
    Finding,
    FindingStatus,
    InspectionReport,
    SourceKind,
    StrictModel,
)
from ceqa_preflight.rule_catalog import RuleCatalog, RuleDefinition

MAX_OUTPUT_TOKENS = 3_000


class ExplainMode(StrEnum):
    EXPLAIN = "explain"
    DRAFT_FIX = "draft_fix"


PROMPT_VERSIONS = {ExplainMode.EXPLAIN: "explain-v1", ExplainMode.DRAFT_FIX: "draft-fix-v1"}

_COMMON_RULES = (
    "Rules you must follow:\n"
    "1. Use only the passages provided below. Do not use outside knowledge, and do not "
    "describe anything the passages do not say.\n"
    "2. Every claim must cite at least one passage by its identifier (the text in square "
    "brackets) and include a verbatim quote of 5 to 300 characters copied exactly from that "
    "passage. A claim without a verifying quote will be discarded.\n"
    "3. Never state, imply, or estimate whether the filing, package, notice, project, "
    "exemption, or agency is or is not sufficient, adequate, valid, compliant, correct, "
    "acceptable, defensible, or likely to be accepted. You explain what a technical finding "
    "means and what the cited guidance says; you never judge the filing.\n"
    "4. If a passage is marked as the project's own advisory reasoning rather than official "
    "guidance, say so plainly in the claim that relies on it.\n"
    "5. If the passages do not support a faithful answer, return an empty claims list.\n"
    "6. Output a single JSON object and nothing else: "
    '{"claims": [{"text": <one plain-language sentence or two>, '
    '"citations": [{"passage_id": <identifier>, "quote": <verbatim quote>}]}]}'
)

SYSTEM_PROMPTS = {
    ExplainMode.EXPLAIN: (
        "You explain one technical finding from a CEQA filing-package checker to a planner or "
        "clerk in plain language: what the check looked at, what it observed, and what the "
        "official guidance it cites says about that topic. Three to six short claims.\n\n"
        + _COMMON_RULES
    ),
    ExplainMode.DRAFT_FIX: (
        "You draft concrete, practical steps a planner or clerk can take to correct one "
        "technical finding in their own filing package before submitting it, grounded in "
        "the official guidance the check cites. Each claim is one numbered step, written as "
        "an instruction, three to six steps. Steps are suggestions to review, not "
        "requirements, and must not promise any outcome.\n\n" + _COMMON_RULES
    ),
}


class FindingExplanation(StrictModel):
    """One finding's grounded explanation (or correction draft) and everything withheld."""

    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    status: FindingStatus
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    document: str | None = None
    source_kind: SourceKind | None = None
    claims: list[Claim] = Field(default_factory=list)
    withheld: list[WithheldClaim] = Field(default_factory=list)
    sources: list[SourceSummary] = Field(default_factory=list)
    passages_shown: list[str] = Field(default_factory=list)
    note: str | None = None
    model_error: str | None = None


class ExplanationCounts(StrictModel):
    findings: int = 0
    claims_shown: int = 0
    claims_withheld: int = 0
    model_errors: int = 0


class ReportExplanations(StrictModel):
    """The AI-generated companion to a report. It is not part of the report."""

    explanations_schema_version: str = "1.0"
    label: str = AI_GENERATED_LABEL
    mode: ExplainMode
    filing_type: FilingType
    report_fingerprint: str = Field(min_length=1)
    items: list[FindingExplanation] = Field(default_factory=list)
    counts: ExplanationCounts = Field(default_factory=ExplanationCounts)
    provenance: Provenance


_PROJECT_ADVISORY_NOTE = (
    "This rule is self-cited: no official source states its threshold. The explanation is "
    "grounded in the project's own documented reasoning, not in official guidance."
)
_NO_CORPUS_NOTE = (
    "The source this rule cites is not in the committed corpus; nothing was generated."
)
_NOTHING_SUPPORTED_NOTE = "The cited guidance did not support any claim that passed verification."


def _user_prompt(finding: Finding, rule: RuleDefinition, rendered: str) -> str:
    kind_label = {
        SourceKind.OFFICIAL: "official State guidance",
        SourceKind.TECHNICAL_REFERENCE: "a general technical reference, not CEQA guidance",
        SourceKind.PROJECT_ADVISORY: "the project's own advisory reasoning, not official guidance",
    }[rule.source.kind]
    location = f"\nDocument: {finding.document}" if finding.document else ""
    return (
        f"Finding\nRule: {finding.rule_id} ({rule.title}), version {finding.rule_version}\n"
        f"Status: {finding.status.value}\nMessage: {finding.message}\n"
        f"Remediation from the checker: {finding.remediation}{location}\n"
        f"Cited source: {rule.source.title} ({kind_label})\n\n"
        f"Passages\n{rendered}"
    )


def explain_finding(
    client: ModelClient,
    corpus: Corpus,
    finding: Finding,
    rule: RuleDefinition,
    *,
    mode: ExplainMode,
) -> FindingExplanation:
    base = FindingExplanation(
        rule_id=finding.rule_id,
        rule_version=finding.rule_version,
        status=finding.status,
        title=rule.title,
        message=finding.message,
        document=finding.document,
        source_kind=rule.source.kind,
    )
    query = f"{rule.title} {finding.message} {finding.remediation}"
    shown = passages_for_rule(corpus, rule, query)
    if not shown:
        return base.model_copy(update={"note": _NO_CORPUS_NOTE})
    claims, withheld, error = generate_grounded(
        client,
        corpus,
        system=SYSTEM_PROMPTS[mode],
        user=_user_prompt(finding, rule, render_passages(shown)),
        shown=shown,
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    note = _PROJECT_ADVISORY_NOTE if rule.source.kind is SourceKind.PROJECT_ADVISORY else None
    if error is None and not claims:
        note = f"{note} {_NOTHING_SUPPORTED_NOTE}" if note else _NOTHING_SUPPORTED_NOTE
    return base.model_copy(
        update={
            "claims": claims,
            "withheld": withheld,
            "sources": sources_for(corpus, claims),
            "passages_shown": [passage.id for passage in shown],
            "note": note,
            "model_error": error,
        }
    )


def findings_to_explain(report: InspectionReport, rule_ids: set[str] | None) -> list[Finding]:
    """Every non-passing finding and manual-review item, optionally limited by rule id."""

    candidates = [
        finding
        for finding in [*report.findings, *report.manual_review]
        if finding.status is not FindingStatus.PASS
    ]
    if rule_ids is None:
        return candidates
    return [finding for finding in candidates if finding.rule_id in rule_ids]


def explain_report(
    client: ModelClient,
    corpus: Corpus,
    report: InspectionReport,
    catalog: RuleCatalog,
    *,
    mode: ExplainMode,
    rule_ids: set[str] | None = None,
    commit: str | None = None,
) -> ReportExplanations:
    rules = {rule.id: rule for rule in catalog.rules}
    items: list[FindingExplanation] = []
    for finding in findings_to_explain(report, rule_ids):
        rule = rules.get(finding.rule_id)
        if rule is None:
            continue  # a report from a newer catalog; nothing to ground it in
        items.append(explain_finding(client, corpus, finding, rule, mode=mode))
    counts = ExplanationCounts(
        findings=len(items),
        claims_shown=sum(len(item.claims) for item in items),
        claims_withheld=sum(len(item.withheld) for item in items),
        model_errors=sum(item.model_error is not None for item in items),
    )
    return ReportExplanations(
        mode=mode,
        filing_type=report.filing_type,
        report_fingerprint=report.input_fingerprint,
        items=items,
        counts=counts,
        provenance=provenance_for(client, PROMPT_VERSIONS[mode], commit=commit),
    )
