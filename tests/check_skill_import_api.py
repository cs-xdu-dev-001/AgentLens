from __future__ import annotations

import atexit
import importlib
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEST_ROOT = ROOT / "data" / "test-dbs" / "skill-import-api"


def cleanup_test_root() -> None:
    test_db_root = (ROOT / "data" / "test-dbs").resolve()
    if TEST_ROOT.is_symlink():
        raise RuntimeError("refusing to clean a symlinked Skill import API TEST_ROOT")
    resolved = TEST_ROOT.resolve()
    if resolved.relative_to(test_db_root) != Path("skill-import-api"):
        raise RuntimeError(
            "Skill import API TEST_ROOT must remain fixed under data/test-dbs"
        )
    runtime = sys.modules.get("knowflow.runtime")
    if runtime is not None:
        runtime.db.engine.dispose()
    if resolved.exists():
        shutil.rmtree(resolved)


def skill_zip(
    *,
    slug: str = "alice-research",
    version: str = "1.0.0",
    description: str = "Alice research workflow.",
    github_root: bool = False,
    nested_upload: bool = False,
) -> bytes:
    prefix = (
        "repo-main/skills/alice/"
        if github_root
        else ("package/" if nested_upload else "")
    )
    manifest = (
        "---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  knowflow:\n"
        f"    display_name: Alice Research\n"
        f"    version: {version}\n"
        "    required_tools: [web_search]\n"
        "---\n"
        "Collect sources and write a concise report.\n"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(prefix + "SKILL.md", manifest)
        bundle.writestr(prefix + "scripts/helper.py", "print('stored only')\n")
    return stream.getvalue()


class FakeResponse:
    status_code = 200
    headers: dict[str, str]

    def __init__(self, body: bytes):
        self.body = body
        self.headers = {"Content-Length": str(len(body))}

    def iter_content(self, chunk_size: int):
        yield self.body

    def close(self):
        pass


class FakeSession:
    def __init__(self, body: bytes):
        self.body = body
        self.trust_env = True

    def get(self, url: str, **kwargs):
        return FakeResponse(self.body)

    def close(self):
        pass


def register(client: TestClient, name: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": name,
            "email": f"{name}@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text


def main() -> None:
    db_path = TEST_ROOT / "db.sqlite"
    skill_dir = TEST_ROOT / "skills"
    import_dir = TEST_ROOT / "imports"
    cleanup_test_root()
    atexit.register(cleanup_test_root)
    TEST_ROOT.mkdir(parents=True)
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ.update(
        KNOWFLOW_DB_URL=f"sqlite:///{db_path.as_posix()}",
        KNOWFLOW_SKILL_DIR=str(skill_dir),
        KNOWFLOW_SKILL_IMPORT_DIR=str(import_dir),
        KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES="1024",
        KNOWFLOW_SECRET_KEY="skill-import-test",
        KNOWFLOW_VECTOR_BACKEND="local",
    )
    sys.path.insert(0, str(BACKEND))
    for name in list(sys.modules):
        if name == "main" or name.startswith("knowflow"):
            sys.modules.pop(name, None)
    app = importlib.import_module("main").app
    runtime = importlib.import_module("knowflow.runtime")
    from knowflow.services.skill_store import SkillStoreError

    unsafe_root_aliases = (
        "foo/..",
        ".",
        "",
        "foo\\..",
        "valid\\child",
        "C:\\temp\\skill",
        "\\\\server\\share\\skill",
    )
    for storage_root in (
        runtime.skills.skill_dir,
        runtime.skills.import_dir,
    ):
        for index, unsafe in enumerate(
            (*unsafe_root_aliases, str(storage_root))
        ):
            storage_root.mkdir(parents=True, exist_ok=True)
            sentinel = storage_root / f"root-sentinel-{index}.txt"
            sentinel.write_text("keep root", encoding="utf-8")
            other_skill = storage_root / "other-skill"
            other_skill.mkdir(exist_ok=True)
            other_sentinel = other_skill / "keep.txt"
            other_sentinel.write_text("keep sibling", encoding="utf-8")
            try:
                runtime.skills._cleanup_inside(storage_root, unsafe)
            except SkillStoreError as exc:
                assert exc.code == "skill_invalid_path"
            assert storage_root.is_dir(), (storage_root, unsafe)
            assert sentinel.read_text(encoding="utf-8") == "keep root"
            assert other_sentinel.read_text(encoding="utf-8") == "keep sibling"
            try:
                runtime.skills._inside(storage_root, unsafe)
            except SkillStoreError as exc:
                assert exc.code == "skill_invalid_path"
            else:
                raise AssertionError(
                    f"storage root alias unexpectedly accepted: {unsafe!r}"
                )

        removable = storage_root / "valid-child"
        removable.mkdir()
        (removable / "file.txt").write_text("remove child", encoding="utf-8")
        assert runtime.skills._inside(
            storage_root, "valid-child"
        ) == removable.resolve()
        nested = storage_root / "valid" / "child"
        nested.mkdir(parents=True)
        assert runtime.skills._inside(
            storage_root, "valid/child"
        ) == nested.resolve()
        runtime.skills._cleanup_inside(storage_root, "valid-child")
        assert not removable.exists()
        assert storage_root.is_dir()
        assert (storage_root / "other-skill" / "keep.txt").is_file()

    alice = TestClient(app)
    bob = TestClient(app)
    register(alice, "skill-import-alice")
    register(bob, "skill-import-bob")

    guarded_import = alice.post(
        "/api/skills/import/upload/inspect",
        files={
            "file": (
                "guarded.zip",
                skill_zip(slug="guarded-import"),
                "application/zip",
            )
        },
    ).json()["data"]
    runtime.execute(
        "UPDATE skill_import SET staged_path='foo/..' WHERE id=:id",
        {"id": guarded_import["importId"]},
    )
    import_root_sentinel = runtime.skills.import_dir / "api-root-sentinel.txt"
    import_root_sentinel.write_text("keep import root", encoding="utf-8")
    guarded_install = alice.post(
        f"/api/skills/import/{guarded_import['importId']}/install",
        json={"enabled": False},
    )
    assert guarded_install.status_code == 400, guarded_install.text
    assert guarded_install.json()["code"] == "skill_invalid_path"
    assert str(TEST_ROOT) not in guarded_install.text
    assert import_root_sentinel.read_text(encoding="utf-8") == "keep import root"

    github_archive = skill_zip(github_root=True)
    runtime.skills.session_factory = lambda: FakeSession(github_archive)
    try:
        runtime.skills._cleanup_inside(runtime.skills.import_dir, "")
    except Exception:
        pass
    else:
        raise AssertionError("cleanup must reject the configured root itself")
    assert runtime.skills.import_dir.is_dir()
    inspected = alice.post(
        "/api/skills/import/github/inspect",
        json={
            "url": "https://github.com/example/research.git",
            "ref": "main",
            "subpath": "skills/alice",
        },
    )
    assert inspected.status_code == 200, inspected.text
    preview = inspected.json()["data"]
    assert preview["name"] == "Alice Research"
    assert preview["slug"] == "alice-research"
    assert preview["scriptsExecutable"] is False
    assert preview["sourceKind"] == "github"
    assert preview["available"] is False
    assert "importId" in preview
    assert str(TEST_ROOT) not in inspected.text
    assert "staged" not in inspected.text.lower()

    assert (
        bob.post(
            f"/api/skills/import/{preview['importId']}/install",
            json={"enabled": False},
        ).status_code
        == 404
    )
    installed = alice.post(
        f"/api/skills/import/{preview['importId']}/install",
        json={"enabled": True},
    )
    assert installed.status_code == 200, installed.text
    item = installed.json()["data"]
    assert item["owner"] == "personal"
    assert item["enabled"] is False
    assert item["available"] is False
    old_package_id = item["packageId"]
    package = runtime.fetch_one(
        "SELECT package_path FROM skill_package WHERE id=:id",
        {"id": old_package_id},
    )
    assert package and not Path(package["package_path"]).is_absolute()

    expired_preview = alice.post(
        "/api/skills/import/upload/inspect",
        files={
            "file": (
                "expired.zip",
                skill_zip(slug="expired-skill", nested_upload=True),
                "application/zip",
            )
        },
    ).json()["data"]
    expired_row = runtime.fetch_one(
        "SELECT staged_path FROM skill_import WHERE id=:id",
        {"id": expired_preview["importId"]},
    )
    expired_container = (
        runtime.skills.import_dir
        / Path(expired_row["staged_path"]).parts[0]
    )
    runtime.execute(
        "UPDATE skill_import SET expires_at='2000-01-01 00:00:00' WHERE id=:id",
        {"id": expired_preview["importId"]},
    )
    expired = alice.post(
        f"/api/skills/import/{expired_preview['importId']}/install",
        json={"enabled": False},
    )
    assert expired.status_code == 410, expired.text
    assert expired.json()["code"] == "skill_import_expired"
    assert runtime.fetch_one(
        "SELECT id FROM skill_import WHERE id=:id",
        {"id": expired_preview["importId"]},
    ) is None
    assert not expired_container.exists()

    before_count = runtime.fetch_one(
        "SELECT COUNT(*) AS count FROM skill_package"
    )["count"]
    malformed_stream = io.BytesIO()
    with zipfile.ZipFile(malformed_stream, "w") as bundle:
        bundle.writestr("README.md", "missing manifest")
    malformed = alice.post(
        "/api/skills/import/upload/inspect",
        files={"file": ("bad.zip", malformed_stream.getvalue(), "application/zip")},
    )
    assert malformed.status_code == 400, malformed.text
    assert runtime.fetch_one(
        "SELECT COUNT(*) AS count FROM skill_package"
    )["count"] == before_count

    v2_preview = alice.post(
        "/api/skills/import/upload/inspect",
        files={
            "file": (
                "v2.zip",
                skill_zip(version="2.0.0", description="Second snapshot."),
                "application/zip",
            )
        },
    ).json()["data"]
    staged = runtime.fetch_one(
        "SELECT staged_path FROM skill_import WHERE id=:id",
        {"id": v2_preview["importId"]},
    )
    staged_path = (runtime.skills.import_dir / staged["staged_path"]).resolve()
    import shutil

    shutil.rmtree(staged_path)
    failed = alice.post(
        f"/api/skills/import/{v2_preview['importId']}/install",
        json={"enabled": False},
    )
    assert failed.status_code == 400, failed.text
    current = alice.get(f"/api/skills/{item['id']}").json()["data"]
    assert current["packageId"] == old_package_id

    successful_v2 = alice.post(
        "/api/skills/import/upload/inspect",
        files={"file": ("v2.zip", skill_zip(version="2.0.0"), "application/zip")},
    ).json()["data"]
    updated = alice.post(
        f"/api/skills/import/{successful_v2['importId']}/install",
        json={"enabled": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["packageId"] != old_package_id

    oversized = alice.post(
        "/api/skills/import/upload/inspect",
        files={"file": ("huge.zip", b"x" * 1025, "application/zip")},
    )
    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["code"] == "skill_archive_too_large"

    numeric = runtime.normalize_api_error_detail({"code": 40001, "message": "x"}, 400)
    textual = runtime.normalize_api_error_detail(
        {"code": "skill_invalid_source", "message": "x"},
        400,
    )
    assert numeric["code"] == 40001
    assert textual["code"] == "skill_invalid_source"
    json.dumps(inspected.json())
    print("skill staged import API checks passed")


if __name__ == "__main__":
    main()
