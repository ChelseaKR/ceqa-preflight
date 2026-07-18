"""CLI smoke tests."""

from pathlib import Path

from pypdf import PdfWriter
from typer.testing import CliRunner

from ceqa_preflight import __version__
from ceqa_preflight.cli import app

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"{__version__}\n"


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout == f"{__version__}\n"


def test_help_discloses_advisory_scope() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "does not provide legal advice" in result.stdout


def test_check_writes_json_report(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    document = package / "notice.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with document.open("wb") as output:
        writer.write(output)
    output_directory = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "check",
            str(package),
            "--filing-type",
            "NOE",
            "--format",
            "json",
            "--output",
            str(output_directory),
        ],
    )

    assert result.exit_code == 0
    assert "Wrote advisory report" in result.stdout
    assert '"filing_type": "NOE"' in (output_directory / "report.json").read_text(encoding="utf-8")


def test_check_writes_html_report(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (package / "notice.pdf").open("wb") as output:
        writer.write(output)
    output_directory = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "check",
            str(package),
            "--filing-type",
            "NOE",
            "--format",
            "html",
            "--output",
            str(output_directory),
        ],
    )

    assert result.exit_code == 0
    assert '<html lang="en">' in (output_directory / "report.html").read_text(encoding="utf-8")


def test_rules_list_and_show_are_source_cited() -> None:
    listed = runner.invoke(app, ["rules", "list", "--filing-type", "NOE"])
    shown = runner.invoke(app, ["rules", "show", "noe-001"])
    missing = runner.invoke(app, ["rules", "show", "missing-001"])

    assert listed.exit_code == 0
    assert "NOE-001" in listed.stdout
    assert "NOD-001" not in listed.stdout
    assert shown.exit_code == 0
    assert '"url": "https://lci.ca.gov/sch/faq/"' in shown.stdout
    assert missing.exit_code == 2
    assert "Unknown rule identifier" in missing.stderr


def test_init_creates_a_non_overwriting_template(tmp_path: Path) -> None:
    directory = tmp_path / "new-package"

    created = runner.invoke(app, ["init", str(directory), "--filing-type", "NOD"])
    existing = runner.invoke(app, ["init", str(directory), "--filing-type", "NOD"])

    assert created.exit_code == 0
    assert "Created manifest template" in created.stdout
    assert "filing_type: NOD" in (directory / "package.yaml").read_text(encoding="utf-8")
    assert existing.exit_code == 2
    assert "refusing to overwrite" in existing.stderr


def test_pilot_commands_create_and_summarize_controlled_label_files(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pilot", "init", str(tmp_path)])
    reviews = tmp_path / "finding-review.csv"
    baseline = tmp_path / "manual-baseline.csv"
    reviews.write_text(
        "package_id,filing_type,rule_id,finding_status,disposition,severity,elapsed_seconds\n"
        "PKG_001,NOE,NOE-001,warning,true_positive,medium,60\n",
        encoding="utf-8",
    )
    baseline.write_text(
        "package_id,filing_type,severity,was_missed\nPKG_001,NOE,high,false\n",
        encoding="utf-8",
    )
    summary = runner.invoke(
        app,
        [
            "pilot",
            "summarize",
            "--reviews",
            str(reviews),
            "--baseline",
            str(baseline),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert summary.exit_code == 0
    assert '"go_no_go": "go"' in summary.stdout
