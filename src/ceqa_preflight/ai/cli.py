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
from ceqa_preflight.ai.client import ModelClient, ModelError, build_client
from ceqa_preflight.ai.extraction import (
    DocumentExtraction,
    FieldStatus,
    PackageExtraction,
    extract_package,
)
from ceqa_preflight.ai.text import DocumentText, extract_document_text
from ceqa_preflight.models import FilingType, PackageManifest
from ceqa_preflight.observability import event
from ceqa_preflight.package_loader import PackageLoadError, open_package

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
        typer.echo(f"AI provider error: {error}", err=True)
        raise typer.Exit(code=2) from error


def _announce(client: ModelClient) -> None:
    typer.echo(
        messages.DATA_FLOW_NOTICE.format(provider=client.provider, model=client.model), err=True
    )


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
        detail = messages.NOT_ATTEMPTED.format(reason=document.reason_not_attempted)
    elif document.model_error:
        detail = messages.MODEL_ERROR.format(error=document.model_error)
    lines = [
        messages.DOCUMENT_LINE.format(
            path=document.path, kind=document.document_kind.value, detail=detail
        )
    ]
    for item in document.fields:
        if item.status is FieldStatus.FOUND:
            lines.append(
                messages.FIELD_FOUND.format(
                    name=item.name, value=item.value, page=item.page, quote=item.quote
                )
            )
        elif item.status is FieldStatus.UNVERIFIED:
            lines.append(messages.FIELD_UNVERIFIED.format(name=item.name, note=item.note))
        else:
            lines.append(messages.FIELD_UNKNOWN.format(name=item.name))
    return lines


def render_extraction_console(extraction: PackageExtraction) -> str:
    lines = [
        messages.EXTRACTION_HEADER,
        extraction.label,
        "",
        messages.EXTRACTION_SUMMARY.format(**extraction.counts.model_dump()),
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
        typer.echo(f"Input error: refusing to overwrite existing file: {destination}", err=True)
        raise typer.Exit(code=2)
    body = yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    header = messages.MANIFEST_COMMENT.format(
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
        raise typer.BadParameter("must be console or json", param_hint="--format")
    client = _client(provider, model)
    _announce(client)
    try:
        texts = _package_texts(source)
    except PackageLoadError as error:
        typer.echo(f"Input error: {error}", err=True)
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
        typer.echo(f"Wrote AI extraction draft to {output}")
    failed = any(document.model_error for document in extraction.documents)
    if write_manifest is not None:
        if failed:
            typer.echo(messages.DRAFT_MANIFEST_FAILED_CLOSED, err=True)
        elif extraction.draft_manifest is None:
            typer.echo(messages.DRAFT_MANIFEST_NONE, err=True)
        else:
            _write_draft_manifest(extraction, extraction.draft_manifest, write_manifest)
            typer.echo(messages.DRAFT_MANIFEST_WRITTEN.format(path=write_manifest))
            typer.echo(
                messages.NEXT_STEP.format(
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
