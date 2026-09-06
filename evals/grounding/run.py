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
  after verification and is reported before it so the verifier's work is visible;
- ``determinations_reaching_display``: the same check re-run over the claims that were
  actually shown. This is the figure that proves the tool never issues a determination,
  so it is read out of the displayed claims rather than inferred from the verifier's
  contract. It was previously published as a literal ``0`` annotated "by construction",
  which is the code under test asserting its own result: no regression that let a
  determination through could ever have moved it.

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

from evalkit import current_commit, write_result  # noqa: E402

from ceqa_preflight import __version__  # noqa: E402
from ceqa_preflight.ai.client import ModelClient, build_client  # noqa: E402
from ceqa_preflight.ai.corpus import Corpus  # noqa: E402
from ceqa_preflight.ai.evals import EvalProvenance, EvalResult, EvalStatus  # noqa: E402
from ceqa_preflight.ai.explain import (  # noqa: E402
    PROMPT_VERSIONS,
    ExplainMode,
    FindingExplanation,
    explain_report,
)
from ceqa_preflight.ai.guard import determination_language  # noqa: E402
from ceqa_preflight.checker import check_package  # noqa: E402
from ceqa_preflight.models import FilingType, InspectionReport  # noqa: E402
from ceqa_preflight.rule_registry import default_catalog  # noqa: E402
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package  # noqa: E402

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


def row_for(name: str, mode: ExplainMode, item: FindingExplanation) -> dict[str, Any]:
    """One eval row for one explained finding.

    ``determinations_shown`` scans the claims the reader actually sees with the same
    predicate the verifier uses to withhold them. The verifier is supposed to withhold
    every one, so the expected value is zero -- but expecting a number is not measuring
    it, and only a row built from the output can notice a claim that reached display
    without passing ``verify_claims``.
    """

    reasons = [withheld.reason for withheld in item.withheld]
    shown_determinations = [
        phrase
        for phrase in (determination_language(claim.text) for claim in item.claims)
        if phrase is not None
    ]
    return {
        "report": name,
        "mode": mode.value,
        "rule_id": item.rule_id,
        "status": item.status.value,
        "source_kind": item.source_kind.value if item.source_kind else None,
        "claims_produced": len(item.claims) + len(item.withheld),
        "claims_shown": len(item.claims),
        "withheld_citation": sum("did not verify" in r for r in reasons),
        "withheld_uncited": sum(r == "no citation" for r in reasons),
        "withheld_determination": sum(r.startswith("determination language") for r in reasons),
        "determination_phrases": [
            r.split(": ", 1)[1] for r in reasons if r.startswith("determination")
        ],
        "determinations_shown": len(shown_determinations),
        "determination_phrases_shown": shown_determinations,
        "model_error": item.model_error,
        "note": item.note,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the per-finding rows. Every published figure is derived here."""

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
    return {
        "findings_covered": len(rows),
        "reports": len({row["report"] for row in rows}),
        "model_errors": sum(row["model_error"] is not None for row in rows),
        **totals,
        "verified_share_of_produced": round(totals["claims_shown"] / produced, 3)
        if produced
        else None,
        "determinations_reaching_display": sum(row["determinations_shown"] for row in rows),
        "determination_phrases_reaching_display": sorted(
            {phrase for row in rows for phrase in row["determination_phrases_shown"]}
        ),
        "findings_with_nothing_shown": sum(
            row["claims_shown"] == 0 and row["model_error"] is None for row in rows
        ),
    }


def run_live(client: ModelClient, corpus: Corpus) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog = default_catalog()
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="ceqa-preflight-grounding-") as directory:
        for name, report in reports(Path(directory)):
            for mode in ExplainMode:
                explained = explain_report(client, corpus, report, catalog, mode=mode)
                for item in explained.items:
                    rows.append(row_for(name, mode, item))
                    print(
                        f"{name} {mode.value} {item.rule_id}: shown={len(item.claims)} "
                        f"withheld={len(item.withheld)} error={item.model_error is not None}",
                        file=sys.stderr,
                    )
    return summarize(rows), rows


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
