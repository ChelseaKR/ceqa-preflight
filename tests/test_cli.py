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


def test_check_excludes_filing_pilot_rules_unless_explicitly_requested(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (package / "notice.pdf").open("wb") as output:
        writer.write(output)
    manifest = tmp_path / "package.yaml"
    manifest.write_text(
        "filing_type: NOE\nproject:\n  title: Example Project\ndocuments:\n  - path: notice.pdf\n"
        "    category: Notice of Exemption\n    primary: true\n",
        encoding="utf-8",
    )
    base_arguments = [
        "check",
        str(package),
        "--filing-type",
        "NOE",
        "--manifest",
        str(manifest),
        "--format",
        "json",
    ]

    default = runner.invoke(app, base_arguments)
    experimental = runner.invoke(app, [*base_arguments, "--include-experimental"])

    assert default.exit_code == 0
    assert '"rule_id": "NOE-001"' not in default.stdout
    assert experimental.exit_code == 0
    assert '"rule_id": "NOE-001"' in experimental.stdout


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


def test_synth_creates_a_checkable_package_and_refuses_reuse(tmp_path: Path) -> None:
    directory = tmp_path / "synthetic"

    created = runner.invoke(
        app,
        ["synth", str(directory), "--filing-type", "NOE", "--defect", "scanned"],
    )
    reused = runner.invoke(app, ["synth", str(directory), "--filing-type", "NOE"])

    assert created.exit_code == 0
    assert "synthetic NOE package" in created.stdout
    assert (directory / "package.yaml").exists()
    assert reused.exit_code == 2
    assert "refusing to write" in reused.stderr


def test_check_supports_batch_sources_with_rollup_summary(tmp_path: Path) -> None:
    for name in ("one", "two"):
        package = tmp_path / name
        package.mkdir()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with (package / f"{name}_notice_document.pdf").open("wb") as output:
            writer.write(output)
    output_directory = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "check",
            str(tmp_path / "one"),
            str(tmp_path / "two"),
            "--filing-type",
            "NOE",
            "--format",
            "json",
            "--output",
            str(output_directory),
        ],
    )

    assert result.exit_code == 0
    assert "Batch summary" in result.stdout
    assert (output_directory / "report-01-one.json").exists()
    assert (output_directory / "report-02-two.json").exists()


def test_check_rejects_manifest_with_multiple_sources(tmp_path: Path) -> None:
    for name in ("one", "two"):
        (tmp_path / name).mkdir()

    result = runner.invoke(
        app,
        [
            "check",
            str(tmp_path / "one"),
            str(tmp_path / "two"),
            "--filing-type",
            "NOE",
            "--manifest",
            str(tmp_path / "package.yaml"),
        ],
    )

    assert result.exit_code == 2


def test_check_rule_selection_flags(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (package / "notice.pdf").open("wb") as output:
        writer.write(output)
    base = ["check", str(package), "--filing-type", "NOE", "--format", "json"]

    only = runner.invoke(app, [*base, "--rules", "core-001"])
    excluded = runner.invoke(app, [*base, "--exclude-rules", "CORE-001"])
    unknown = runner.invoke(app, [*base, "--rules", "NOPE-001"])
    empty = runner.invoke(app, [*base, "--rules", " , "])

    assert only.exit_code == 0
    assert '"rule_id": "CORE-001"' in only.stdout
    assert '"rule_id": "PDF-001"' not in only.stdout
    assert excluded.exit_code == 0
    assert '"rule_id": "CORE-001"' not in excluded.stdout
    assert unknown.exit_code == 2
    assert "unknown rule identifier" in unknown.stderr
    assert empty.exit_code == 2


def test_check_renders_a_printable_checklist(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (package / "notice.pdf").open("wb") as output:
        writer.write(output)

    result = runner.invoke(
        app,
        ["check", str(package), "--filing-type", "NOE", "--format", "checklist"],
    )

    assert result.exit_code == 0
    assert "CEQA Preflight pre-submission checklist" in result.stdout
    assert "Resolve before submission" in result.stdout


def test_init_from_package_prepopulates_existing_pdfs(tmp_path: Path) -> None:
    directory = tmp_path / "existing-package"
    directory.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (directory / "NOD_project_form.pdf").open("wb") as output:
        writer.write(output)

    populated = runner.invoke(
        app, ["init", str(directory), "--filing-type", "NOD", "--from-package"]
    )
    empty_directory = tmp_path / "empty-package"
    empty_directory.mkdir()
    empty = runner.invoke(
        app, ["init", str(empty_directory), "--filing-type", "NOD", "--from-package"]
    )

    assert populated.exit_code == 0
    manifest_text = (directory / "package.yaml").read_text(encoding="utf-8")
    assert "NOD_project_form.pdf" in manifest_text
    assert "REPLACE_WITH_FORM" not in manifest_text
    assert empty.exit_code == 2
    assert "no PDF files were found" in empty.stderr


def test_rules_list_supports_json_output() -> None:
    result = runner.invoke(app, ["rules", "list", "--format", "json"])
    invalid = runner.invoke(app, ["rules", "list", "--format", "yaml"])

    assert result.exit_code == 0
    assert '"id": "CORE-001"' in result.stdout
    assert invalid.exit_code == 2
