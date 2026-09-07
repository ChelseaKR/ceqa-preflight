"""Tests for the composite action, the pre-commit hook, and the counts they publish.

The action and the hook are YAML that CI cannot run from here, so what is testable is the
part that would rot: whether the flags the action passes still exist on the CLI, whether
the outputs it declares are the ones the summary module writes, and whether the counting
it publishes agrees with the console summary's counting rather than being a second
implementation of it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.main import get_command
from typer.testing import CliRunner

from ceqa_preflight.checker import check_package
from ceqa_preflight.ci_summary import (
    OUTPUT_KEYS,
    NoReportProduced,
    main,
    read_reports,
    summarize_reports,
)
from ceqa_preflight.cli import app
from ceqa_preflight.models import FilingType
from ceqa_preflight.precommit import MANIFEST_NAMES, PackageNotResolved, resolve_package
from ceqa_preflight.reporting import render_json, summarize_counts
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

_ROOT = Path(__file__).resolve().parents[1]
_ACTION = _ROOT / "action.yml"
_HOOKS = _ROOT / ".pre-commit-hooks.yaml"
_EXAMPLE_WORKFLOW = _ROOT / "examples" / "workflows" / "ceqa-preflight.yml"

runner = CliRunner()


def _action() -> dict[str, object]:
    return yaml.safe_load(_ACTION.read_text(encoding="utf-8"))


def _option_names(*path: str) -> set[str]:
    """The option strings a command really accepts, read off the command object.

    Not off `--help`. Rich wraps and colours that output at the terminal's width, so an
    assertion over it passes on a wide developer terminal and fails on an 80-column CI
    runner with `--filing-type` split across two lines -- a test measuring the runner
    rather than the code. It did exactly that on all three platforms before this.
    """

    command = get_command(app)
    for name in path:
        found = command.commands.get(name)  # type: ignore[attr-defined]
        assert found is not None, f"no `{name}` command on the CLI"
        command = found
    return {option for parameter in command.params for option in parameter.opts}


def _command_names() -> set[str]:
    return set(get_command(app).commands)  # type: ignore[attr-defined]


def test_the_action_declares_exactly_the_outputs_the_summary_module_writes() -> None:
    """The one pairing that silently rots: an output nothing sets reads empty, not as an error."""

    declared = set(_action()["outputs"])  # type: ignore[arg-type]

    assert declared == set(OUTPUT_KEYS)


def test_every_flag_the_action_passes_still_exists_on_the_cli() -> None:
    """A renamed option would make the action fail on a runner and nowhere else."""

    script = "\n".join(
        step["run"]
        for step in _action()["runs"]["steps"]
        if "run" in step  # type: ignore[index,call-overload]
    )
    check_options = _option_names("check")
    for flag in ("--filing-type", "--include-experimental", "--rules", "--format", "--output"):
        assert flag in script, f"the action no longer passes {flag}"
        assert flag in check_options, f"`check` no longer accepts {flag}"
    assert "--locale" in script
    assert "--locale" in _option_names(), "`--locale` is no longer a root option"


def test_the_action_pins_its_release_and_refuses_a_mismatched_wheel() -> None:
    """`version` has no default on purpose: the report's `tool_version` is evidence."""

    action = _action()
    version_input = action["inputs"]["version"]  # type: ignore[index]

    assert version_input["required"] is True
    assert "default" not in version_input
    install = next(
        step
        for step in action["runs"]["steps"]
        if step["name"].startswith("Install")  # type: ignore[index,union-attr]
    )
    assert "ceqa-preflight --version" in install["run"]
    assert "installed version" in install["run"], (
        "the install step no longer compares the tag with what it installed"
    )


def test_the_action_fails_the_job_on_the_tools_own_exit_code() -> None:
    """A gate that always exits 0 is the shape this whole project is written against."""

    steps = _action()["runs"]["steps"]  # type: ignore[index]
    final = steps[-1]  # type: ignore[index]

    assert 'exit "${CODE}"' in final["run"]
    assert final["env"]["CODE"] == "${{ steps.check.outputs.exit-code }}"


