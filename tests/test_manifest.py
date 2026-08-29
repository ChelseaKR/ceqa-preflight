"""Manifest and report contract tests."""

from __future__ import annotations

import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ceqa_preflight.manifest import ManifestError, load_manifest
from ceqa_preflight.models import FilingType, InspectionReport, PackageManifest, SourceCitation


def _manifest_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "filing_type": "NOE",
        "project": {
            "title": "Town Hall Solar Canopy",
            "lead_agency": "Example City",
            "county": "Sacramento",
        },
        "documents": [
            {
                "path": "notices/NOE_Town_Hall_Solar_Canopy.pdf",
                "category": "Notice of Exemption",
                "primary": True,
            }
        ],
    }


def test_yaml_and_json_manifests_are_equivalent(tmp_path: Path) -> None:
    payload = _manifest_payload()
    yaml_path = tmp_path / "package.yaml"
    json_path = tmp_path / "package.json"
    yaml_path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_manifest(yaml_path) == load_manifest(json_path)


def test_unknown_manifest_schema_major_fails(tmp_path: Path) -> None:
    payload = _manifest_payload()
    payload["schema_version"] = "2.0"
    path = tmp_path / "package.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")

    with pytest.raises(ManifestError, match="unsupported manifest schema major"):
        load_manifest(path)


def test_manifest_root_must_be_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "package.yaml"
    path.write_text("- not\n- a manifest\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="manifest root must be a mapping"):
        load_manifest(path)


def test_missing_manifest_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="does not exist"):
        load_manifest(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "unsafe_path",
    ["../NOE.pdf", "/tmp/NOE.pdf", "C:\\filings\\NOE.pdf", "notices/../NOE.pdf"],
)
def test_document_path_cannot_escape_package_root(unsafe_path: str) -> None:
    payload = _manifest_payload()
    documents = payload["documents"]
    assert isinstance(documents, list)
    first_document = documents[0]
    assert isinstance(first_document, dict)
    first_document["path"] = unsafe_path

    with pytest.raises(ValidationError, match="document path"):
        PackageManifest.model_validate(payload)


def test_report_serializes_with_schema_contract() -> None:
    report = InspectionReport(
        tool_version="0.1.0.dev0",
        ruleset_version="0.0.0",
        generated_at=datetime.now(UTC),
        input_fingerprint="sha256:example",
        filing_type=FilingType.NOE,
        disclaimer="Advisory only; this is not legal advice.",
    )

    serialized = report.model_dump(mode="json")

    assert serialized["report_schema_version"] == "1.1"
    assert serialized["filing_type"] == "NOE"
    assert serialized["not_run"] == []


def test_source_citation_rejects_non_http_url() -> None:
    with pytest.raises(ValidationError, match="absolute HTTP"):
        SourceCitation(title="Example", url="file:///tmp/not-a-source")


# CITATION.cff once carried `date-released: "2026-07-18"`, which was the first commit date
# and not a release: no tag and no GitHub Release have ever been cut, and CHANGELOG.md holds
# only `## Unreleased`. Citation tooling surfaces that field as a release date, so it stayed
# omitted. These gates keep the file honest against the two in-repo sources of truth.

_ROOT = Path(__file__).resolve().parent.parent
_RELEASED_HEADING = re.compile(r"^##\s+\[?\d+\.\d+\.\d+", re.MULTILINE)


def _citation() -> dict[str, object]:
    return yaml.safe_load((_ROOT / "CITATION.cff").read_text(encoding="utf-8"))


def test_citation_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert _citation()["version"] == pyproject["project"]["version"]


def test_citation_claims_no_release_date_until_one_is_released() -> None:
    """`date-released` may return only once CHANGELOG.md records an actual released version."""
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if _RELEASED_HEADING.search(changelog) is None:
        assert "date-released" not in _citation(), (
            "CITATION.cff states a release date, but CHANGELOG.md records no released "
            "version. Add date-released only once a version is actually tagged and released."
        )
