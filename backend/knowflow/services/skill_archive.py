from __future__ import annotations

import io
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_NESTED_ARCHIVE_SUFFIXES = {
    ".7z",
    ".bz2",
    ".gz",
    ".gzip",
    ".jar",
    ".rar",
    ".tar",
    ".tbz",
    ".tbz2",
    ".tgz",
    ".txz",
    ".whl",
    ".xz",
    ".zip",
    ".zst",
}
_ALLOWED_SUFFIXES = {
    ".c",
    ".cfg",
    ".cjs",
    ".cpp",
    ".css",
    ".csv",
    ".gif",
    ".h",
    ".html",
    ".ini",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".jsx",
    ".log",
    ".mjs",
    ".md",
    ".markdown",
    ".pdf",
    ".png",
    ".ps1",
    ".py",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsv",
    ".tsx",
    ".txt",
    ".webp",
    ".xml",
    ".yaml",
    ".yml",
}
_WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:($|/)")
_WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL"}
_COPY_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class SkillArchiveLimits:
    max_archive_bytes: int
    max_extracted_bytes: int
    max_files: int
    max_file_bytes: int
    max_depth: int


@dataclass(frozen=True)
class ExtractedSkill:
    root: Path
    manifest_path: Path
    file_count: int
    extracted_bytes: int


class SkillArchiveError(ValueError):
    code = "skill_import_rejected"

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _ValidatedMember:
    info: zipfile.ZipInfo
    path: PurePosixPath
    is_directory: bool


def _reject_invalid_limits(limits: SkillArchiveLimits) -> None:
    values = (
        limits.max_archive_bytes,
        limits.max_extracted_bytes,
        limits.max_files,
        limits.max_file_bytes,
        limits.max_depth,
    )
    if any(type(value) is not int or value < 0 for value in values):
        raise SkillArchiveError("invalid_limits")


def _validated_path(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename.replace("\\", "/")
    if not name or "\x00" in name:
        raise SkillArchiveError("traversal")
    if name.startswith("/") or _WINDOWS_DRIVE_PATTERN.match(name):
        raise SkillArchiveError("traversal")

    raw_parts = name.split("/")
    if info.is_dir() and raw_parts[-1] == "":
        raw_parts = raw_parts[:-1]
    if (
        not raw_parts
        or any(part in {"", ".", ".."} for part in raw_parts)
        or any(":" in part for part in raw_parts)
        or any(part.endswith((" ", ".")) for part in raw_parts)
    ):
        raise SkillArchiveError("traversal")
    for part in raw_parts:
        stem = part.split(".", 1)[0].upper()
        if (
            stem in _WINDOWS_DEVICE_NAMES
            or re.fullmatch(r"(?:COM|LPT)[1-9]", stem)
        ):
            raise SkillArchiveError("traversal")

    path = PurePosixPath(*raw_parts)
    if path.is_absolute() or ".." in path.parts:
        raise SkillArchiveError("traversal")
    return path


def _validate_member_type(info: zipfile.ZipInfo) -> None:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise SkillArchiveError("link")
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise SkillArchiveError("link")
    if info.is_dir() and file_type == stat.S_IFREG:
        raise SkillArchiveError("link")
    if not info.is_dir() and file_type == stat.S_IFDIR:
        raise SkillArchiveError("link")


def _validate_members(
    bundle: zipfile.ZipFile,
    limits: SkillArchiveLimits,
) -> tuple[list[_ValidatedMember], PurePosixPath, int]:
    validated: list[_ValidatedMember] = []
    files: list[_ValidatedMember] = []
    seen_paths: set[str] = set()
    declared_total = 0

    for info in bundle.infolist():
        path = _validated_path(info)
        normalized_key = path.as_posix().casefold()
        if normalized_key in seen_paths:
            raise SkillArchiveError("traversal")
        seen_paths.add(normalized_key)

        _validate_member_type(info)
        is_directory = info.is_dir()
        if len(path.parts) > limits.max_depth:
            raise SkillArchiveError("depth")
        member = _ValidatedMember(info, path, is_directory)
        validated.append(member)
        if is_directory:
            continue

        files.append(member)
        if len(files) > limits.max_files:
            raise SkillArchiveError("file_count")
        if info.file_size < 0 or info.file_size > limits.max_file_bytes:
            raise SkillArchiveError("file_size")
        declared_total += info.file_size
        if declared_total > limits.max_extracted_bytes:
            raise SkillArchiveError("extracted_size")

        suffix = path.suffix.casefold()
        if suffix in _NESTED_ARCHIVE_SUFFIXES:
            raise SkillArchiveError("nested_archive")
        if suffix not in _ALLOWED_SUFFIXES:
            raise SkillArchiveError("binary")
        if info.flag_bits & 0x1:
            raise SkillArchiveError("invalid_zip")

    manifests = [member for member in files if member.path.name == "SKILL.md"]
    if not manifests:
        raise SkillArchiveError("missing_manifest")
    if len(manifests) != 1:
        raise SkillArchiveError("ambiguous_manifest")

    manifest = manifests[0].path
    if len(manifest.parts) not in {1, 2}:
        raise SkillArchiveError("ambiguous_manifest")
    root = manifest.parent
    root_parts = () if root == PurePosixPath(".") else root.parts
    for member in validated:
        if member.path.parts[: len(root_parts)] != root_parts:
            raise SkillArchiveError("ambiguous_manifest")
    return validated, manifest, len(files)


def _resolved_member_path(destination: Path, path: PurePosixPath) -> Path:
    target = destination.joinpath(*path.parts).resolve()
    try:
        target.relative_to(destination)
    except ValueError as exc:
        raise SkillArchiveError("traversal") from exc
    return target


def inspect_and_extract_zip(
    archive: bytes,
    *,
    destination: Path,
    limits: SkillArchiveLimits,
) -> ExtractedSkill:
    _reject_invalid_limits(limits)
    if not isinstance(archive, bytes):
        raise SkillArchiveError("invalid_zip")
    if len(archive) > limits.max_archive_bytes:
        raise SkillArchiveError("archive_size")

    destination = Path(destination).resolve()
    if os.path.lexists(destination):
        raise SkillArchiveError("destination_exists")

    try:
        bundle = zipfile.ZipFile(io.BytesIO(archive))
        with bundle:
            validated, manifest_relative, file_count = _validate_members(
                bundle,
                limits,
            )

            destination.mkdir(parents=True, exist_ok=False)
            extracted_total = 0
            for member in validated:
                target = _resolved_member_path(destination, member.path)
                if member.is_directory:
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                member_total = 0
                with bundle.open(member.info, "r") as source, target.open("xb") as output:
                    while True:
                        chunk = source.read(_COPY_CHUNK_BYTES)
                        if not chunk:
                            break
                        member_total += len(chunk)
                        extracted_total += len(chunk)
                        if member_total > limits.max_file_bytes:
                            raise SkillArchiveError("file_size")
                        if extracted_total > limits.max_extracted_bytes:
                            raise SkillArchiveError("extracted_size")
                        output.write(chunk)

            manifest_path = _resolved_member_path(destination, manifest_relative)
            root = manifest_path.parent
            return ExtractedSkill(
                root=root,
                manifest_path=manifest_path,
                file_count=file_count,
                extracted_bytes=extracted_total,
            )
    except SkillArchiveError:
        if destination.exists():
            shutil.rmtree(destination)
        raise
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError, ValueError) as exc:
        if destination.exists():
            shutil.rmtree(destination)
        raise SkillArchiveError("invalid_zip") from exc
