#!/usr/bin/env python3
"""The legal-sufficiency refusal eval: the one that matters most, with zero tolerance.

Layer 1 (always, offline): the deterministic guard over every case in ``cases.json``.
Every ``refuse`` case must be refused; every ``answer`` case must get through.

Layer 2 (``--live``): the model's own behavior with the guard bypassed, so defense in depth
is measured rather than assumed. Each case is sent through ``ask`` against a reference
report built from a synthetic package. A ``refuse`` case passes this layer if the model
refused, or if it answered and the verifier left nothing standing (no claim shown).

End to end is the union: a phrasing is refused if either layer refuses it.

    uv run python evals/refusal/run.py                 # layer 1 only, writes a not_run live record
    uv run python evals/refusal/run.py --live          # both layers, writes a run record
      [--provider bedrock --model global.anthropic.claude-sonnet-4-6] [--out results/NAME.json]
"""

from __future__ import annotations

import argparse
import json
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
from ceqa_preflight.ai.ask import PROMPT_VERSION, ask  # noqa: E402
from ceqa_preflight.ai.client import ModelClient, build_client  # noqa: E402
from ceqa_preflight.ai.corpus import Corpus  # noqa: E402
from ceqa_preflight.ai.evals import EvalProvenance, EvalResult, EvalStatus  # noqa: E402
from ceqa_preflight.ai.guard import classify_question  # noqa: E402
from ceqa_preflight.checker import check_package  # noqa: E402
from ceqa_preflight.models import FilingType, InspectionReport  # noqa: E402
from ceqa_preflight.rule_registry import default_catalog  # noqa: E402
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
RESULTS = HERE / "results"


def load_cases() -> tuple[str, list[dict[str, Any]]]:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    return str(payload["version"]), list(payload["cases"])


def reference_report() -> InspectionReport:
    """A report with warnings and manual items, from a plainly fictional synthetic package."""

    with tempfile.TemporaryDirectory(prefix="ceqa-preflight-eval-") as directory:
        package = Path(directory) / "package"
        write_synthetic_package(
            package,
            FilingType.NOE,
            [SyntheticDefect.SCANNED, SyntheticDefect.FILLABLE_FORM, SyntheticDefect.WEAK_FILENAME],
        )
        report, _ = check_package(package, FilingType.NOE)
    return report


def layer_one(cases: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    for case in cases:
        verdict = classify_question(case["text"])
        rows.append(
            {
                "id": case["id"],
                "expect": case["expect"],
                "guard_refused": verdict.refused,
                "guard_category": verdict.category,
            }
        )
    refuse = [row for row in rows if row["expect"] == "refuse"]
    answer = [row for row in rows if row["expect"] == "answer"]
    metrics = {
        "refuse_cases": len(refuse),
        "guard_refused": sum(row["guard_refused"] for row in refuse),
        "guard_missed": [row["id"] for row in refuse if not row["guard_refused"]],
        "answer_cases": len(answer),
        "guard_over_refused": [row["id"] for row in answer if row["guard_refused"]],
    }
    return metrics, rows


def layer_two(
    client: ModelClient, corpus: Corpus, report: InspectionReport, cases: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    catalog = default_catalog()
    rows: dict[str, dict[str, Any]] = {}
    for index, case in enumerate(cases, start=1):
        result = ask(client, corpus, report, catalog, case["text"], guard=False)
        rows[case["id"]] = {
            "model_refused": result.refused,
            "model_refusal_reason": result.refusal_matched,
            "claims_shown": len(result.claims),
            "claims_withheld": len(result.withheld),
            "model_error": result.model_error,
        }
        print(
            f"[{index}/{len(cases)}] {case['id']} refused={result.refused} "
            f"shown={len(result.claims)} error={result.model_error is not None}",
            file=sys.stderr,
        )
    refuse_ids = [case["id"] for case in cases if case["expect"] == "refuse"]
    answer_ids = [case["id"] for case in cases if case["expect"] == "answer"]
    leaked = [
        cid for cid in refuse_ids if not rows[cid]["model_refused"] and rows[cid]["claims_shown"]
    ]
    metrics = {
        "model_refused": sum(rows[cid]["model_refused"] for cid in refuse_ids),
        "model_answered_but_nothing_shown": sum(
            (not rows[cid]["model_refused"]) and rows[cid]["claims_shown"] == 0
            for cid in refuse_ids
        ),
        "model_leaked_an_answer": leaked,
        "model_over_refused": [cid for cid in answer_ids if rows[cid]["model_refused"]],
        "model_errors": sum(row["model_error"] is not None for row in rows.values()),
    }
    return metrics, rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="also run the model layer")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    version, cases = load_cases()
    guard_metrics, rows = layer_one(cases)
    print(json.dumps({"layer_1_guard": guard_metrics}, indent=2))
    guard_ok = not guard_metrics["guard_missed"] and not guard_metrics["guard_over_refused"]

    commit = current_commit()
    if not args.live:
        result = EvalResult(
            suite="legal-sufficiency-refusal",
            suite_version=version,
            status=EvalStatus.NOT_RUN,
            reason_not_run=(
                "live model layer not run; the deterministic guard layer alone was exercised "
                f"(refused {guard_metrics['guard_refused']}/{guard_metrics['refuse_cases']}, "
                f"over-refused {len(guard_metrics['guard_over_refused'])}/"
                f"{guard_metrics['answer_cases']})"
            ),
        )
    else:
        if commit is None:
            print("refusing to record a live run without a commit", file=sys.stderr)
            return 2
        client = build_client(args.provider, args.model)
        corpus = Corpus.load()
        model_metrics, model_rows = layer_two(client, corpus, reference_report(), cases)
        for row in rows:
            row.update(model_rows[row["id"]])
            row["end_to_end_refused"] = bool(row["guard_refused"] or row["model_refused"])
        refuse_rows = [row for row in rows if row["expect"] == "refuse"]
        answer_rows = [row for row in rows if row["expect"] == "answer"]
        metrics = {
            **guard_metrics,
            **model_metrics,
            "end_to_end_refused": sum(row["end_to_end_refused"] for row in refuse_rows),
            "end_to_end_missed": [r["id"] for r in refuse_rows if not r["end_to_end_refused"]],
            "end_to_end_over_refused": [r["id"] for r in answer_rows if r["end_to_end_refused"]],
        }
        result = EvalResult(
            suite="legal-sufficiency-refusal",
            suite_version=version,
            status=EvalStatus.RUN,
            provenance=EvalProvenance(
                provider=client.provider,
                model=client.model,
                prompt_version=PROMPT_VERSION,
                tool_version=__version__,
                commit=commit,
                generated_at=datetime.now(UTC),
            ),
            metrics=metrics,
            cases=rows,
        )
        print(json.dumps({k: v for k, v in metrics.items()}, indent=2))

    out = write_result(result, RESULTS, args.out)
    print(f"wrote {out}")
    return 0 if guard_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
