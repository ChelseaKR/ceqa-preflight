"""Aggregate written JSON reports into the counts a CI job publishes.

The composite action in ``action.yml`` needs three numbers -- failures, warnings, and
checks that did not run -- to set as step outputs. It could count them in shell, and that
is exactly what this module exists to prevent: a second implementation of a published
figure drifts from the first one silently, and the shell copy is the one nobody tests.
So the counting here is :func:`ceqa_preflight.reporting.summarize_counts`, the same
function the console summary line uses, over reports parsed as
:class:`~ceqa_preflight.models.InspectionReport` rather than as loose JSON.

The other reason this is a module and not an inline snippet is that it has a failure mode
worth testing. A directory with no report in it is not a clean run: it is a run that
produced nothing, and printing ``failures=0`` for it would publish an absence as a
measurement -- a green job standing on no evidence at all. ``main`` exits 2 and says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from ceqa_preflight.models import InspectionReport
from ceqa_preflight.reporting import summarize_counts

#: The counts published as action outputs, in the order they are written.
OUTPUT_KEYS = ("failures", "warnings", "not-run")

_COUNT_KEYS = {"failures": "failure", "warnings": "warning", "not-run": "not_run"}


class NoReportProduced(RuntimeError):
    """Raised when a directory that should hold reports holds none."""


def read_reports(directory: Path) -> list[InspectionReport]:
    """Parse every ``*.json`` report in ``directory``, sorted by name.

    A file that is not a report raises rather than being skipped. Skipping it would let a
    malformed report reduce the published counts without reducing anyone's confidence in
    them.
    """

    paths = sorted(path for path in directory.glob("*.json") if path.is_file())
    if not paths:
        raise NoReportProduced(f"no report produced in {directory}")
    reports = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise NoReportProduced(f"{path.name}: not readable as JSON: {error}") from error
        reports.append(InspectionReport.model_validate(payload))
    return reports


def summarize_reports(reports: Sequence[InspectionReport]) -> dict[str, int]:
    """Sum the published counts across every report in a batch."""

    totals = dict.fromkeys(OUTPUT_KEYS, 0)
    for report in reports:
        counts = summarize_counts(report)
        for output_key, count_key in _COUNT_KEYS.items():
            totals[output_key] += counts[count_key]
    return totals


def main(argv: Sequence[str] | None = None) -> int:
    """Write ``name=value`` output lines for a directory of reports. Returns an exit code."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory holding JSON reports.")
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="File to append GitHub Actions output lines to; stdout when omitted.",
    )
    arguments = parser.parse_args(argv)

    try:
        reports = read_reports(arguments.directory)
    except NoReportProduced as error:
        print(f"no report produced: {error}", file=sys.stderr)
        return 2

    lines = [f"{key}={value}" for key, value in summarize_reports(reports).items()]
    rendered = "\n".join(lines) + "\n"
    if arguments.output_file is None:
        sys.stdout.write(rendered)
    else:
        with arguments.output_file.open("a", encoding="utf-8") as destination:
            destination.write(rendered)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
