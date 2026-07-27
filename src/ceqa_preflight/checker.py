"""End-to-end local package inventory, inspection, and deterministic checking."""

from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from ceqa_preflight import __version__
from ceqa_preflight.models import FilingType, FindingStatus, InspectionReport, PackageManifest
from ceqa_preflight.observability import event
from ceqa_preflight.package_loader import open_package
from ceqa_preflight.pdf_inspector import inspect_pdf
from ceqa_preflight.rule_catalog import RuleCatalog
from ceqa_preflight.rule_engine import RuleContext, RuleEngine
from ceqa_preflight.rule_registry import default_catalog, default_registry

_MAX_INSPECTION_WORKERS = 4

DISCLAIMER = (
    "CEQA Preflight is an advisory technical checker, not legal advice or a determination "
    "of CEQA compliance. Review all manual-review items before submission."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _has_pdf_signature(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(5) == b"%PDF-"


def _inspect_documents(documents: list[dict[str, object]], targets: list[tuple[int, Path]]) -> None:
    """Inspect PDFs concurrently; each inspection still runs in its own isolated process."""

    if not targets:
        return
    workers = min(_MAX_INSPECTION_WORKERS, len(targets), os.cpu_count() or 1)
    event("pdf_inspection_started", total=len(targets))
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(inspect_pdf, path): index for index, path in targets}
        for future in as_completed(futures):
            documents[futures[future]]["inspection"] = future.result()
            completed += 1
            event("pdf_inspection_progress", completed=completed, total=len(targets))


def _manifest_documents(manifest: PackageManifest | None) -> dict[str, tuple[str | None, bool]]:
    if manifest is None:
        return {}
    return {entry.path: (entry.category, entry.primary) for entry in manifest.documents}


def _filter_catalog(
    catalog: RuleCatalog,
    rule_ids: set[str] | None,
    exclude_rule_ids: set[str] | None,
) -> RuleCatalog:
    known = {rule.id for rule in catalog.rules}
    unknown = sorted(((rule_ids or set()) | (exclude_rule_ids or set())) - known)
    if unknown:
        raise ValueError(f"unknown rule identifier(s): {', '.join(unknown)}")
    rules = [
        rule
        for rule in catalog.rules
        if (rule_ids is None or rule.id in rule_ids)
        and (exclude_rule_ids is None or rule.id not in exclude_rule_ids)
    ]
    if not rules:
        raise ValueError("rule selection removed every applicable rule")
    return RuleCatalog(catalog_version=catalog.catalog_version, rules=rules)


def check_package(
    source: Path,
    filing_type: FilingType,
    *,
    manifest: PackageManifest | None = None,
    include_experimental: bool = False,
    rule_ids: set[str] | None = None,
    exclude_rule_ids: set[str] | None = None,
) -> tuple[InspectionReport, int]:
    """Inspect a local package and return a source-cited advisory report.

    Filing-specific rules remain excluded unless the caller explicitly opts into
    experimental checks while they complete the permissioned practitioner pilot.
    """

    if manifest is not None and manifest.filing_type is not filing_type:
        raise ValueError("manifest filing_type does not match the requested filing type")
    declarations = _manifest_documents(manifest)
    documents: list[dict[str, object]] = []
    fingerprint_lines: list[str] = []
    with open_package(source) as root:
        paths = sorted(
            (path for path in root.rglob("*") if path.is_file()), key=lambda path: path.as_posix()
        )
        inspection_targets: list[tuple[int, Path]] = []
        for path in paths:
            relative_path = path.relative_to(root).as_posix()
            is_pdf = path.suffix.casefold() == ".pdf"
            signature_is_pdf = _has_pdf_signature(path) if is_pdf else None
            checksum = _sha256(path)
            category, primary = declarations.get(relative_path, (None, False))
            document: dict[str, object] = {
                "path": relative_path,
                "is_pdf": is_pdf,
                "signature_is_pdf": signature_is_pdf,
                "sha256": checksum,
                "size_bytes": path.stat().st_size,
                "category": category,
                "primary": primary,
            }
            if is_pdf and signature_is_pdf:
                inspection_targets.append((len(documents), path))
            documents.append(document)
            fingerprint_lines.append(f"{relative_path}\0{checksum}")
        _inspect_documents(documents, inspection_targets)

    catalog = _filter_catalog(default_catalog(filing_type), rule_ids, exclude_rule_ids)
    run = RuleEngine(catalog, default_registry()).run(
        RuleContext(
            filing_type=filing_type,
            facts={
                "documents": documents,
                "declared_paths": sorted(declarations) if manifest is not None else None,
            },
        ),
        include_experimental=include_experimental,
    )
    manual_review = [finding for finding in run.findings if finding.status is FindingStatus.MANUAL]
    findings = [finding for finding in run.findings if finding.status is not FindingStatus.MANUAL]
    report = InspectionReport(
        tool_version=__version__,
        ruleset_version=catalog.catalog_version,
        generated_at=datetime.now(UTC),
        input_fingerprint=hashlib.sha256("\n".join(fingerprint_lines).encode()).hexdigest(),
        filing_type=filing_type,
        findings=findings,
        manual_review=manual_review,
        disclaimer=DISCLAIMER,
    )
    if run.exit_code == 2:
        return report, 2
    if any(finding.status is FindingStatus.FAILURE for finding in findings):
        return report, 1
    return report, 0
