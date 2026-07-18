"""Command-line interface for CEQA Preflight."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ceqa_preflight import __version__
from ceqa_preflight.checker import check_package
from ceqa_preflight.manifest import ManifestError, load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.observability import configure_logging, event
from ceqa_preflight.package_loader import PackageLoadError
from ceqa_preflight.reporting import render_console, render_html, render_json
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.scaffold import write_manifest_template

app = typer.Typer(
    name="ceqa-preflight",
    help=(
        "Local, advisory preflight checks for CEQA Submit filing packages. "
        "This tool does not provide legal advice or determine CEQA compliance."
    ),
    no_args_is_help=True,
)
rules_app = typer.Typer(help="Inspect the built-in, source-cited rule catalog.")
app.add_typer(rules_app, name="rules")


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


@app.command()
def check(
    source: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Package directory or ZIP file.")
    ],
    filing_type: Annotated[
        FilingType,
        typer.Option("--filing-type", help="The intended NOD or NOE filing type."),
    ],
    manifest_path: Annotated[
        Path | None,
        typer.Option("--manifest", help="Optional local YAML or JSON package manifest."),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option("--format", help="Report format: console, json, or html."),
    ] = "console",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional directory for a generated report file."),
    ] = None,
) -> None:
    """Inspect a local package without uploading or changing its source files."""

    if output_format not in {"console", "json", "html"}:
        raise typer.BadParameter("must be console, json, or html", param_hint="--format")
    try:
        event("check_started", filing_type=filing_type.value, report_format=output_format)
        manifest = load_manifest(manifest_path) if manifest_path is not None else None
        report, exit_code = check_package(source, filing_type, manifest=manifest)
    except (ManifestError, PackageLoadError, ValueError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error

    rendered = {
        "console": render_console,
        "html": render_html,
        "json": render_json,
    }[output_format](report)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        output.mkdir(parents=True, exist_ok=True)
        suffix = {"console": "txt", "html": "html", "json": "json"}[output_format]
        destination = output / f"report.{suffix}"
        destination.write_text(rendered, encoding="utf-8")
        typer.echo(f"Wrote advisory report to {destination}")
    event("check_completed", exit_code=exit_code, findings=len(report.findings))
    raise typer.Exit(code=exit_code)


@app.command()
def init(
    directory: Annotated[
        Path, typer.Argument(help="Directory where package.yaml will be created.")
    ],
    filing_type: Annotated[
        FilingType,
        typer.Option("--filing-type", help="The intended NOD or NOE filing type."),
    ],
) -> None:
    """Create a non-overwriting, schema-valid local manifest template."""

    try:
        destination = write_manifest_template(directory, filing_type)
    except (FileExistsError, ValueError) as error:
        typer.echo(f"Input error: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(f"Created manifest template at {destination}")


@rules_app.command("list")
def list_rules(
    filing_type: Annotated[
        FilingType | None,
        typer.Option("--filing-type", help="Optionally filter rules to one filing type."),
    ] = None,
) -> None:
    """List rule identifiers, lifecycle, and source titles."""

    for rule in default_catalog(filing_type).rules:
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
