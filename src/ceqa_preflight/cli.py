"""Command-line interface for CEQA Preflight."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ceqa_preflight import __version__
from ceqa_preflight.checker import check_package
from ceqa_preflight.manifest import ManifestError, load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.observability import configure_logging, event
from ceqa_preflight.package_loader import PackageLoadError
from ceqa_preflight.pilot import PilotDataError, summarize_pilot, write_pilot_templates
from ceqa_preflight.reporting import (
    render_checklist,
    render_console,
    render_html,
    render_json,
    summarize_counts,
)
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.scaffold import write_manifest_template
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

app = typer.Typer(
    name="ceqa-preflight",
    help=(
        "Local, advisory preflight checks for CEQA Submit filing packages. "
        "This tool does not provide legal advice or determine CEQA compliance."
    ),
    no_args_is_help=True,
)
rules_app = typer.Typer(help="Inspect the built-in, source-cited rule catalog.")
pilot_app = typer.Typer(help="Create and summarize privacy-preserving pilot evidence files.")
app.add_typer(rules_app, name="rules")
app.add_typer(pilot_app, name="pilot")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_show_version,
            is_eager=True,
            help="Show the installed CEQA Preflight version and exit.",
        ),
    ] = False,
    log_format: Annotated[
        str,
        typer.Option("--log-format", help="Operational logs: text (off) or json (stderr)."),
    ] = "text",
) -> None:
    """Run local, advisory checks without uploading filing packages."""

    if log_format not in {"text", "json"}:
        raise typer.BadParameter("must be text or json", param_hint="--log-format")
    configure_logging(log_format)


@app.command()
def version() -> None:
    """Show the installed CEQA Preflight version."""

    typer.echo(__version__)


_RENDERERS = {
    "console": render_console,
    "html": render_html,
    "json": render_json,
    "checklist": render_checklist,
}
_REPORT_SUFFIXES = {"console": "txt", "html": "html", "json": "json", "checklist": "txt"}


def _parse_rule_ids(raw: str | None) -> set[str] | None:
    if raw is None:
        return None
    identifiers = {token.strip().upper() for token in raw.split(",") if token.strip()}
    if not identifiers:
        raise typer.BadParameter("expected a comma-separated list of rule identifiers")
    return identifiers


def _report_stem(source: Path, index: int, total: int) -> str:
    if total == 1:
        return "report"
    safe = "".join(
        character if character.isalnum() or character in "-_" else "-" for character in source.stem
    ).strip("-")
    return f"report-{index + 1:02d}-{safe}" if safe else f"report-{index + 1:02d}"


@app.command()
def check(
    sources: Annotated[
        list[Path],
        typer.Argument(
            exists=True, readable=True, help="One or more package directories or ZIP files."
        ),
    ],
    filing_type: Annotated[
        FilingType,
        typer.Option("--filing-type", help="The intended NOD or NOE filing type."),
    ],
    manifest_path: Annotated[
        Path | None,
        typer.Option(
            "--manifest",
            help="Optional local YAML or JSON package manifest (single package only).",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Report format: console, json, html, or checklist."),
    ] = "console",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional directory for generated report files."),
    ] = None,
    include_experimental: Annotated[
        bool,
        typer.Option(
            "--include-experimental",
            help="Include filing-specific pilot rules; they are advisory and not release-ready.",
        ),
    ] = False,
    rules: Annotated[
        str | None,
        typer.Option("--rules", help="Run only these comma-separated rule identifiers."),
    ] = None,
    exclude_rules: Annotated[
        str | None,
        typer.Option("--exclude-rules", help="Skip these comma-separated rule identifiers."),
    ] = None,
) -> None:
    """Inspect local packages without uploading or changing their source files."""

    if output_format not in _RENDERERS:
        raise typer.BadParameter("must be console, json, html, or checklist", param_hint="--format")
    if manifest_path is not None and len(sources) > 1:
        raise typer.BadParameter("a manifest applies to a single package", param_hint="--manifest")
    rule_ids = _parse_rule_ids(rules)
    exclude_rule_ids = _parse_rule_ids(exclude_rules)

    worst_exit_code = 0
    batch_lines: list[str] = []
    for index, source in enumerate(sources):
        try:
            event("check_started", filing_type=filing_type.value, report_format=output_format)
            manifest = load_manifest(manifest_path) if manifest_path is not None else None
            report, exit_code = check_package(
                source,
                filing_type,
                manifest=manifest,
                include_experimental=include_experimental,
                rule_ids=rule_ids,
                exclude_rule_ids=exclude_rule_ids,
            )
        except (ManifestError, PackageLoadError, ValueError) as error:
            typer.echo(f"Input error: {error}", err=True)
            raise typer.Exit(code=2) from error

        rendered = _RENDERERS[output_format](report)
        if output is None:
            if len(sources) > 1:
                typer.echo(f"== Package: {source}")
            typer.echo(rendered, nl=False)
        else:
            output.mkdir(parents=True, exist_ok=True)
            stem = _report_stem(source, index, len(sources))
            destination = output / f"{stem}.{_REPORT_SUFFIXES[output_format]}"
            destination.write_text(rendered, encoding="utf-8")
            typer.echo(f"Wrote advisory report to {destination}")
        counts = summarize_counts(report)
        batch_lines.append(
            f"{source}: exit {exit_code}, {counts['failure']} failure(s), "
            f"{counts['warning']} warning(s), {counts['manual']} manual-review item(s), "
            f"{counts['not_run']} check(s) not run"
        )
        worst_exit_code = max(worst_exit_code, exit_code)
        event(
            "check_completed",
            exit_code=exit_code,
            findings=len(report.findings),
            not_run=len(report.not_run),
        )
    if len(sources) > 1:
        typer.echo("Batch summary")
        for line in batch_lines:
            typer.echo(f"  {line}")
    raise typer.Exit(code=worst_exit_code)


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Directory where package.yaml will be created.")
    ],
    filing_type: Annotated[
        FilingType,
        typer.Option("--filing-type", help="The intended NOD or NOE filing type."),
    ],
    from_package: Annotated[
        bool,
        typer.Option(
            "--from-package",
            help="Prepopulate document paths from PDFs already in the directory.",
        ),
    ] = False,
) -> None:
    """Create a non-overwriting, schema-valid local manifest template."""

    try:
        destination = write_manifest_template(directory, filing_type, from_package=from_package)
    except (FileExistsError, ValueError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Created manifest template at {destination}")


@app.command()
def synth(
    directory: Annotated[
        Path, typer.Argument(help="Empty or new directory for the synthetic package.")
    ],
    filing_type: Annotated[
        FilingType,
        typer.Option("--filing-type", help="The intended NOD or NOE filing type."),
    ],
    defect: Annotated[
        list[SyntheticDefect] | None,
        typer.Option("--defect", help="Seed an objective, detectable defect; repeatable."),
    ] = None,
) -> None:
    """Create a plainly fictional synthetic package for demos, tests, and pilot calibration."""

    try:
        created = write_synthetic_package(directory, filing_type, list(defect or []))
    except (FileExistsError, ValueError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Created a synthetic {filing_type.value} package with {len(created)} file(s):")
    for path in created:
        typer.echo(f"  {path}")


@rules_app.command("list")
def list_rules(
    filing_type: Annotated[
        FilingType | None,
        typer.Option("--filing-type", help="Optionally filter rules to one filing type."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Listing format: console or json."),
    ] = "console",
) -> None:
    """List rule identifiers, lifecycle, and source titles."""

    if output_format not in {"console", "json"}:
        raise typer.BadParameter("must be console or json", param_hint="--format")
    catalog = default_catalog(filing_type)
    if output_format == "json":
        typer.echo(
            json.dumps(
                [rule.model_dump(mode="json") for rule in catalog.rules],
                indent=2,
                sort_keys=True,
            )
        )
        return
    for rule in catalog.rules:
        typer.echo(f"{rule.id}\t{rule.lifecycle}\t{rule.title}\t{rule.source.title}")


@rules_app.command("show")
def show_rule(
    rule_id: Annotated[str, typer.Argument(help="Rule identifier, for example NOE-001.")],
) -> None:
    """Show the full source-cited metadata for one built-in rule."""

    normalized_id = rule_id.upper()
    for rule in default_catalog().rules:
        if rule.id == normalized_id:
            typer.echo(rule.model_dump_json(indent=2))
            return
    typer.echo(f"Unknown rule identifier: {rule_id}", err=True)
    raise typer.Exit(code=2)


@pilot_app.command("init")
def init_pilot(
    directory: Annotated[
        Path, typer.Argument(help="Directory where controlled-label CSV templates will be created.")
    ],
) -> None:
    """Create non-overwriting, package-content-free pilot evidence templates."""

    try:
        review_path, baseline_path = write_pilot_templates(directory)
    except FileExistsError as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Created pilot templates: {review_path.name}, {baseline_path.name}")


@pilot_app.command("summarize")
def summarize_pilot_data(
    reviews: Annotated[
        Path,
        typer.Option(
            "--reviews", exists=True, readable=True, help="Controlled-label finding review CSV."
        ),
    ],
    baseline: Annotated[
        Path,
        typer.Option("--baseline", exists=True, readable=True, help="Manual baseline issue CSV."),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", help="Summary format: console or json."),
    ] = "console",
) -> None:
    """Summarize pilot metrics without reading filing packages or free-text notes."""

    if output_format not in {"console", "json"}:
        raise typer.BadParameter("must be console or json", param_hint="--format")
    try:
        summary = summarize_pilot(reviews, baseline)
    except PilotDataError as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error
    event("pilot_summarized", reviewed_findings=summary.reviewed_findings)
    if output_format == "json":
        typer.echo(summary.model_dump_json(indent=2))
        return
    typer.echo(
        "\n".join(
            (
                "CEQA Preflight pilot summary",
                f"Decision: {summary.go_no_go}",
                f"Reviewed findings: {summary.reviewed_findings}",
                f"Reviewed packages: {summary.reviewed_packages}",
                f"Actionable precision: {_format_rate(summary.actionable_precision)}",
                "High-severity false-negative rate: "
                f"{_format_rate(summary.high_severity_false_negative_rate)}",
                f"Median report time: {_format_seconds(summary.median_report_seconds)}",
                *summary.reasons,
            )
        )
    )


def _format_rate(value: float | None) -> str:
    return "not measured" if value is None else f"{value:.1%}"


def _format_seconds(value: float | None) -> str:
    return "not measured" if value is None else f"{value:.1f} seconds"
