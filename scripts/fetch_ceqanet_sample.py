#!/usr/bin/env python3
"""Maintainer tool: fetch a small, varied sample of real CEQAnet filings for the extraction eval.

CEQAnet (https://ceqanet.lci.ca.gov) publishes every Notice of Exemption and Notice of
Determination filed with the State Clearinghouse, together with the structured metadata the
lead agency entered. That metadata is the gold for ``evals/extraction``: the same document,
described by the people who filed it.

What this script commits and what it does not:

- ``evals/extraction/cases/<sch>-<doc>.json``: the CEQAnet identifiers, the attachment URL
  and its SHA-256, the document type, the fetch time, and the gold fields drawn from the
  CSV export. Contact phone, email, and street address are never written; the contact's
  name is kept because it is part of the public record's own metadata and is a field the
  extraction must find.
- ``evals/extraction/cache/``: the PDFs themselves, which are gitignored. The eval harness
  re-fetches a missing PDF and checks its hash before using it.

Network use is polite: one request per second, an identifying User-Agent, and nothing under
the one path robots.txt disallows (``/*/AttachmentZip``). This is not part of ``make verify``.

    uv run python scripts/fetch_ceqanet_sample.py \
        --discover NOE 3 "StartRange=2026-06-01&EndRange=2026-08-21" \
        --discover NOD 2 "StartRange=2024-01-01&EndRange=2024-03-01&Region=Southern%20California"
    uv run python scripts/fetch_ceqanet_sample.py --document 2026080811/1
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://ceqanet.lci.ca.gov"
CASES = ROOT / "evals" / "extraction" / "cases"
CACHE = ROOT / "evals" / "extraction" / "cache"
_USER_AGENT = "ceqa-preflight-eval-fetch/1.0 (+https://github.com/ChelseaKR/ceqa-preflight)"
_MIN_INTERVAL = 1.0
_MAX_BYTES = 25 * 1024 * 1024
_FORM_LABELS = {"NOE": "Notice of Exemption", "NOD": "Notice of Determination"}

Fetcher = Callable[[str], bytes]
_last_request = 0.0


def _fetch(url: str) -> bytes:
    """One polite GET: rate-limited, identified, bounded."""

    global _last_request
    if not url.startswith("https://"):
        raise ValueError(f"unsupported URL: {url}")
    if "/AttachmentZip" in url:
        raise ValueError("robots.txt disallows AttachmentZip")
    wait = _MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        data = response.read(_MAX_BYTES + 1)
    _last_request = time.monotonic()
    if len(data) > _MAX_BYTES:
        raise ValueError(f"response exceeds {_MAX_BYTES} bytes: {url}")
    return data


def document_links(search_html: str) -> list[tuple[str, str]]:
    """Return (sch, document_id) pairs in page order, each once."""

    seen: list[tuple[str, str]] = []
    for sch, doc in re.findall(r'href="/(\d{10})/(\d+)"', search_html):
        if (sch, doc) not in seen:
            seen.append((sch, doc))
    return seen


def attachments(document_html: str) -> list[tuple[str, str, str]]:
    """Return (category label, filename label, href) for each attachment on a document page."""

    main = document_html[document_html.find("Attachments") :]
    found: list[tuple[str, str, str]] = []
    pattern = re.compile(r'<a[^>]*href="(/\d{10}/\d+/Attachment/[^"]+)"[^>]*>(.*?)</a>', re.S)
    for match in pattern.finditer(main):
        href = match.group(1)
        label = html.unescape(" ".join(re.sub(r"<[^>]+>", " ", match.group(2)).split()))
        before = re.sub(r"<[^>]+>", "\n", main[: match.start()])
        lines = [html.unescape(" ".join(line.split())) for line in before.split("\n")]
        lines = [line for line in lines if line]
        category = lines[-1] if lines else ""
        found.append((category, label, href))
    return found


_GOLD_COLUMNS = {
    "project_title": ("Document Title", "Project Title"),
    "lead_agency": ("Lead Agency Name",),
    "sch_number": ("SCH Number",),
    "county": ("Counties",),
    "city_or_community": ("Cities",),
    "project_location": ("Location Cross Streets",),
    "contact_name": ("Contact Full Name",),
    "exemption_status": ("NOE Exempt Status",),
    "exemption_citation": ("NOE Exempt Citation",),
    "nod_approval_date": ("NOD Approved Date",),
}


def gold_from_csv(text: str) -> dict[str, Any]:
    """Map the CEQAnet CSV export to the extraction field names; blanks become ``None``."""

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("CSV export had no rows")
    row = {key.strip(): (value or "").strip() for key, value in rows[0].items() if key}
    gold: dict[str, Any] = {}
    for field, columns in _GOLD_COLUMNS.items():
        values = [row.get(column, "") for column in columns]
        values = [value for value in values if value]
        distinct = len(set(values)) > 1
        gold[field] = values if distinct else (values[0] if values else None)
    eir = row.get("NOD Environmental Impact Report Prepared", "").lower() == "yes"
    nd = row.get("NOD Negative Declaration Prepared", "").lower() == "yes"
    mitigation = row.get("NOD Mitigation Measures", "").lower() == "yes"
    if eir:
        gold["nod_environmental_document"] = "EIR"
    elif nd:
        gold["nod_environmental_document"] = (
            ["Negative Declaration", "Mitigated Negative Declaration"]
            if mitigation
            else "Negative Declaration"
        )
    else:
        gold["nod_environmental_document"] = None
    gold["document_type"] = row.get("Document Type") or None
    return gold


def fetch_case(sch: str, doc: str, *, fetch: Fetcher = _fetch) -> dict[str, Any] | None:
    """Fetch one document's metadata and single form attachment; return the case record."""

    page = fetch(f"{BASE}/{sch}/{doc}").decode("utf-8", errors="replace")
    found = attachments(page)
    csv_text = fetch(f"{BASE}/Search?Sch={sch}&DocumentId={doc}&OutputFormat=CSV").decode(
        "utf-8-sig", errors="replace"
    )
    gold = gold_from_csv(csv_text)
    document_type = (gold.get("document_type") or "").upper()
    form_label = _FORM_LABELS.get(document_type)
    forms = [item for item in found if form_label and item[0] == form_label]
    if len(forms) != 1:
        print(f"skip {sch}/{doc}: {len(forms)} {form_label!r} attachment(s)", file=sys.stderr)
        return None
    category, label, href = forms[0]
    data = fetch(f"{BASE}{href}")
    if data[:5] != b"%PDF-":
        print(f"skip {sch}/{doc}: attachment is not a PDF", file=sys.stderr)
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / f"{sch}-{doc}.pdf").write_bytes(data)
    return {
        "id": f"{sch}-{doc}",
        "sch_number": sch,
        "document_id": doc,
        "document_url": f"{BASE}/{sch}/{doc}",
        "document_type": document_type,
        "attachment_url": f"{BASE}{href}",
        "attachment_category": category,
        "attachment_label": label,
        "attachment_sha256": hashlib.sha256(data).hexdigest(),
        "attachment_bytes": len(data),
        "other_attachments": len(found) - 1,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "gold": {key: value for key, value in gold.items() if key != "document_type"},
    }


