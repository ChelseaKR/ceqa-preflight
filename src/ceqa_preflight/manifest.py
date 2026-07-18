"""Manifest loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ceqa_preflight.models import PackageManifest


class ManifestError(ValueError):
    """Raised when a manifest cannot be loaded or validated."""


def load_manifest(path: Path) -> PackageManifest:
    """Load a YAML or JSON package manifest from an explicit local path."""

    if not path.is_file():
        raise ManifestError(f"manifest does not exist or is not a file: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestError(f"could not read manifest: {path}") from error

    try:
        parsed: Any = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ManifestError(f"could not parse manifest: {path}") from error

    if not isinstance(parsed, dict):
        raise ManifestError("manifest root must be a mapping")

    try:
        return PackageManifest.model_validate(parsed)
    except ValidationError as error:
        raise ManifestError(f"manifest validation failed: {error}") from error
