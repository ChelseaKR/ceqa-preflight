"""Safe, local loading of filing-package directories and ZIP archives."""

from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath

from ceqa_preflight.limits import DEFAULT_PACKAGE_LIMITS, PackageLimits


class PackageLoadError(ValueError):
    """Raised when a filing package is missing, unsafe, or exceeds limits."""


def _safe_archive_path(name: str) -> PurePosixPath:
    if not name or "\x00" in name:
        raise PackageLoadError("archive entry path must be non-empty and contain no null bytes")

    windows_path = PureWindowsPath(name)
    archive_path = PurePosixPath(name.replace("\\", "/"))
    if windows_path.is_absolute() or windows_path.drive or archive_path.is_absolute():
        raise PackageLoadError(f"archive entry must be relative: {name!r}")
    if any(part in {"", ".", ".."} for part in archive_path.parts):
        raise PackageLoadError(f"archive entry contains an unsafe path segment: {name!r}")
    return archive_path


def _require_positive_limits(limits: PackageLimits) -> None:
    values = (
        limits.max_files,
        limits.max_compressed_bytes,
        limits.max_expanded_bytes,
        limits.max_file_bytes,
        limits.max_compression_ratio,
    )
    if any(value <= 0 for value in values):
        raise PackageLoadError("all package limits must be greater than zero")


def _validate_directory(root: Path, limits: PackageLimits) -> None:
    file_count = 0
    total_size = 0

    for directory, directory_names, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        for directory_name in directory_names:
            candidate = current / directory_name
            if candidate.is_symlink():
                raise PackageLoadError(f"symbolic links are not allowed: {candidate}")

        for filename in filenames:
            candidate = current / filename
            if candidate.is_symlink():
                raise PackageLoadError(f"symbolic links are not allowed: {candidate}")

            file_stat = candidate.stat(follow_symlinks=False)
            if not stat.S_ISREG(file_stat.st_mode):
                raise PackageLoadError(f"only regular files are allowed: {candidate}")

            file_count += 1
            total_size += file_stat.st_size
            if file_count > limits.max_files:
                raise PackageLoadError(f"package exceeds the {limits.max_files} file limit")
            if file_stat.st_size > limits.max_file_bytes:
                raise PackageLoadError(f"file exceeds the size limit: {candidate.name}")
            if total_size > limits.max_expanded_bytes:
                raise PackageLoadError("package exceeds the expanded size limit")


def _validate_zip_info(
    info: zipfile.ZipInfo,
    seen_paths: set[str],
    file_paths: set[str],
    file_count: int,
    total_size: int,
    limits: PackageLimits,
) -> tuple[int, int]:
    archive_path = _safe_archive_path(info.filename)
    normalized_name = archive_path.as_posix()
    casefolded_name = normalized_name.casefold()
    if casefolded_name in seen_paths:
        raise PackageLoadError(f"archive contains duplicate paths: {info.filename!r}")
    if any(casefolded_name.startswith(f"{file_path}/") for file_path in file_paths):
        raise PackageLoadError(f"archive contains a file-path collision: {info.filename!r}")
    if not info.is_dir() and any(
        existing_path.startswith(f"{casefolded_name}/") for existing_path in seen_paths
    ):
        raise PackageLoadError(f"archive contains a file-path collision: {info.filename!r}")
    seen_paths.add(casefolded_name)

    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type == stat.S_IFLNK:
        raise PackageLoadError(f"archive contains a symbolic link: {info.filename!r}")
    if not info.is_dir() and file_type not in {0, stat.S_IFREG}:
        raise PackageLoadError(f"archive contains a non-regular file: {info.filename!r}")
    if info.flag_bits & 0x1:
        raise PackageLoadError(f"encrypted archive entries are not supported: {info.filename!r}")

    if info.is_dir():
        return file_count, total_size

    file_paths.add(casefolded_name)

    file_count += 1
    total_size += info.file_size
    if file_count > limits.max_files:
        raise PackageLoadError(f"package exceeds the {limits.max_files} file limit")
    if info.file_size > limits.max_file_bytes:
        raise PackageLoadError(f"archive entry exceeds the size limit: {info.filename!r}")
    if total_size > limits.max_expanded_bytes:
        raise PackageLoadError("package exceeds the expanded size limit")
    if info.file_size and not info.compress_size:
        raise PackageLoadError(f"archive entry has an unsafe compression ratio: {info.filename!r}")
    if info.compress_size and info.file_size / info.compress_size > limits.max_compression_ratio:
        raise PackageLoadError(f"archive entry has an unsafe compression ratio: {info.filename!r}")

    return file_count, total_size


def _extract_file(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    remaining_bytes: int,
) -> int:
    written = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with archive.open(info, "r") as source, destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > remaining_bytes:
                    raise PackageLoadError(
                        "archive exceeds the expanded size limit during extraction"
                    )
                target.write(chunk)
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageLoadError(f"could not extract archive entry: {info.filename!r}") from error
    return written


def _extract_zip(source: Path, destination: Path, limits: PackageLimits) -> None:
    if source.stat().st_size > limits.max_compressed_bytes:
        raise PackageLoadError("archive exceeds the compressed size limit")

    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise PackageLoadError(f"input is not a readable ZIP archive: {source}") from error

    with archive:
        file_count = 0
        declared_total = 0
        seen_paths: set[str] = set()
        file_paths: set[str] = set()
        entries = archive.infolist()
        for info in entries:
            file_count, declared_total = _validate_zip_info(
                info,
                seen_paths,
                file_paths,
                file_count,
                declared_total,
                limits,
            )

        actual_total = 0
        for info in entries:
            if info.is_dir():
                (destination / _safe_archive_path(info.filename)).mkdir(
                    parents=True,
                    exist_ok=True,
                )
                continue
            remaining_bytes = limits.max_expanded_bytes - actual_total
            actual_total += _extract_file(
                archive,
                info,
                destination / _safe_archive_path(info.filename),
                remaining_bytes,
            )


@contextmanager
def open_package(
    source: Path,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
) -> Iterator[Path]:
    """Yield a validated local package root and clean temporary ZIP extraction."""

    _require_positive_limits(limits)
    if source.is_symlink():
        raise PackageLoadError(f"symbolic-link inputs are not allowed: {source}")
    if not source.exists():
        raise PackageLoadError(f"package does not exist: {source}")

    if source.is_dir():
        root = source.resolve()
        _validate_directory(root, limits)
        yield root
        return

    if not source.is_file() or not zipfile.is_zipfile(source):
        raise PackageLoadError(f"package must be a directory or ZIP archive: {source}")

    with tempfile.TemporaryDirectory(prefix="ceqa-preflight-") as temporary_directory:
        root = Path(temporary_directory)
        _extract_zip(source, root, limits)
        yield root
