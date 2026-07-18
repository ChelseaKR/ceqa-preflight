"""Tests for safe manifest-template creation."""

from pathlib import Path

import pytest

from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.scaffold import manifest_template, write_manifest_template


def test_template_is_schema_valid_for_each_supported_filing_type() -> None:
    for filing_type in FilingType:
        template = manifest_template(filing_type)
        assert template.filing_type is filing_type
        assert template.documents[0].primary is True


def test_write_template_does_not_overwrite(tmp_path: Path) -> None:
    destination = write_manifest_template(tmp_path / "new-package", FilingType.NOD)

    assert load_manifest(destination).filing_type is FilingType.NOD
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_manifest_template(destination.parent, FilingType.NOD)
