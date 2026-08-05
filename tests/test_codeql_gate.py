"""Tests for scripts/codeql_gate.py — especially that it does NOT fail open.

The four NoSarifFailsClosedTests cases are the point of this file. An earlier revision of the
gate returned 0 when it found no SARIF at all, which meant a silently broken analysis reported a
clean scan and every PR showed a passing security check. With no code-scanning dashboard on this
repo, the gate is the only thing standing between a broken analysis and a green build.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import codeql_gate  # type: ignore[import-not-found]  # noqa: E402


def _write(dirpath: str, name: str, doc: dict[str, Any]) -> Path:
    path = Path(dirpath) / name
    with path.open("w") as fh:
        json.dump(doc, fh)
    return path


def _sarif(
    results: list[dict[str, Any]], rules: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {"runs": [{"tool": {"driver": {"rules": rules or []}}, "results": results}]}


def _run(argv: list[str]) -> int:
    with mock.patch.object(sys, "argv", ["codeql_gate.py", *argv]):
        return int(codeql_gate.main())


class NoSarifFailsClosedTests(unittest.TestCase):
    """A missing SARIF means the analysis did not run — it must never read as a clean scan."""

    def test_empty_directory_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_run([d]), 1)

    def test_nonexistent_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_run([str(Path(d) / "sarif-results")]), 1)

    def test_default_path_absent_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            cwd = Path.cwd()
            os.chdir(d)
            try:
                self.assertEqual(_run([]), 1)
            finally:
                os.chdir(cwd)

    def test_directory_with_non_sarif_files_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "results.json").write_text("{}")
            self.assertEqual(_run([d]), 1)


class GateVerdictTests(unittest.TestCase):
    def test_sarif_with_no_findings_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write(d, "results.sarif", _sarif([]))
            self.assertEqual(_run([d]), 0)

    def test_error_level_result_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write(
                d,
                "results.sarif",
                _sarif([{"ruleId": "x/y", "level": "error", "message": {"text": "boom"}}]),
            )
            self.assertEqual(_run([d]), 1)

    def test_error_severity_rule_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write(
                d,
                "results.sarif",
                _sarif(
                    [{"ruleId": "x/y", "level": "note", "message": {"text": "boom"}}],
                    [{"id": "x/y", "properties": {"problem.severity": "error"}}],
                ),
            )
            self.assertEqual(_run([d]), 1)

    def test_warning_only_passes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _write(
                d,
                "results.sarif",
                _sarif(
                    [{"ruleId": "x/y", "level": "warning", "message": {"text": "meh"}}],
                    [{"id": "x/y", "properties": {"problem.severity": "warning"}}],
                ),
            )
            self.assertEqual(_run([d]), 0)

    def test_nested_sarif_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            nested = Path(d) / "runs" / "lang"
            nested.mkdir(parents=True)
            _write(
                str(nested),
                "results.sarif",
                _sarif([{"ruleId": "x/y", "level": "error", "message": {"text": "boom"}}]),
            )
            self.assertEqual(_run([d]), 1)


if __name__ == "__main__":
    unittest.main()