def discover(
    document_type: str, limit: int, *, query: str = "", fetch: Fetcher = _fetch
) -> list[dict[str, Any]]:
    """Take filings of one type, one per lead agency, that carry exactly one form PDF.

    ``query`` is an extra CEQAnet search query string (for example
    ``StartRange=2025-01-01&EndRange=2025-03-01&County=Kern``) so a sample can be spread
    across years, regions, and agencies rather than taken from one listing page.
    """

    extra = f"&{query}" if query else ""
    search = fetch(f"{BASE}/Search?DocumentType={document_type}{extra}").decode(
        "utf-8", errors="replace"
    )
    cases: list[dict[str, Any]] = []
    agencies: set[str] = set()
    for sch, doc in document_links(search):
        if len(cases) >= limit:
            break
        if (CASES / f"{sch}-{doc}.json").exists():
            continue
        case = fetch_case(sch, doc, fetch=fetch)
        if case is None:
            continue
        agency = str(case["gold"].get("lead_agency") or "").casefold()
        if agency in agencies:
            print(f"skip {sch}/{doc}: another filing by the same agency", file=sys.stderr)
            continue
        agencies.add(agency)
        cases.append(case)
    return cases


def write_case(case: dict[str, Any]) -> Path:
    CASES.mkdir(parents=True, exist_ok=True)
    path = CASES / f"{case['id']}.json"
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None, fetch: Fetcher = _fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discover",
        nargs=3,
        action="append",
        metavar=("TYPE", "N", "QUERY"),
        default=[],
        help="fetch N filings of TYPE (NOE or NOD) matching QUERY ('' for none)",
    )
    parser.add_argument(
        "--document", action="append", default=[], metavar="SCH/DOC", help="fetch one filing"
    )
    args = parser.parse_args(argv)
    written: list[Path] = []
    for sch_doc in args.document:
        sch, _, doc = sch_doc.partition("/")
        case = fetch_case(sch, doc or "1", fetch=fetch)
        if case is not None:
            written.append(write_case(case))
    for document_type, count, query in args.discover:
        for case in discover(document_type.upper(), int(count), query=query, fetch=fetch):
            written.append(write_case(case))
    for path in written:
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"{len(written)} case(s) written; PDFs cached under {CACHE.relative_to(ROOT)}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
