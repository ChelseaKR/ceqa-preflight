"""Command-line interface for CEQA Preflight."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from ceqa_preflight import __version__
from ceqa_preflight.ai.cli import ai_app
from ceqa_preflight.checker import check_package
from ceqa_preflight.diffing import DiffError, diff_reports, exit_code_for, load_report
from ceqa_preflight.i18n import LocaleError, resolve, set_locale
from ceqa_preflight.i18n import gettext as _
from ceqa_preflight.manifest import ManifestError, load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.observability import configure_logging, event
from ceqa_preflight.package_loader import PackageLoadError
from ceqa_preflight.pilot import PilotDataError, summarize_pilot, write_pilot_templates
from ceqa_preflight.reporting import (
    diff_counts,
    render_checklist,
    render_console,
    render_diff_console,
    render_diff_html,
    render_diff_json,
    render_html,
    render_json,
    render_junit,
    render_sarif,
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
app.add_typer(ai_app, name="ai")


def _show_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    context: typer.Context,
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
    locale: Annotated[
        str | None,
        typer.Option(
            "--locale",
            help=(
                "Language for report prose and messages, as a BCP 47 tag (en, es). "
                "Omitted means English. Nothing is inferred from the environment."
            ),
        ),
    ] = None,
) -> None:
    """Run local, advisory checks without uploading filing packages."""

    if log_format not in {"text", "json"}:
        raise typer.BadParameter("must be text or json", param_hint="--log-format")
    configure_logging(log_format)
    _select_locale(context, locale)


SPANISH_REVIEW_PENDING = (
    "Note: the Spanish catalog is a maintainer draft. A qualified Spanish-language CEQA "
    "reviewer has not yet approved its terminology or its advisory, non-legal framing "
    "(docs/I18N.md release gate, item 3). The English wording is authoritative."
)


def _select_locale(context: typer.Context, requested: str | None) -> None:
    """Put the requested language in force, and say plainly when it could not be met.

    A tag that is not well formed is the caller's typo and is reported as one. A tag that
    is well formed but has no catalog falls back to English and says so on stderr, because
    an advisory report silently arriving in the wrong language is a withheld fact, not a
    convenience.
    """

    try:
        catalog, unavailable = resolve(requested)
    except LocaleError as error:
        raise typer.BadParameter(str(error), param_hint="--locale") from error
    previous = set_locale(catalog)
    # A command that changed the language puts it back when it ends, so one process running
    # several commands cannot leak a locale from one into the next.
    context.call_on_close(lambda: set_locale(previous))
    if unavailable is not None:
        typer.echo(
            f"No catalog ships for {unavailable}; reporting in English instead.",
            err=True,
        )
    if catalog != "en":
        typer.echo(SPANISH_REVIEW_PENDING, err=True)


@app.command()
def version() -> None:
    """Show the installed CEQA Preflight version."""

    typer.echo(__version__)


_RENDERERS = {
    "console": render_console,
    "html": render_html,
    "json": render_json,
    "checklist": render_checklist,
    "sarif": render_sarif,
    "junit": render_junit,
}
_REPORT_SUFFIXES = {
    "console": "txt",
    "html": "html",
    "json": "json",
    "checklist": "txt",
    "sarif": "sarif",
    "junit": "xml",
}
_DIFF_RENDERERS = {
    "console": render_diff_console,
    "html": render_diff_html,
    "json": render_diff_json,
}
_DIFF_SUFFIXES = {"console": "txt", "html": "html", "json": "json"}


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
        typer.Option(
            "--format",
            help="Report format: console, json, html, checklist, sarif, or junit.",
        ),
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
        raise typer.BadParameter(
            "must be one of: " + ", ".join(sorted(_RENDERERS)), param_hint="--format"
        )
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
            typer.echo(_("Input error: {error}").format(error=error), err=True)
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
            typer.echo(_("Wrote advisory report to {path}").format(path=destination))
        counts = summarize_counts(report)
        batch_lines.append(
            _(
                "{source}: exit {exit_code}, {failure} failure(s), {warning} warning(s), "
                "{manual} manual-review item(s), {not_run} check(s) not run"
            ).format(
                source=source,
                exit_code=exit_code,
                failure=counts["failure"],
                warning=counts["warning"],
                manual=counts["manual"],
                not_run=counts["not_run"],
            )
        )
        worst_exit_code = max(worst_exit_code, exit_code)
        event(
            "check_completed",
            exit_code=exit_code,
            findings=len(report.findings),
            not_run=len(report.not_run),
        )
    if len(sources) > 1:
        typer.echo(_("Batch summary"))
        for line in batch_lines:
            typer.echo(f"  {line}")
    raise typer.Exit(code=worst_exit_code)


@app.command()
def diff(
    before: Annotated[
        Path,
        typer.Argument(
            exists=True, readable=True, help="The earlier JSON report written by `check`."
        ),
    ],
    after: Annotated[
        Path,
        typer.Argument(
            exists=True, readable=True, help="The later JSON report written by `check`."
        ),
    ],
    output_format: Annotated[
        str,
        typer.Option("--format", help="Comparison format: console, json, or html."),
    ] = "console",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional file to write the comparison to."),
    ] = None,
) -> None:
    """Name every finding that moved between two reports, and everything that did not.

    Exits 0 when nothing regressed, 1 when a failure is new or a finding became one, and
    2 when either input cannot be read as a report this tool knows how to compare. A
    comparison is never a determination: a finding that no longer appears has cleared a
    check, not been found compliant.
    """

    if output_format not in _DIFF_RENDERERS:
        raise typer.BadParameter("must be console, json, or html", param_hint="--format")
    event("diff_started", report_format=output_format)
    try:
        earlier = load_report(before.read_text(encoding="utf-8"))
        later = load_report(after.read_text(encoding="utf-8"))
    except DiffError as error:
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    except OSError as error:
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error

    comparison = diff_reports(earlier, later)
    rendered = _DIFF_RENDERERS[output_format](comparison)
    if output is None:
        typer.echo(rendered, nl=False)
    else:
        # `check --output` takes a directory, so a hand reaching for `diff --output` will
        # reach for one too. Writing `reports.txt` beside a `reports/` directory the person
        # meant to write into is a file in a place nobody asked for, and the success line
        # would name it as though it had been requested.
        if output.is_dir():
            output = output / f"comparison.{_DIFF_SUFFIXES[output_format]}"
        elif output.suffix == "":
            output = output.with_suffix(f".{_DIFF_SUFFIXES[output_format]}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(_("Wrote comparison to {path}").format(path=output))
    counts = diff_counts(comparison)
    event(
        "diff_completed",
        added=counts["added"],
        removed=counts["removed"],
        changed=counts["changed"],
        not_comparable=counts["not_comparable"],
        regressions=counts["regressions"],
    )
    raise typer.Exit(code=exit_code_for(comparison))


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
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(_("Created manifest template at {path}").format(path=destination))


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
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        _("Created a synthetic {filing_type} package with {count} file(s):").format(
            filing_type=filing_type.value, count=len(created)
        )
    )
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
    typer.echo(_("Unknown rule identifier: {rule_id}").format(rule_id=rule_id), err=True)
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
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(
        _("Created pilot templates: {review}, {baseline}").format(
            review=review_path.name, baseline=baseline_path.name
        )
    )


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
        typer.echo(_("Input error: {error}").format(error=error), err=True)
        raise typer.Exit(code=2) from error
    event("pilot_summarized", reviewed_findings=summary.reviewed_findings)
    if output_format == "json":
        typer.echo(summary.model_dump_json(indent=2))
        return
    typer.echo(
        "\n".join(
            (
                _("CEQA Preflight pilot summary"),
                _("Decision: {value}").format(value=summary.go_no_go),
                _("Reviewed findings: {value}").format(value=summary.reviewed_findings),
                _("Reviewed packages: {value}").format(value=summary.reviewed_packages),
                _("Actionable precision: {value}").format(
                    value=_format_rate(summary.actionable_precision)
                ),
                _("High-severity false-negative rate: {value}").format(
                    value=_format_rate(summary.high_severity_false_negative_rate)
                ),
                _("Median report time: {value}").format(
                    value=_format_seconds(summary.median_report_seconds)
                ),
                *summary.reasons,
            )
        )
    )


def _format_rate(value: float | None) -> str:
    return _("not measured") if value is None else f"{value:.1%}"


def _format_seconds(value: float | None) -> str:
    return _("not measured") if value is None else _("{value} seconds").format(value=f"{value:.1f}")
