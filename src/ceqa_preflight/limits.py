"""Resource limits for untrusted local filing packages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PackageLimits:
    """Bound resource use before expensive document inspection begins."""

    max_files: int = 100
    max_compressed_bytes: int = 250 * 1024 * 1024
    max_expanded_bytes: int = 500 * 1024 * 1024
    max_file_bytes: int = 100 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_pdf_pages: int = 2_000
    per_file_timeout_seconds: float = 60.0


DEFAULT_PACKAGE_LIMITS = PackageLimits()
