#!/usr/bin/env python3
"""CodeQL SARIF gate — fails the build on any error-severity finding.

ceqa-preflight is a private repo with no GitHub Advanced Security, so `codeql-action/analyze`
runs with `upload: never` (the code-scanning SARIF-upload API isn't available and would otherwise
fail the job with "Code scanning is not enabled for this repository"). Without upload, nothing else
makes the CodeQL job reflect its own findings — this script reads the SARIF CodeQL writes locally
and fails if any result's rule carries `problem.severity: error` (CodeQL's own severity, surfaced
per-result in `properties.problem.severity` or via the rule's default `level`).

Warning- and note-severity findings are REPORTED but deliberately do NOT affect the exit code.
They used to be invisible: the only line this script printed counted error-severity results, so
"CodeQL: 0 error-severity finding(s)" read as "CodeQL found nothing" when it often meant "CodeQL
found things, none of which this gate is allowed to fail on". The advisory summary below exists so
that distinction is visible in the log. Raising the floor to fail on warnings is a separate,
deliberate decision — it is not made here, and nothing that passes today starts failing.

    python3 scripts/codeql_gate.py <sarif-dir-or-file> [...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Report order for the advisory summary; anything unrecognized sorts after these.
_SEVERITY_ORDER = {"error": 0, "warning": 1, "note": 2}


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


def _severity(result: dict[str, Any], rules_by_id: dict[str, Any]) -> str:
    """Bucket a result for reporting.

    `error` is decided by `_is_error` and by nothing else, so the exit code is byte-for-byte the
    same as before this reporting was added — in particular a result whose own `level` is `note`
    but whose rule is `problem.severity: error` still counts as an error, not a note.
    """
    if _is_error(result, rules_by_id):
        return "error"
    level = str(result.get("level") or "").lower()
    if level:
        return level
    rule = rules_by_id.get(result.get("ruleId"), {})
    props = rule.get("properties", {}) or {}
    sev = str(props.get("problem.severity", "")).lower()
    if sev:
        # CodeQL's `recommendation` is SARIF's `note`.
        return "note" if sev == "recommendation" else sev
    default_level = str((rule.get("defaultConfiguration", {}) or {}).get("level", "")).lower()
    # SARIF's own default when nothing states a level is `warning`.
    return default_level or "warning"


def _report_advisory(counts: Counter[str], per_rule: Counter[tuple[str, str]]) -> None:
    advisory = {sev: n for sev, n in counts.items() if sev != "error"}
    if not advisory:
        print("CodeQL: no warning- or note-severity findings either.")
        return
    ordered = sorted(advisory.items(), key=lambda kv: (_SEVERITY_ORDER.get(kv[0], 99), kv[0]))
    parts = ", ".join(f"{n} {sev}" for sev, n in ordered)
    print(
        f"CodeQL (advisory, NOT gated): {parts}. These do not affect the exit code — this gate "
        f"fails on error-severity only. Listed so a green check is not read as 'nothing found'."
    )
    for (sev, rule_id), n in sorted(
        ((k, v) for k, v in per_rule.items() if k[0] != "error"),
        key=lambda kv: (_SEVERITY_ORDER.get(kv[0][0], 99), -kv[1], kv[0][1]),
    ):
        print(f"  {sev:<9} {n:>4}  {rule_id}")


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
    counts: Counter[str] = Counter()
    per_rule: Counter[tuple[str, str]] = Counter()
    total_errors = 0
    for f in files:
        with Path(f).open() as fh:
            doc = json.load(fh)
        for run in doc.get("runs", []):
            driver_rules = run.get("tool", {}).get("driver", {}).get("rules", []) or []
            rules_by_id = {r.get("id"): r for r in driver_rules}
            for result in run.get("results", []):
                sev = _severity(result, rules_by_id)
                counts[sev] += 1
                per_rule[(sev, str(result.get("ruleId") or "?"))] += 1
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
    _report_advisory(counts, per_rule)
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
