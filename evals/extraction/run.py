#!/usr/bin/env python3
"""The real-filing extraction eval: ``ai extract`` against CEQAnet's own metadata.

Each case in ``cases/`` is one real Notice of Exemption or Notice of Determination that a
California agency filed, identified by its CEQAnet SCH number and document id, with the
structured metadata CEQAnet publishes for it as gold. The PDFs live in the gitignored
``cache/`` and are re-fetched by hash when missing.

Per field, the outcome is one of:

- ``match``: a verified value that equals the gold after normalization (or, for the
  exemption citation, cites the same Guidelines section number);
- ``mismatch``: a verified value that differs from the gold, listed for a person to look at
  (the form and the metadata legitimately disagree sometimes);
- ``abstained_gold_present``: the extraction said ``unknown`` but CEQAnet holds a value;
  often legitimate (the SCH number is assigned after filing) and always reported;
- ``withheld``: the model proposed a value whose quote did not verify, so it was not shown;
- ``filled_gold_absent``: a verified value where CEQAnet holds nothing. This is the defect
  the verifier exists to prevent; it is counted separately and never folded into accuracy;
- ``both_absent``: nothing on either side.

    uv run python evals/extraction/run.py --live [--provider bedrock --model ...] [--out FILE]
    uv run python evals/extraction/run.py            # records not_run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "scripts"))

from evalkit import current_commit, write_result  # noqa: E402

from ceqa_preflight import __version__  # noqa: E402
from ceqa_preflight.ai.client import ModelClient, build_client  # noqa: E402
from ceqa_preflight.ai.evals import EvalProvenance, EvalResult, EvalStatus  # noqa: E402
from ceqa_preflight.ai.extraction import (  # noqa: E402
    FIELD_NAMES,
    PROMPT_VERSION,
    DocumentExtraction,
    DocumentKind,
    FieldStatus,
    extract_document,
)
from ceqa_preflight.ai.text import extract_document_text  # noqa: E402

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
CACHE = HERE / "cache"
RESULTS = HERE / "results"
SUITE_VERSION = "1.0"

# Fields CEQAnet's export does not hold; they are extracted but cannot be scored.
UNSCORED = {"project_applicant", "signature_date"}
# Fields whose values are never written to a result file.
REDACTED_VALUES = {"contact_name"}
_PHONE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SECTION = re.compile(r"15\d{3}")
_KIND_FOR_TYPE = {"NOE": DocumentKind.NOE_FORM, "NOD": DocumentKind.NOD_FORM}


def redact(text: str | None) -> str | None:
    if text is None:
        return None
    return _EMAIL.sub("[email redacted]", _PHONE.sub("[phone redacted]", text))


_ABBREVIATIONS = {
    "dept": "department",
    "com": "community",
    "dev": "development",
    "div": "division",
    "co": "county",
    "st": "street",
    "ave": "avenue",
    "rd": "road",
    "blvd": "boulevard",
    "hwy": "highway",
    "mt": "mount",
    "&": "and",
}
_STOPWORDS = {"of", "the", "a", "an"}
_FIELD_STOPWORDS = {"county": {"county"}, "city_or_community": {"city", "community"}}


def normalize(value: str) -> str:
    lowered = value.casefold().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(_ABBREVIATIONS.get(token, token) for token in lowered.split())


def tokens(field: str, value: str) -> frozenset[str]:
    """Order-insensitive tokens: "Belmont, City of" and "City of Belmont" compare equal."""

    drop = _STOPWORDS | _FIELD_STOPWORDS.get(field, set())
    return frozenset(token for token in normalize(value).split() if token not in drop)


def _date_key(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", value)
    if match:
        month, day, year = (int(part) for part in match.groups())
        return (year + 2000 if year < 100 else year, month, day)
    months = "january february march april may june july august september october november december"
    match = re.search(r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", value.casefold())
    if match and match.group(1) in months.split():
        return (int(match.group(3)), months.split().index(match.group(1)) + 1, int(match.group(2)))
    return None


def values_match(field: str, extracted: str, gold: str | list[str]) -> bool:
    candidates = gold if isinstance(gold, list) else [gold]
    left = normalize(extracted)
    for candidate in candidates:
        right = normalize(candidate)
        if left == right:
            return True
        if field in {"county", "city_or_community"} and left in {
            normalize(part) for part in re.split(r"[,;/]", candidate)
        }:
            return True
        if field == "exemption_citation":
            sections = set(_SECTION.findall(extracted)) & set(_SECTION.findall(candidate))
            if sections:
                return True
        if field in {"nod_approval_date", "signature_date"}:
            keys = (_date_key(extracted), _date_key(candidate))
            if keys[0] is not None and keys[0] == keys[1]:
                return True
        if tokens(field, extracted) == tokens(field, candidate):
            return True
        if field in {"lead_agency", "project_title", "contact_name"} and (
            left in right or right in left
        ):
            return True
    return False


def score_field(field: str, extraction: DocumentExtraction, gold: Any) -> dict[str, Any]:
    item = extraction.field(field)
    status = item.status if item else FieldStatus.UNKNOWN
    gold_present = gold not in (None, "", [])
    if status is FieldStatus.UNVERIFIED:
        outcome = "withheld"
    elif status is FieldStatus.UNKNOWN:
        outcome = "abstained_gold_present" if gold_present else "both_absent"
    elif not gold_present:
        outcome = "filled_gold_absent"
    else:
        outcome = "match" if values_match(field, item.value or "", gold) else "mismatch"
    row: dict[str, Any] = {"field": field, "outcome": outcome, "status": status.value}
    if field not in REDACTED_VALUES:
        row["extracted"] = redact(item.value if item else None)
        row["gold"] = (
            [redact(part) for part in gold] if isinstance(gold, list) else redact(gold or None)
        )
        row["quote"] = redact(item.quote if item else None)
    return row


def ensure_pdf(case: dict[str, Any]) -> Path:
    path = CACHE / f"{case['id']}.pdf"
    if not path.exists():
        from fetch_ceqanet_sample import _fetch

        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_fetch(case["attachment_url"]))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != case["attachment_sha256"]:
        raise RuntimeError(f"{case['id']}: cached PDF hash {digest} != recorded hash")
    return path


def run_case(client: ModelClient, case: dict[str, Any]) -> dict[str, Any]:
    path = ensure_pdf(case)
    text = extract_document_text(path)
    extraction = extract_document(client, text)
    expected_kind = _KIND_FOR_TYPE[case["document_type"]]
    scored = [
        score_field(field, extraction, case["gold"].get(field))
        for field in FIELD_NAMES
        if field not in UNSCORED
    ]
    return {
        "id": case["id"],
        "document_type": case["document_type"],
        "document_url": case["document_url"],
        "has_text_layer": text.has_text_layer,
        "pages_read": text.pages_read,
        "attempted": extraction.attempted,
        "reason_not_attempted": extraction.reason_not_attempted,
        "model_error": extraction.model_error,
        "document_kind": extraction.document_kind.value,
        "document_kind_correct": extraction.document_kind is expected_kind,
        "fields": scored,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    per_field: dict[str, dict[str, int]] = {}
    for row in rows:
        for scored in row["fields"]:
            outcomes[scored["outcome"]] = outcomes.get(scored["outcome"], 0) + 1
            bucket = per_field.setdefault(scored["field"], {})
            bucket[scored["outcome"]] = bucket.get(scored["outcome"], 0) + 1
    scored_present = outcomes.get("match", 0) + outcomes.get("mismatch", 0)
    return {
        "cases": len(rows),
        "cases_attempted": sum(row["attempted"] for row in rows),
        "cases_without_text_layer": sum(not row["has_text_layer"] for row in rows),
        "cases_with_model_error": sum(row["model_error"] is not None for row in rows),
        "document_kind_correct": sum(row["document_kind_correct"] for row in rows),
        "field_outcomes": outcomes,
        "exact_or_normalized_match_rate_when_filled": (
            round(outcomes.get("match", 0) / scored_present, 3) if scored_present else None
        ),
        "filled_gold_absent": outcomes.get("filled_gold_absent", 0),
        "per_field": per_field,
    }


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(CASES.glob("*.json"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    cases = load_cases()
    if not args.live:
        result = EvalResult(
            suite="real-filing-extraction",
            suite_version=SUITE_VERSION,
            status=EvalStatus.NOT_RUN,
            reason_not_run=f"live run not performed; {len(cases)} case(s) are committed",
        )
    else:
        commit = current_commit()
        if commit is None:
            print("refusing to record a live run without a commit", file=sys.stderr)
            return 2
        client = build_client(args.provider, args.model)
        rows = []
        for index, case in enumerate(cases, start=1):
            row = run_case(client, case)
            rows.append(row)
            print(
                f"[{index}/{len(cases)}] {row['id']} kind={row['document_kind']} "
                f"{[s['outcome'][:5] for s in row['fields']]}",
                file=sys.stderr,
            )
        metrics = aggregate(rows)
        print(json.dumps(metrics, indent=2))
        result = EvalResult(
            suite="real-filing-extraction",
            suite_version=SUITE_VERSION,
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
    out = write_result(result, RESULTS, args.out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