def test_the_hook_passes_filenames_and_matches_the_files_a_check_reads() -> None:
    hooks = yaml.safe_load(_HOOKS.read_text(encoding="utf-8"))

    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["entry"] == "ceqa-preflight pre-commit"
    assert hook["pass_filenames"] is True
    assert "pre-commit" in _command_names(), "the hook's entry command is not on the CLI"
    assert "--package" in _option_names("pre-commit")


def test_the_example_workflow_grants_the_permission_the_action_needs() -> None:
    """A composite action cannot widen its caller's token; the example has to grant it."""

    workflow = yaml.safe_load(_EXAMPLE_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["preflight"]

    assert job["permissions"]["security-events"] == "write"
    uses = [step.get("uses", "") for step in job["steps"]]
    assert any(entry.startswith("ChelseaKR/ceqa-preflight@") for entry in uses)


def _write_report(directory: Path, name: str, package: Path) -> None:
    report, _ = check_package(package, FilingType.NOE)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(render_json(report), encoding="utf-8")


def test_the_published_counts_are_the_consoles_counts_and_not_a_second_implementation(
    tmp_path: Path,
) -> None:
    """The reason `ci_summary` exists. Counting in shell would drift from this silently."""

    package = tmp_path / "package"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.SCANNED])
    reports = tmp_path / "reports"
    _write_report(reports, "report.json", package)
    report, _ = check_package(package, FilingType.NOE)
    expected = summarize_counts(report)

    published = summarize_reports(read_reports(reports))

    assert published == {
        "failures": expected["failure"],
        "warnings": expected["warning"],
        "not-run": expected["not_run"],
    }


def test_two_reports_are_summed_rather_than_the_last_one_winning(tmp_path: Path) -> None:
    package = tmp_path / "package"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.SCANNED])
    reports = tmp_path / "reports"
    _write_report(reports, "report-01.json", package)
    _write_report(reports, "report-02.json", package)
    single = summarize_counts(check_package(package, FilingType.NOE)[0])

    published = summarize_reports(read_reports(reports))

    assert published["warnings"] == single["warning"] * 2
    assert published["not-run"] == single["not_run"] * 2


