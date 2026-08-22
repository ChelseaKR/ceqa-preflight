"""Shared helpers for the eval harnesses. Not product code; never imported by the CLI."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from ceqa_preflight.ai.evals import EvalResult


def current_commit() -> str | None:
    """Return the checked-out commit, or ``None`` outside a git checkout."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def write_result(result: EvalResult, results_dir: Path, out: Path | None = None) -> Path:
    """Write a result file named by date, status, provider, and model unless ``out`` is given."""

    provenance = result.provenance
    suffix = f"-{provenance.provider}-{provenance.model}" if provenance else ""
    target = out or results_dir / f"{datetime.now(UTC):%Y-%m-%d}-{result.status.value}{suffix}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return target
