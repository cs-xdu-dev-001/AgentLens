from __future__ import annotations

import io
import stat
import sys
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.skill_archive import (  # noqa: E402
    SkillArchiveError,
    SkillArchiveLimits,
    inspect_and_extract_zip,
)


VALID_MANIFEST = b"---\nname: safe-skill\ndescription: Safe test Skill.\n---\nBody\n"
LIMITS = SkillArchiveLimits(
    max_archive_bytes=100_000,
    max_extracted_bytes=1_000,
    max_files=5,
    max_file_bytes=600,
    max_depth=3,
)


def make_zip(
    members: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=compression) as bundle:
        for name, content in members:
            bundle.writestr(name, content)
    return stream.getvalue()


def expect_rejected(
    archive: bytes,
    destination: Path,
    reason: str,
    *,
    limits: SkillArchiveLimits = LIMITS,
) -> None:
    try:
        inspect_and_extract_zip(
            archive,
            destination=destination,
            limits=limits,
        )
    except SkillArchiveError as exc:
        assert exc.code == "skill_import_rejected"
        assert exc.reason == reason, (exc.reason, reason)
    else:
        raise AssertionError(f"archive unexpectedly accepted for {reason}")
    assert not destination.exists(), (reason, list(destination.rglob("*")))


def special_member(name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = mode << 16
    return info


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)

        unsafe_cases = {
            "traversal": make_zip(
                [("safe.txt", b"must not be written"), ("..\\escape.txt", b"x")]
            ),
            "absolute": make_zip(
                [("safe.txt", b"must not be written"), ("/escape.txt", b"x")]
            ),
            "windows_absolute": make_zip(
                [("safe.txt", b"must not be written"), ("C:\\escape.txt", b"x")]
            ),
            "windows_device": make_zip(
                [("SKILL.md", VALID_MANIFEST), ("NUL.txt", b"x")]
            ),
            "casefold_duplicate": make_zip(
                [
                    ("SKILL.md", VALID_MANIFEST),
                    ("A.txt", b"one"),
                    ("a.TXT", b"two"),
                ]
            ),
            "nested_archive": make_zip(
                [("SKILL.md", VALID_MANIFEST), ("payload.zip", b"PK")]
            ),
            "nested_gzip": make_zip(
                [("SKILL.md", VALID_MANIFEST), ("payload.gzip", b"\x1f\x8b")]
            ),
            "binary": make_zip(
                [("SKILL.md", VALID_MANIFEST), ("payload.exe", b"MZ")]
            ),
            "missing_manifest": make_zip([("README.md", b"x")]),
            "ambiguous_manifest": make_zip(
                [
                    ("one/SKILL.md", VALID_MANIFEST),
                    ("two/SKILL.md", VALID_MANIFEST),
                ]
            ),
            "ambiguous_root": make_zip(
                [
                    ("package/SKILL.md", VALID_MANIFEST),
                    ("outside/README.md", b"x"),
                ]
            ),
            "outside_empty_directory": make_zip(
                [
                    ("package/", b""),
                    ("package/SKILL.md", VALID_MANIFEST),
                    ("outside/", b""),
                ]
            ),
            "deep_manifest": make_zip(
                [
                    ("a/", b""),
                    ("a/b/", b""),
                    ("a/b/SKILL.md", VALID_MANIFEST),
                ]
            ),
        }
        expected_reasons = {
            "traversal": "traversal",
            "absolute": "traversal",
            "windows_absolute": "traversal",
            "windows_device": "traversal",
            "casefold_duplicate": "traversal",
            "nested_archive": "nested_archive",
            "nested_gzip": "nested_archive",
            "binary": "binary",
            "missing_manifest": "missing_manifest",
            "ambiguous_manifest": "ambiguous_manifest",
            "ambiguous_root": "ambiguous_manifest",
            "outside_empty_directory": "ambiguous_manifest",
            "deep_manifest": "ambiguous_manifest",
        }
        for label, archive in unsafe_cases.items():
            expect_rejected(
                archive,
                base / label,
                expected_reasons[label],
            )

        symlink = special_member("link.md", stat.S_IFLNK | 0o777)
        expect_rejected(
            make_zip([("SKILL.md", VALID_MANIFEST), (symlink, b"target")]),
            base / "symlink",
            "link",
        )
        device = special_member("device.txt", stat.S_IFCHR | 0o600)
        expect_rejected(
            make_zip([("SKILL.md", VALID_MANIFEST), (device, b"x")]),
            base / "device",
            "link",
        )

        expect_rejected(
            b"not a zip",
            base / "invalid",
            "invalid_zip",
        )
        expect_rejected(
            make_zip([("SKILL.md", VALID_MANIFEST)]),
            base / "archive-size",
            "archive_size",
            limits=SkillArchiveLimits(10, 1_000, 5, 600, 3),
        )
        expect_rejected(
            make_zip(
                [
                    ("SKILL.md", VALID_MANIFEST),
                    ("a.txt", b"a"),
                    ("b.txt", b"b"),
                ]
            ),
            base / "file-count",
            "file_count",
            limits=SkillArchiveLimits(100_000, 1_000, 2, 600, 3),
        )
        expect_rejected(
            make_zip(
                [
                    ("SKILL.md", VALID_MANIFEST),
                    ("a/b/c/d.txt", b"x"),
                ]
            ),
            base / "depth",
            "depth",
        )
        expect_rejected(
            make_zip([("SKILL.md", VALID_MANIFEST), ("large.txt", b"x" * 601)]),
            base / "file-size",
            "file_size",
        )
        expect_rejected(
            make_zip(
                [
                    ("SKILL.md", VALID_MANIFEST),
                    ("one.txt", b"x" * 500),
                    ("two.txt", b"x" * 500),
                ]
            ),
            base / "extracted-size",
            "extracted_size",
        )
        limit_fields = (
            "max_archive_bytes",
            "max_extracted_bytes",
            "max_files",
            "max_file_bytes",
            "max_depth",
        )
        for field in limit_fields:
            expect_rejected(
                make_zip([("SKILL.md", VALID_MANIFEST)]),
                base / f"boolean-{field}",
                "invalid_limits",
                limits=replace(LIMITS, **{field: True}),
            )

        existing = base / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        try:
            inspect_and_extract_zip(
                make_zip([("SKILL.md", VALID_MANIFEST)]),
                destination=existing,
                limits=LIMITS,
            )
        except SkillArchiveError as exc:
            assert exc.reason == "destination_exists"
        else:
            raise AssertionError("existing destination unexpectedly accepted")
        assert marker.read_text(encoding="utf-8") == "keep"

        corrupt = make_zip(
            [("SKILL.md", VALID_MANIFEST), ("note.txt", b"unique-payload")]
        )
        corrupt = corrupt.replace(b"unique-payload", b"broken-payload", 1)
        expect_rejected(corrupt, base / "corrupt", "invalid_zip")

        root_archive = make_zip(
            [
                ("SKILL.md", VALID_MANIFEST),
                ("references/", b""),
                ("references/root-guide.md", b"root guide"),
            ]
        )
        root_extracted = inspect_and_extract_zip(
            root_archive,
            destination=base / "root-good",
            limits=LIMITS,
        )
        assert root_extracted.root == (base / "root-good").resolve()
        assert root_extracted.manifest_path == root_extracted.root / "SKILL.md"
        assert root_extracted.file_count == 2
        assert root_extracted.extracted_bytes == (
            len(VALID_MANIFEST) + len(b"root guide")
        )

        good = make_zip(
            [
                ("repo-main/", b""),
                ("repo-main/SKILL.md", VALID_MANIFEST),
                ("repo-main/references/guide.md", b"guide"),
                ("repo-main/references/notes.log", b"log"),
                ("repo-main/assets/icon.png", b"\x89PNG\r\n"),
                ("repo-main/scripts/helper.py", b"print('stored only')\n"),
            ],
            compression=zipfile.ZIP_DEFLATED,
        )
        extracted = inspect_and_extract_zip(
            good,
            destination=base / "good",
            limits=LIMITS,
        )
        assert extracted.root == (base / "good" / "repo-main").resolve()
        assert extracted.manifest_path == extracted.root / "SKILL.md"
        assert extracted.file_count == 5
        assert extracted.extracted_bytes == (
            len(VALID_MANIFEST)
            + len(b"guide")
            + len(b"log")
            + len(b"\x89PNG\r\n")
            + len(b"print('stored only')\n")
        )
        assert extracted.manifest_path.read_bytes() == VALID_MANIFEST
        assert (extracted.root / "references" / "guide.md").read_bytes() == b"guide"

    print("skill archive security checks passed")


if __name__ == "__main__":
    main()
