#!/usr/bin/env python3
"""CodeQL SARIF gate — fails the build on any error-severity finding.

ceqa-preflight is a private repo with no GitHub Advanced Security, so `codeql-action/analyze`
runs with `upload: never` (the code-scanning SARIF-upload API isn't available and would otherwise
fail the job with "Code scanning is not enabled for this repository"). Without upload, nothing else
makes the CodeQL job reflect its own findings — this script reads the SARIF CodeQL writes locally
and fails if any result's rule carries `problem.severity: error` (CodeQL's own severity, surfaced
per-result in `properties.problem.severity` or via the rule's default `level`).

    python3 scripts/codeql_gate.py <sarif-dir-or-file> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _sarif_files(paths: list[str]) -> list[str]:
    out: list[str] = []
    for p in paths:
        candidate = Path(p)
        if candidate.is_dir():
            out += [str(f) for f in sorted(candidate.rglob("*.sarif"))]
        elif p.endswith(".sarif"):
            out.append(p)
    return out


def _is_error(result: dict[str, Any], rules_by_id: dict[str, Any]) -> bool:
    level = str(result.get("level") or "").lower()
    if level == "error":
        return True
    rule_id = result.get("ruleId")
    rule = rules_by_id.get(rule_id, {})
    sev = (rule.get("properties", {}) or {}).get("problem.severity", "")
    return str(sev).lower() == "error"


def main() -> int:
    paths = sys.argv[1:] or ["sarif-results"]
    files = _sarif_files(paths)
    if not files:
        # FAIL, never pass. No SARIF does not mean "no findings" — it means the analysis did not
        # run, or wrote somewhere else, or the output path changed under us. Returning 0 here
        # would make the gate go green vacuously: CodeQL could silently stop producing results
        # and every PR would still show a passing security check. A gate that cannot see its
        # input has not verified anything, so it must not report success.
        print(
            f"::error::no .sarif files found under {paths} — CodeQL produced no output, so "
            f"nothing was analyzed. This is a gate failure, not a pass: check the analyze step's "
            f"`output:` path and that the analyze step actually ran."
        )
        return 1
    total_errors = 0
    for f in files:
        with Path(f).open() as fh:
            doc = json.load(fh)
        for run in doc.get("runs", []):
            driver_rules = run.get("tool", {}).get("driver", {}).get("rules", []) or []
            rules_by_id = {r.get("id"): r for r in driver_rules}
            errors = [r for r in run.get("results", []) if _is_error(r, rules_by_id)]
            total_errors += len(errors)
            for e in errors:
                loc = (e.get("locations") or [{}])[0].get("physicalLocation", {})
                uri = loc.get("artifactLocation", {}).get("uri", "?")
                line = loc.get("region", {}).get("startLine", "?")
                print(
                    f"::error file={uri},line={line}::[{e.get('ruleId')}] "
                    f"{e.get('message', {}).get('text', '')}"
                )
    print(f"CodeQL: {total_errors} error-severity finding(s) across {len(files)} SARIF file(s).")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