def test_a_directory_with_no_report_is_refused_rather_than_counted_as_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The absence-as-a-value case. `failures=0` here would be a green job on no evidence."""

    empty = tmp_path / "reports"
    empty.mkdir()

    code = main([str(empty)])

    assert code == 2
    assert "no report produced" in capsys.readouterr().err
    with pytest.raises(NoReportProduced):
        read_reports(empty)


def test_a_report_that_will_not_parse_stops_the_count_rather_than_lowering_it(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "report.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(NoReportProduced, match="not readable as JSON"):
        read_reports(reports)


def test_main_appends_every_declared_output_to_the_file_it_is_given(tmp_path: Path) -> None:
    package = tmp_path / "package"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.SCANNED])
    reports = tmp_path / "reports"
    _write_report(reports, "report.json", package)
    destination = tmp_path / "github-output"

    code = main([str(reports), "--output-file", str(destination)])

    written = dict(
        line.split("=", 1) for line in destination.read_text(encoding="utf-8").splitlines()
    )
    assert code == 0
    assert sorted(written) == sorted(OUTPUT_KEYS)
    assert all(value.isdigit() for value in written.values())


def test_the_hook_resolves_the_package_that_holds_the_staged_files(tmp_path: Path) -> None:
    package = tmp_path / "filings" / "noe-2026"
    write_synthetic_package(package, FilingType.NOE, [])
    staged = sorted(package.glob("*.pdf"))
    assert staged, "the synthetic package wrote no PDF, so this fixture proves nothing"

    directory, manifest = resolve_package(staged, boundary=tmp_path)

    assert directory == package.resolve()
    assert manifest.name in MANIFEST_NAMES


def test_the_hook_refuses_when_no_manifest_identifies_a_package(tmp_path: Path) -> None:
    """The fallback that would turn the hook into a check that cannot fail."""

    loose = tmp_path / "docs"
    loose.mkdir()
    (loose / "notes.pdf").write_bytes(b"%PDF-1.7\n")

    with pytest.raises(PackageNotResolved, match="pass --package"):
        resolve_package([loose / "notes.pdf"], boundary=tmp_path)


def test_the_hook_refuses_a_directory_holding_two_manifests(tmp_path: Path) -> None:
    package = tmp_path / "package"
    write_synthetic_package(package, FilingType.NOE, [])
    (package / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PackageNotResolved, match="more than one manifest"):
        resolve_package(sorted(package.glob("*.pdf")), boundary=tmp_path)


def test_the_hook_refuses_a_staged_path_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(PackageNotResolved, match="does not exist"):
        resolve_package([tmp_path / "gone.pdf"], boundary=tmp_path)


def test_the_hook_refuses_an_empty_file_list(tmp_path: Path) -> None:
    with pytest.raises(PackageNotResolved, match="no files were passed"):
        resolve_package([], boundary=tmp_path)


def test_the_hook_command_checks_the_resolved_package(tmp_path: Path) -> None:
    package = tmp_path / "filings" / "noe-2026"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.SCANNED])
    staged = [str(path) for path in sorted(package.glob("*.pdf"))]

    result = runner.invoke(app, ["pre-commit", *staged, "--package", str(package)])

    assert result.exit_code in {0, 1}, result.output
    assert f"Checking {package}" in result.stdout
    assert "as NOE, per package.yaml" in result.stdout


def test_the_hook_command_exits_two_when_it_cannot_identify_a_package(tmp_path: Path) -> None:
    loose = tmp_path / "notes.pdf"
    loose.write_bytes(b"%PDF-1.7\n")

    result = runner.invoke(app, ["pre-commit", str(loose), "--package", str(tmp_path)])

    assert result.exit_code == 2
    assert "holds no package.yaml" in result.stderr


def test_the_hook_reads_the_filing_type_from_the_manifest_rather_than_defaulting(
    tmp_path: Path,
) -> None:
    """A default filing type would check an NOD package against the NOE rules and pass."""

    package = tmp_path / "nod"
    write_synthetic_package(package, FilingType.NOD, [])
    staged = [str(path) for path in sorted(package.glob("*.pdf"))]

    result = runner.invoke(app, ["pre-commit", *staged, "--package", str(package)])

    assert "as NOD, per package.yaml" in result.stdout
    manifest = yaml.safe_load((package / "package.yaml").read_text(encoding="utf-8"))
    assert manifest["filing_type"] == "NOD"


def test_the_reports_the_action_uploads_are_the_reports_it_counts(tmp_path: Path) -> None:
    """SARIF rule ids and the counted JSON must describe one run, not two."""

    package = tmp_path / "package"
    write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.SCANNED])
    reports = tmp_path / "reports"
    for output_format in ("json", "sarif"):
        result = runner.invoke(
            app,
            [
                "check",
                str(package),
                "--filing-type",
                "NOE",
                "--format",
                output_format,
                "--output",
                str(reports / output_format),
            ],
        )
        assert result.exit_code in {0, 1}, result.output

    report = json.loads((reports / "json" / "report.json").read_text(encoding="utf-8"))
    sarif = json.loads((reports / "sarif" / "report.sarif").read_text(encoding="utf-8"))

    scored_ids = {entry["rule_id"] for entry in report["findings"] + report["manual_review"]}
    sarif_ids = {result["ruleId"] for result in sarif["runs"][0]["results"]}
    assert sarif_ids == scored_ids, "the SARIF describes a different run from the JSON"
    assert scored_ids, "this package produced no scored rule, so the comparison is vacuous"
    notification_ids = {
        entry["associatedRule"]["id"] if "associatedRule" in entry else entry["descriptor"]["id"]
        for entry in sarif["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    }
    not_run_ids = {entry["rule_id"] for entry in report["not_run"]}
    assert notification_ids == not_run_ids
    assert not_run_ids, "no check was skipped here, so the notification check is vacuous"
