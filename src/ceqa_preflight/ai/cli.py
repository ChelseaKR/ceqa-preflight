"""The ``ai`` command group (ADR 0002).

These commands are the only place CEQA Preflight talks to a model provider. They are never
invoked by ``check``. The provider SDK is imported only when a command runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
import yaml

from ceqa_preflight.ai import messages
from ceqa_preflight.ai.ask import Answer, ask, findings_summary
from ceqa_preflight.ai.client import ModelClient, ModelError, build_client
from ceqa_preflight.ai.corpus import Corpus, CorpusError
from ceqa_preflight.ai.explain import (
    ExplainMode,
    FindingExplanation,
    ReportExplanations,
    explain_report,
)
from ceqa_preflight.ai.extraction import (
    DocumentExtraction,
    FieldStatus,
    PackageExtraction,
    extract_package,
)
from ceqa_preflight.ai.grounding import Claim, SourceSummary
from ceqa_preflight.ai.guard import classify_question
from ceqa_preflight.ai.text import DocumentText, extract_document_text
from ceqa_preflight.i18n import _
from ceqa_preflight.models import FilingType, InspectionReport, PackageManifest
from ceqa_preflight.observability import event
from ceqa_preflight.package_loader import PackageLoadError, open_package
from ceqa_preflight.rule_registry import default_catalog

ai_app = typer.Typer(
    help=(
        "Opt-in, model-backed drafting and explanation (ADR 0002). These commands send "
        "document text or report findings to a model provider. They never produce a "
        "finding and never assess legal sufficiency."
    ),
    no_args_is_help=True,
)

ProviderOption = Annotated[
    str | None,
    typer.Option("--provider", help="Model provider: anthropic (default) or bedrock."),
]
ModelOption = Annotated[
    str | None,
    typer.Option("--model", help="Model identifier; defaults to the provider's Sonnet 5."),
]


def _client(provider: str | None, model: str | None) -> ModelClient:
    try:
        return build_client(provider, model)
    except ModelError as error:
        typer.echo(_("AI provider error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error


def _announce(client: ModelClient) -> None:
    typer.echo(messages.DATA_FLOW_NOTICE(provider=client.provider, model=client.model), err=True)


def _package_texts(source: Path) -> list[DocumentText]:
    with open_package(source) as root:
        pdfs = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.casefold() == ".pdf"
            ),
            key=lambda path: path.as_posix(),
        )
        texts: list[DocumentText] = []
        for path in pdfs:
            text = extract_document_text(path)
            texts.append(text.model_copy(update={"path": path.relative_to(root).as_posix()}))
        return texts


def _render_document(document: DocumentExtraction) -> list[str]:
    detail = ""
    if not document.attempted:
        detail = messages.NOT_ATTEMPTED(reason=document.reason_not_attempted)
    elif document.model_error:
        detail = messages.MODEL_ERROR(error=document.model_error)
    lines = [
        messages.DOCUMENT_LINE(path=document.path, kind=document.document_kind.value, detail=detail)
    ]
    for item in document.fields:
        if item.status is FieldStatus.FOUND:
            lines.append(
                messages.FIELD_FOUND(
                    name=item.name, value=item.value, page=item.page, quote=item.quote
                )
            )
        elif item.status is FieldStatus.UNVERIFIED:
            lines.append(messages.FIELD_UNVERIFIED(name=item.name, note=item.note))
        else:
            lines.append(messages.FIELD_UNKNOWN(name=item.name))
    return lines


def render_extraction_console(extraction: PackageExtraction) -> str:
    lines = [
        messages.EXTRACTION_HEADER(),
        extraction.label,
        "",
        messages.EXTRACTION_SUMMARY(**extraction.counts.model_dump()),
        "",
    ]
    for document in extraction.documents:
        lines.extend(_render_document(document))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_draft_manifest(
    extraction: PackageExtraction, manifest: PackageManifest, destination: Path
) -> None:
    if destination.exists():
        typer.echo(
            _("Input error: refusing to overwrite existing file: {destination}").format(
                destination=destination
            ),
            err=True,
        )
        raise typer.Exit(code=2)
    body = yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    header = messages.MANIFEST_COMMENT(
        provider=extraction.provenance.provider,
        model=extraction.provenance.model,
        prompt_version=extraction.provenance.prompt_version,
        generated_at=extraction.provenance.generated_at.isoformat(timespec="seconds"),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(header + body, encoding="utf-8")


@ai_app.command("extract")
def extract(
    source: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="A package directory or ZIP.")
    ],
    filing_type: Annotated[
        FilingType, typer.Option("--filing-type", help="The intended NOD or NOE filing type.")
    ],
    provider: ProviderOption = None,
    model: ModelOption = None,
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: console or json.")
    ] = "console",
    output: Annotated[
        Path | None, typer.Option("--output", help="Optional file for the extraction record.")
    ] = None,
    write_manifest: Annotated[
        Path | None,
        typer.Option(
            "--write-manifest",
            help="Write the DRAFT manifest here (never overwrites). Review it before use.",
        ),
    ] = None,
) -> None:
    """Draft manifest fields from the package's own text; every value carries a verified quote.

    The draft is for a person to review. Only `check --manifest` on the reviewed manifest
    produces findings, and this command never assesses sufficiency.
    """

    if output_format not in {"console", "json"}:
        raise typer.BadParameter(_("must be console or json"), param_hint="--format")
    client = _client(provider, model)
    _announce(client)
    try:
        texts = _package_texts(source)
    except PackageLoadError as error:
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    event("ai_extract_started", provider=client.provider, documents=len(texts))
    extraction = extract_package(client, filing_type, texts)
    rendered = (
        extraction.model_dump_json(indent=2) + "\n"
        if output_format == "json"
        else render_extraction_console(extraction)
    )
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(_("Wrote AI extraction draft to {output}").format(output=output))
    failed = any(document.model_error for document in extraction.documents)
    if write_manifest is not None:
        if failed:
            typer.echo(messages.DRAFT_MANIFEST_FAILED_CLOSED(), err=True)
        elif extraction.draft_manifest is None:
            typer.echo(messages.DRAFT_MANIFEST_NONE(), err=True)
        else:
            _write_draft_manifest(extraction, extraction.draft_manifest, write_manifest)
            typer.echo(messages.DRAFT_MANIFEST_WRITTEN(path=write_manifest))
            typer.echo(
                messages.NEXT_STEP(
                    package=source, filing_type=filing_type.value, manifest=write_manifest
                )
            )
    event(
        "ai_extract_completed",
        found=extraction.counts.found,
        unknown=extraction.counts.unknown,
        unverified=extraction.counts.unverified,
    )
    raise typer.Exit(code=2 if failed else 0)


def _load_report(path: Path) -> InspectionReport:
    try:
        return InspectionReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        typer.echo(
            _("Input error: could not load report {path}: {error}").format(path=path, error=error),
            err=True,
        )
        raise typer.Exit(code=2) from error


def _load_corpus() -> Corpus:
    try:
        return Corpus.load()
    except CorpusError as error:
        typer.echo(_("Corpus error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error


def _render_claims(claims: list[Claim]) -> list[str]:
    lines: list[str] = []
    for index, claim in enumerate(claims, start=1):
        lines.append(messages.CLAIM_LINE(index=index, text=claim.text))
        lines.extend(
            messages.CITATION_LINE(passage_id=citation.passage_id, quote=citation.quote)
            for citation in claim.citations
        )
    return lines


def _render_sources(sources: list[SourceSummary]) -> list[str]:
    """One line per cited document, naming the headings of the passages it quoted."""

    by_url: dict[str, tuple[SourceSummary, list[str]]] = {}
    for source in sources:
        entry = by_url.setdefault(source.url, (source, []))
        if source.heading and source.heading not in entry[1]:
            entry[1].append(source.heading)
    return [
        messages.SOURCE_LINE(
            title=source.title,
            kind=source.kind.value,
            url=source.url,
            headings=f" — {'; '.join(headings)}" if headings else "",
        )
        for source, headings in by_url.values()
    ]


def _render_item(item: FindingExplanation) -> list[str]:
    location = f" ({item.document})" if item.document else ""
    lines = [
        messages.FINDING_HEADER(
            rule_id=item.rule_id, status=item.status.value, title=item.title, location=location
        ),
        messages.FINDING_MESSAGE(message=item.message),
    ]
    lines.extend(_render_claims(item.claims))
    lines.extend(_render_sources(item.sources))
    if item.withheld:
        reasons = "; ".join(sorted({withheld.reason for withheld in item.withheld}))
        lines.append(messages.WITHHELD_LINE(count=len(item.withheld), reasons=reasons))
    if item.note:
        lines.append(messages.NOTE_LINE(note=item.note))
    if item.model_error:
        lines.append(messages.MODEL_ERROR_LINE(error=item.model_error))
    return lines


def render_explanations_console(explanations: ReportExplanations) -> str:
    lines = [
        messages.EXPLANATION_HEADER(explanations.mode.value),
        explanations.label,
        "",
        messages.EXPLANATION_SUMMARY(**explanations.counts.model_dump()),
        "",
    ]
    if not explanations.items:
        lines.append(messages.EXPLANATION_NONE())
    for item in explanations.items:
        lines.extend(_render_item(item))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _emit(rendered: str, output: Path | None, what: str) -> None:
    if output is None:
        typer.echo(rendered, nl=False)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(_("Wrote {what} to {output}").format(what=what, output=output))


def _run_explain(
    report_path: Path,
    mode: ExplainMode,
    provider: str | None,
    model: str | None,
    rules: str | None,
    output_format: str,
    output: Path | None,
) -> None:
    if output_format not in {"console", "json"}:
        raise typer.BadParameter(_("must be console or json"), param_hint="--format")
    report = _load_report(report_path)
    corpus = _load_corpus()
    client = _client(provider, model)
    _announce(client)
    rule_ids = _parse_rule_ids(rules)
    event("ai_explain_started", mode=mode.value, provider=client.provider)
    explanations = explain_report(
        client, corpus, report, default_catalog(), mode=mode, rule_ids=rule_ids
    )
    rendered = (
        explanations.model_dump_json(indent=2) + "\n"
        if output_format == "json"
        else render_explanations_console(explanations)
    )
    _emit(rendered, output, f"AI {mode.value.replace('_', ' ')} output")
    event("ai_explain_completed", **explanations.counts.model_dump())
    raise typer.Exit(code=2 if explanations.counts.model_errors else 0)


def _parse_rule_ids(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    identifiers = {token.strip().upper() for token in raw.split(",") if token.strip()}
    if not identifiers:
        raise typer.BadParameter(_("expected a comma-separated list of rule identifiers"))
    return identifiers


ReportArgument = Annotated[
    Path,
    typer.Argument(exists=True, readable=True, help="A JSON report written by `check`."),
]
RulesOption = Annotated[
    str | None, typer.Option("--rules", help="Limit to these comma-separated rule identifiers.")
]
FormatOption = Annotated[str, typer.Option("--format", help="Output format: console or json.")]
OutputOption = Annotated[Path | None, typer.Option("--output", help="Optional output file.")]


@ai_app.command("explain")
def explain(
    report_path: ReportArgument,
    provider: ProviderOption = None,
    model: ModelOption = None,
    rules: RulesOption = None,
    output_format: FormatOption = "console",
    output: OutputOption = None,
) -> None:
    """Explain each non-passing finding in plain language, quoting the official source it cites.

    Every claim carries a verbatim quote from the committed corpus, verified before display;
    claims that do not verify are withheld and counted. Nothing here is a finding.
    """

    _run_explain(report_path, ExplainMode.EXPLAIN, provider, model, rules, output_format, output)


@ai_app.command("draft-fix")
def draft_fix(
    report_path: ReportArgument,
    provider: ProviderOption = None,
    model: ModelOption = None,
    rules: RulesOption = None,
    output_format: FormatOption = "console",
    output: OutputOption = None,
) -> None:
    """Draft concrete correction steps for each non-passing finding, grounded in the corpus.

    Drafts are AI-generated suggestions for a person to review; they promise no outcome.
    """

    _run_explain(report_path, ExplainMode.DRAFT_FIX, provider, model, rules, output_format, output)


def render_answer_console(answer: Answer, report: InspectionReport) -> str:
    lines = [
        messages.ASK_HEADER(),
        answer.label,
        "",
        messages.ASK_QUESTION(question=answer.question),
        "",
    ]
    if answer.refused:
        found = findings_summary(report)
        findings_text = "\n".join(f"  {line}" for line in found) or messages.REFUSAL_NO_FINDINGS()
        lines.append(messages.REFUSAL(category=answer.refusal_category, findings=findings_text))
        return "\n".join(lines) + "\n"
    if answer.model_error:
        lines.append(messages.MODEL_ERROR_LINE(error=answer.model_error))
        return "\n".join(lines) + "\n"
    lines.extend(_render_claims(answer.claims) or [messages.ASK_NOTHING()])
    lines.extend(_render_sources(answer.sources))
    if answer.withheld:
        reasons = "; ".join(sorted({withheld.reason for withheld in answer.withheld}))
        lines.append(messages.WITHHELD_LINE(count=len(answer.withheld), reasons=reasons))
    return "\n".join(lines) + "\n"


@ai_app.command("ask")
def ask_command(
    report_path: ReportArgument,
    question: Annotated[str, typer.Argument(help="A question about the report's findings.")],
    provider: ProviderOption = None,
    model: ModelOption = None,
    output_format: FormatOption = "console",
    output: OutputOption = None,
) -> None:
    """Answer a question about the technical findings; refuse legal-sufficiency questions.

    Any form of "is this sufficient / will it be accepted / is the exemption valid / did
    the agency comply" is refused before the model runs, and again after it.
    """

    if output_format not in {"console", "json"}:
        raise typer.BadParameter(_("must be console or json"), param_hint="--format")
    if not question.strip():
        raise typer.BadParameter(_("question must not be empty"), param_hint="QUESTION")
    report = _load_report(report_path)
    corpus = _load_corpus()
    client = _client(provider, model)
    verdict = classify_question(question)
    if not verdict.refused:
        _announce(client)  # a refused question is never sent anywhere
    answer = ask(client, corpus, report, default_catalog(), question)
    event("ai_ask_completed", refused=answer.refused, claims=len(answer.claims))
    rendered = (
        answer.model_dump_json(indent=2) + "\n"
        if output_format == "json"
        else render_answer_console(answer, report)
    )
    _emit(rendered, output, "AI answer")
    raise typer.Exit(code=2 if answer.model_error else 0)
