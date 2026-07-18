"""Safe package-loader tests using synthetic files only."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path

import pytest

from ceqa_preflight.limits import PackageLimits
from ceqa_preflight.package_loader import (
    PackageLoadError,
    _safe_archive_path,
    _validate_zip_info,
    open_package,
)


def _write_zip(path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_directory_package_is_yielded_without_mutation(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    notice = package / "NOE_Example.pdf"
    notice.write_text("synthetic notice", encoding="utf-8")
    original = notice.read_bytes()

    with open_package(package) as root:
        assert root == package.resolve()
        assert (root / notice.name).read_bytes() == original

    assert notice.read_bytes() == original


def test_zip_package_extracts_to_temporary_root_and_cleans_up(tmp_path: Path) -> None:
    archive = tmp_path / "package.zip"
    _write_zip(archive, {"notices/NOE_Example.pdf": "synthetic notice"})

    with open_package(archive) as root:
        extracted_root = root
        assert (root / "notices" / "NOE_Example.pdf").read_text(encoding="utf-8") == (
            "synthetic notice"
        )

    assert not extracted_root.exists()


def test_zip_slip_entry_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    _write_zip(archive, {"../outside.txt": "no"})

    with pytest.raises(PackageLoadError, match="unsafe path segment"), open_package(archive):
        pass


@pytest.mark.parametrize("unsafe_name", ["", "/absolute.pdf", "C:\\filings\\NOE.pdf"])
def test_archive_paths_must_be_safe_and_relative(unsafe_name: str) -> None:
    with pytest.raises(PackageLoadError):
        _safe_archive_path(unsafe_name)


def test_archive_symbolic_link_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as zip_file:
        zip_file.writestr(info, "target")

    with pytest.raises(PackageLoadError, match="symbolic link"), open_package(archive):
        pass


def test_archive_file_path_collision_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "collision.zip"
    _write_zip(archive, {"documents": "file", "documents/NOE.pdf": "nested file"})

    with pytest.raises(PackageLoadError, match="file-path collision"), open_package(archive):
        pass


def test_directory_symbolic_link_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    target = tmp_path / "target.pdf"
    target.write_text("synthetic", encoding="utf-8")
    (package / "linked.pdf").symlink_to(target)

    with pytest.raises(PackageLoadError, match="symbolic links"), open_package(package):
        pass


def test_directory_symbolic_link_directory_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (package / "linked-directory").symlink_to(target, target_is_directory=True)

    with pytest.raises(PackageLoadError, match="symbolic links"), open_package(package):
        pass


def test_file_count_limit_is_enforced(tmp_path: Path) -> None:
    archive = tmp_path / "many.zip"
    _write_zip(archive, {"one.pdf": "one", "two.pdf": "two"})
    limits = PackageLimits(max_files=1)

    with pytest.raises(PackageLoadError, match="file limit"), open_package(archive, limits):
        pass


def test_directory_size_limits_are_enforced(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "large.pdf").write_text("1234", encoding="utf-8")

    with (
        pytest.raises(PackageLoadError, match="size limit"),
        open_package(
            package,
            PackageLimits(max_file_bytes=3),
        ),
    ):
        pass

    with (
        pytest.raises(PackageLoadError, match="expanded size limit"),
        open_package(
            package,
            PackageLimits(max_expanded_bytes=3),
        ),
    ):
        pass


def test_unsafe_compression_ratio_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "compressed.zip"
    _write_zip(archive, {"repeat.txt": "A" * 20_000})
    limits = PackageLimits(max_compression_ratio=2)

    with pytest.raises(PackageLoadError, match="compression ratio"), open_package(archive, limits):
        pass


def test_non_zip_file_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "not-a-package.txt"
    source.write_text("not an archive", encoding="utf-8")

    with pytest.raises(PackageLoadError, match="directory or ZIP"), open_package(source):
        pass


def test_missing_input_and_invalid_limits_are_rejected(tmp_path: Path) -> None:
    with (
        pytest.raises(PackageLoadError, match="does not exist"),
        open_package(tmp_path / "missing.zip"),
    ):
        pass

    source = tmp_path / "package"
    source.mkdir()
    with (
        pytest.raises(PackageLoadError, match="limits"),
        open_package(
            source,
            PackageLimits(max_files=0),
        ),
    ):
        pass


def test_symbolic_link_input_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "package-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(PackageLoadError, match="symbolic-link inputs"), open_package(link):
        pass


def test_archive_entry_metadata_rejects_duplicates_and_special_files() -> None:
    regular = zipfile.ZipInfo("notice.pdf")
    regular.external_attr = (stat.S_IFREG | 0o644) << 16
    seen_paths: set[str] = set()
    file_paths: set[str] = set()
    limits = PackageLimits()

    _validate_zip_info(regular, seen_paths, file_paths, 0, 0, limits)

    with pytest.raises(PackageLoadError, match="duplicate paths"):
        _validate_zip_info(regular, seen_paths, file_paths, 1, 0, limits)

    fifo = zipfile.ZipInfo("pipe")
    fifo.external_attr = (stat.S_IFIFO | 0o644) << 16
    with pytest.raises(PackageLoadError, match="non-regular"):
        _validate_zip_info(fifo, set(), set(), 0, 0, limits)

    encrypted = zipfile.ZipInfo("encrypted.pdf")
    encrypted.flag_bits = 0x1
    with pytest.raises(PackageLoadError, match="encrypted"):
        _validate_zip_info(encrypted, set(), set(), 0, 0, limits)
