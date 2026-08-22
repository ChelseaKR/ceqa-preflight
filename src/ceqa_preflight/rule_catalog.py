"""Loading and validation for declarative, source-cited rule metadata."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator

from ceqa_preflight.models import FilingType, SourceCitation, StrictModel

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
_CHECK_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_EXECUTABLE_MARKERS = ("__import__", "eval(", "exec(", "subprocess", "os.system", "`", ";")


class RuleCatalogError(ValueError):
    """Raised when declarative rule metadata is malformed or unsafe."""


class RuleLifecycle(StrEnum):
    """Rule availability states, retained for a stable audit history."""

    ACTIVE = "active"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class RuleDefinition(StrictModel):
    """Metadata for one registered deterministic rule implementation."""

    id: str = Field(pattern=r"^[A-Z][A-Z0-9-]*\d$")
    version: str
    title: str = Field(min_length=1)
    check: str
    lifecycle: RuleLifecycle = RuleLifecycle.ACTIVE
    filing_types: list[FilingType] = Field(min_length=1)
    source: SourceCitation
    parameters: dict[str, Any] = Field(default_factory=dict)
    # CEQA Guidelines sections (14 CCR, e.g. "15062") whose text the explanation layer may
    # quote for this rule. Retrieval scope only: the rule engine never reads them.
    guidelines: list[str] = Field(default_factory=list)

    @field_validator("guidelines")
    @classmethod
    def require_guidelines_section_numbers(cls, value: list[str]) -> list[str]:
        for section in value:
            if not re.fullmatch(r"15\d{3}(?:\.\d+)?", section):
                raise ValueError("guidelines must be 14 CCR section numbers such as 15062")
        return value

    @field_validator("version")
    @classmethod
    def require_semantic_version(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("rule version must be a semantic version such as 1.0.0")
        return value

    @field_validator("check")
    @classmethod
    def require_registered_name_shape(cls, value: str) -> str:
        if not _CHECK_NAME.fullmatch(value):
            raise ValueError("check must be a lowercase Python registry name")
        return value

    @field_validator("parameters")
    @classmethod
    def reject_executable_looking_parameters(cls, value: dict[str, Any]) -> dict[str, Any]:
        for string_value in _iter_strings(value):
            if any(marker in string_value.lower() for marker in _EXECUTABLE_MARKERS):
                raise ValueError("rule parameters may not contain executable-looking values")
        return value


class RuleCatalog(StrictModel):
    """Ordered catalog loaded from one or more trusted project files."""

    catalog_version: str
    rules: list[RuleDefinition] = Field(default_factory=list)

    @field_validator("catalog_version")
    @classmethod
    def require_semantic_version(cls, value: str) -> str:
        if not _SEMVER.fullmatch(value):
            raise ValueError("catalog version must be a semantic version such as 1.0.0")
        return value


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_strings(key)
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)


def load_rule_catalog(paths: Iterable[Path]) -> RuleCatalog:
    """Load YAML rule files and reject duplicate identifiers deterministically."""

    definitions: list[RuleDefinition] = []
    catalog_version: str | None = None
    seen_ids: set[str] = set()
    for path in paths:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise RuleCatalogError(f"could not load rule catalog: {path}") from error
        if not isinstance(raw, dict):
            raise RuleCatalogError(f"rule catalog root must be a mapping: {path}")
        try:
            catalog = RuleCatalog.model_validate(raw)
        except ValueError as error:
            raise RuleCatalogError(f"invalid rule catalog: {path}") from error
        if catalog_version is None:
            catalog_version = catalog.catalog_version
        elif catalog.catalog_version != catalog_version:
            raise RuleCatalogError("all rule catalog files must use the same catalog version")
        for definition in catalog.rules:
            if definition.id in seen_ids:
                raise RuleCatalogError(f"duplicate rule identifier: {definition.id}")
            seen_ids.add(definition.id)
            definitions.append(definition)
    if catalog_version is None:
        raise RuleCatalogError("at least one rule catalog file is required")
    return RuleCatalog(catalog_version=catalog_version, rules=definitions)
