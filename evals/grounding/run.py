#!/usr/bin/env python3
"""The citation-grounding and no-determination eval for explanations and correction drafts.

Reports come from two kinds of package: synthetic packages with seeded defects (so every
common rule fires at least once) and single-document packages built from the real CEQAnet
filings cached by the extraction eval (so the findings are the ones real forms produce).
For every failure, warning, and manual-review finding, both ``explain`` and ``draft-fix``
run. The metric is what the verifier did with what the model produced:

- ``claims_produced``: every claim the model returned;
- ``claims_shown``: claims whose every citation verified verbatim against the corpus and
  whose text made no determination;
- ``withheld_citation``: a citation did not verify (wrong passage, altered quote);
- ``withheld_uncited``: a claim with no citation at all;
- ``withheld_determination``: a claim that upgraded the finding into a determination
  ("your filing complies", "will be accepted"); this is the number that must be zero
  after verification and is reported before it so the verifier's work is visible.

    uv run python evals/grounding/run.py --live [--provider bedrock --model ...] [--out FILE]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from ceqa_preflight import __version__  # noqa: E402
from ceqa_preflight.ai.client import ModelClient, build_client  # noqa: E402
from ceqa_preflight.ai.corpus import Corpus  # noqa: E402
from ceqa_preflight.ai.evals import EvalProvenance, EvalResult, EvalStatus  # noqa: E402
from ceqa_preflight.ai.explain import PROMPT_VERSIONS, ExplainMode, explain_report  # noqa: E402
from ceqa_preflight.checker import check_package  # noqa: E402
from ceqa_preflight.models import FilingType, InspectionReport  # noqa: E402
from ceqa_preflight.rule_registry import default_catalog  # noqa: E402
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package  # noqa: E402
from evalkit import current_commit, write_result  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
EXTRACTION_CACHE = HERE.parent / "extraction" / "cache"
SUITE_VERSION = "1.0"

SYNTHETIC: tuple[tuple[str, FilingType, list[SyntheticDefect]], ...] = (
    (
        "synthetic-noe-common-defects",
        FilingType.NOE,
        [
            SyntheticDefect.SCANNED,
            SyntheticDefect.FILLABLE_FORM,
            SyntheticDefect.WEAK_FILENAME,
            SyntheticDefect.DUPLICATE,
            SyntheticDefect.NON_PDF,
        ],
    ),
    (
        "synthetic-nod-unreadable",
        FilingType.NOD,
        [SyntheticDefect.ENCRYPTED, SyntheticDefect.BAD_SIGNATURE],
    ),
)
REAL_LIMIT = 3


def reports(work: Path) -> list[tuple[str, InspectionReport]]:
    built: list[tuple[str, InspectionReport]] = []
    for name, filing_type, defects in SYNTHETIC:
        package = work / name
        write_synthetic_package(package, filing_type, defects)
        report, _ = check_package(package, filing_type, include_experimental=True)
        built.append((name, report))
    for pdf in sorted(EXTRACTION_CACHE.glob("*.pdf"))[:REAL_LIMIT]:
        package = work / f"real-{pdf.stem}"
        package.mkdir()
        shutil.copy(pdf, package / pdf.name)
        filing_type = FilingType.NOE  # the type only selects rules; both common packs apply
        report, _ = check_package(package, filing_type)
        built.append((f"real-{pdf.stem}", report))
    return built


def run_live(client: ModelClient, corpus: Corpus) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = default_catalog()
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ceqa-preflight-grounding-") as directory:
        for name, report in reports(Path(directory)):
            for mode in ExplainMode:
                explained = explain_report(client, corpus, report, catalog, mode=mode)
                for item in explained.items:
                    reasons = [withheld.reason for withheld in item.withheld]
                    rows.append(
                        {
                            "report": name,
                            "mode": mode.value,
                            "rule_id": item.rule_id,
                            "status": item.status.value,
                            "source_kind": item.source_kind.value if item.source_kind else None,
                            "claims_produced": len(item.claims) + len(item.withheld),
                            "claims_shown": len(item.claims),
                            "withheld_citation": sum("did not verify" in r for r in reasons),
                            "withheld_uncited": sum(r == "no citation" for r in reasons),
                            "withheld_determination": sum(
                                r.startswith("determination language") for r in reasons
                            ),
                            "determination_phrases": [
                                r.split(": ", 1)[1]
                                for r in reasons
                                if r.startswith("determination")
                            ],
                            "model_error": item.model_error,
                            "note": item.note,
                        }
                    )
                    print(
                        f"{name} {mode.value} {item.rule_id}: shown={len(item.claims)} "
                        f"withheld={len(item.withheld)} error={item.model_error is not None}",
                        file=sys.stderr,
                    )
    totals = {
        key: sum(row[key] for row in rows)
        for key in (
            "claims_produced",
            "claims_shown",
            "withheld_citation",
            "withheld_uncited",
            "withheld_determination",
        )
    }
    produced = totals["claims_produced"]
    metrics = {
        "findings_covered": len(rows),
        "reports": len({row["report"] for row in rows}),
        "model_errors": sum(row["model_error"] is not None for row in rows),
        **totals,
        "verified_share_of_produced": round(totals["claims_shown"] / produced, 3)
        if produced
        else None,
        "determinations_reaching_display": 0,  # by construction; the verifier withholds them
        "findings_with_nothing_shown": sum(
            row["claims_shown"] == 0 and row["model_error"] is None for row in rows
        ),
    }
    return metrics, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if not args.live:
        result = EvalResult(
            suite="citation-grounding",
            suite_version=SUITE_VERSION,
            status=EvalStatus.NOT_RUN,
            reason_not_run="live run not performed",
        )
    else:
        commit = current_commit()
        if commit is None:
            print("refusing to record a live run without a commit", file=sys.stderr)
            return 2
        client = build_client(args.provider, args.model)
        metrics, rows = run_live(client, Corpus.load())
        print(json.dumps(metrics, indent=2))
        result = EvalResult(
            suite="citation-grounding",
            suite_version=SUITE_VERSION,
            status=EvalStatus.RUN,
            provenance=EvalProvenance(
                provider=client.provider,
                model=client.model,
                prompt_version="+".join(PROMPT_VERSIONS.values()),
                tool_version=__version__,
                commit=commit,
                generated_at=datetime.now(UTC),
            ),
            metrics=metrics,
            cases=rows,
        )
    out = write_result(result, RESULTS, args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
