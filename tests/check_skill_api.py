from __future__ import annotations

import atexit
import importlib
import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEST_ROOT = ROOT / "data" / "test-dbs" / "skill-api"


def cleanup_test_root() -> None:
    test_db_root = (ROOT / "data" / "test-dbs").resolve()
    if TEST_ROOT.is_symlink():
        raise RuntimeError("refusing to clean a symlinked Skill API TEST_ROOT")
    resolved = TEST_ROOT.resolve()
    if resolved.relative_to(test_db_root) != Path("skill-api"):
        raise RuntimeError("Skill API TEST_ROOT must remain fixed under data/test-dbs")
    runtime = sys.modules.get("knowflow.runtime")
    if runtime is not None:
        runtime.db.engine.dispose()
    if resolved.exists():
        shutil.rmtree(resolved)


def archive(slug: str, description: str, body: str = "Run the workflow.") -> bytes:
    stream = io.BytesIO()
    manifest = (
        "---\n"
        f"name: {slug}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  knowflow:\n"
        "    version: 1.0.0\n"
        "---\n"
        f"{body}\n"
    )
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("SKILL.md", manifest)
        bundle.writestr("scripts/helper.py", "print('never executed')\n")
    return stream.getvalue()


def register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text


def install_upload(client: TestClient, payload: bytes) -> dict:
    preview = client.post(
        "/api/skills/import/upload/inspect",
        files={"file": ("skill.zip", payload, "application/zip")},
    )
    assert preview.status_code == 200, preview.text
    installed = client.post(
        f"/api/skills/import/{preview.json()['data']['importId']}/install",
        json={"enabled": False},
    )
    assert installed.status_code == 200, installed.text
    return installed.json()["data"]


def main() -> None:
    cleanup_test_root()
    atexit.register(cleanup_test_root)
    TEST_ROOT.mkdir(parents=True)
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ.update(
        KNOWFLOW_DB_URL=f"sqlite:///{(TEST_ROOT / 'db.sqlite').as_posix()}",
        KNOWFLOW_SKILL_DIR=str(TEST_ROOT / "skills"),
        KNOWFLOW_SKILL_IMPORT_DIR=str(TEST_ROOT / "imports"),
        KNOWFLOW_SECRET_KEY="skill-api-test",
        KNOWFLOW_VECTOR_BACKEND="local",
    )
    sys.path.insert(0, str(BACKEND))
    for name in list(sys.modules):
        if name == "main" or name.startswith("knowflow"):
            sys.modules.pop(name, None)
    app = importlib.import_module("main").app
    runtime = importlib.import_module("knowflow.runtime")
    builtin_test_root = TEST_ROOT / "builtin-containment"
    normal_builtin = builtin_test_root / "normal"
    escaped_builtin = builtin_test_root / "zz-escaped"
    unreadable_builtin = builtin_test_root / "zz-unreadable"
    external_directory = TEST_ROOT / "external-builtin-target"
    normal_builtin.mkdir(parents=True)
    escaped_builtin.mkdir(parents=True)
    unreadable_builtin.mkdir(parents=True)
    external_directory.mkdir()
    (normal_builtin / "SKILL.md").write_text(
        "---\n"
        "name: sync-contained-normal\n"
        "description: A contained builtin Skill.\n"
        "---\n"
        "Use only files in the builtin root.\n",
        encoding="utf-8",
    )
    (escaped_builtin / "SKILL.md").write_text(
        "---\n"
        "name: sync-escaped-entry\n"
        "description: This simulated entry resolves outside.\n"
        "---\n"
        "This entry must not be synchronized.\n",
        encoding="utf-8",
    )
    unreadable_manifest = unreadable_builtin / "SKILL.md"
    unreadable_manifest.write_text(
        "---\n"
        "name: sync-unreadable-entry\n"
        "description: This simulated manifest cannot be read.\n"
        "---\n"
        "This entry must not stop builtin synchronization.\n",
        encoding="utf-8",
    )
    external_marker = external_directory / "outside.txt"
    external_marker.write_text("external data", encoding="utf-8")
    real_resolve = Path.resolve
    real_read_bytes = Path.read_bytes
    escaped_resolved = real_resolve(escaped_builtin)
    external_resolved = real_resolve(external_directory)
    unreadable_resolved = real_resolve(unreadable_manifest)

    def simulate_builtin_escape(path: Path, *args, **kwargs) -> Path:
        resolved = real_resolve(path, *args, **kwargs)
        if resolved == escaped_resolved:
            return external_resolved
        return resolved

    def simulate_unreadable_manifest(path: Path) -> bytes:
        if real_resolve(path) == unreadable_resolved:
            raise PermissionError("simulated unreadable builtin manifest")
        return real_read_bytes(path)

    original_builtin_dir = runtime.skills.builtin_dir
    runtime.skills.builtin_dir = builtin_test_root
    Path.resolve = simulate_builtin_escape
    Path.read_bytes = simulate_unreadable_manifest
    try:
        runtime.skills.sync_builtins()
        runtime.skills.sync_builtins()
    finally:
        Path.read_bytes = real_read_bytes
        Path.resolve = real_resolve
        runtime.skills.builtin_dir = original_builtin_dir
    synced_builtins = runtime.fetch_all(
        """
        SELECT slug, package_path FROM skill_package
        WHERE slug IN (
          'sync-contained-normal',
          'sync-escaped-entry',
          'sync-unreadable-entry'
        )
        ORDER BY slug
        """
    )
    assert synced_builtins == [
        {
            "slug": "sync-contained-normal",
            "package_path": "normal",
        }
    ], synced_builtins
    assert runtime.fetch_one(
        """
        SELECT COUNT(*) AS count FROM skill_package
        WHERE slug='sync-contained-normal'
        """
    )["count"] == 1
    assert external_marker.read_text(encoding="utf-8") == "external data"
    assert str(external_resolved) not in str(synced_builtins)
    runtime.execute(
        """
        DELETE FROM skill_package
        WHERE slug IN (
          'sync-contained-normal',
          'sync-escaped-entry',
          'sync-unreadable-entry'
        )
        """
    )

    alice = TestClient(app)
    bob = TestClient(app)
    register(alice, "skill-api-alice")
    register(bob, "skill-api-bob")
    runtime.skills.sync_builtins()

    alice_personal = install_upload(
        alice,
        archive("alice-private", "Only Alice can see this."),
    )
    bob_personal = install_upload(
        bob,
        archive("bob-private", "Only Bob can see this."),
    )
    stored_package = runtime.fetch_one(
        "SELECT package_path FROM skill_package WHERE id=:id",
        {"id": alice_personal["id"]},
    )
    runtime.execute(
        "UPDATE skill_package SET package_path='foo/..' WHERE id=:id",
        {"id": alice_personal["id"]},
    )
    guarded_alice = TestClient(app, raise_server_exceptions=False)
    guarded_alice.cookies.update(alice.cookies)
    for guarded_url in (
        "/api/skills",
        f"/api/skills/{alice_personal['id']}",
        f"/api/skills/{alice_personal['id']}/content",
    ):
        guarded = guarded_alice.get(guarded_url)
        assert guarded.status_code == 400, (guarded_url, guarded.text)
        assert guarded.json()["code"] == "skill_invalid_path"
        assert str(TEST_ROOT) not in guarded.text
    runtime.execute(
        "UPDATE skill_package SET package_path=:package_path WHERE id=:id",
        {
            "package_path": stored_package["package_path"],
            "id": alice_personal["id"],
        },
    )
    assert (TEST_ROOT / "skills").is_dir()
    assert (TEST_ROOT / "skills" / stored_package["package_path"]).is_dir()

    alice_items = alice.get("/api/skills").json()["data"]
    bob_items = bob.get("/api/skills").json()["data"]
    assert {item["slug"] for item in alice_items} == {
        "alice-private",
        "deep-research",
        "notion-research",
    }
    assert {item["slug"] for item in bob_items} == {
        "bob-private",
        "deep-research",
        "notion-research",
    }
    assert all(
        item["scriptsExecutable"] is False
        for item in alice_items + bob_items
    )

    wrong_id = alice_personal["id"]
    wrong_owner_calls = (
        bob.get(f"/api/skills/{wrong_id}"),
        bob.get(f"/api/skills/{wrong_id}/content"),
        bob.patch(f"/api/skills/{wrong_id}", json={"enabled": False}),
        bob.post(f"/api/skills/{wrong_id}/check-update"),
        bob.post(f"/api/skills/{wrong_id}/update", json={"enabled": False}),
        bob.delete(f"/api/skills/{wrong_id}"),
    )
    assert all(response.status_code == 404 for response in wrong_owner_calls)

    alice_builtins = {
        item["slug"]: item for item in alice.get("/api/skills").json()["data"]
    }
    bob_builtins = {
        item["slug"]: item for item in bob.get("/api/skills").json()["data"]
    }
    deep_alice = alice_builtins["deep-research"]
    deep_bob = bob_builtins["deep-research"]
    assert deep_alice["enabled"] is False
    assert deep_bob["enabled"] is False
    missing_dependency = alice.patch(
        f"/api/skills/{deep_alice['id']}",
        json={"enabled": True},
    )
    assert missing_dependency.status_code == 409, missing_dependency.text
    assert missing_dependency.json()["code"] == "skill_dependency_unavailable"
    configured = alice.put(
        "/api/tool-configs/web_search",
        json={"enabled": True, "apiKey": "test-key"},
    )
    assert configured.status_code == 200, configured.text
    enabled = alice.patch(
        f"/api/skills/{deep_alice['id']}",
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["enabled"] is True
    assert bob.get(f"/api/skills/{deep_bob['id']}").json()["data"]["enabled"] is False
    cannot_delete_builtin = alice.delete(f"/api/skills/{deep_alice['id']}")
    assert cannot_delete_builtin.status_code == 409

    content = alice.get(f"/api/skills/{wrong_id}/content")
    assert content.status_code == 200, content.text
    assert content.headers["content-type"].startswith("application/json")
    assert content.json()["data"]["content"].startswith("---\n")
    assert "<script" not in content.json()["data"]["content"].lower()
    assert "scripts/helper.py" not in content.text

    package_id = alice.get(f"/api/skills/{wrong_id}").json()["data"]["packageId"]
    unsupported_update = alice.post(
        f"/api/skills/{wrong_id}/update",
        json={"enabled": False},
    )
    assert unsupported_update.status_code == 409
    assert (
        alice.get(f"/api/skills/{wrong_id}").json()["data"]["packageId"]
        == package_id
    )

    guarded_delete = install_upload(
        alice,
        archive("delete-root-guard", "Delete must preserve the root."),
    )
    bob_package_path = runtime.fetch_one(
        "SELECT package_path FROM skill_package WHERE id=:id",
        {"id": bob_personal["id"]},
    )["package_path"]
    runtime.execute(
        "UPDATE skill_package SET package_path='foo/..' WHERE id=:id",
        {"id": guarded_delete["id"]},
    )
    skill_root_sentinel = runtime.skills.skill_dir / "delete-root-sentinel.txt"
    skill_root_sentinel.write_text("keep skill root", encoding="utf-8")
    deleted_guard = alice.delete(f"/api/skills/{guarded_delete['id']}")
    assert deleted_guard.status_code == 200, deleted_guard.text
    assert skill_root_sentinel.read_text(encoding="utf-8") == "keep skill root"
    assert (runtime.skills.skill_dir / bob_package_path).is_dir()

    original_cleanup = runtime.skills._cleanup_personal_package
    runtime.skills._cleanup_personal_package = lambda *args: (_ for _ in ()).throw(
        OSError("cleanup failed")
    )
    deleted = alice.delete(f"/api/skills/{wrong_id}")
    runtime.skills._cleanup_personal_package = original_cleanup
    assert deleted.status_code == 200, deleted.text
    assert alice.get(f"/api/skills/{wrong_id}").status_code == 404
    assert runtime.fetch_one(
        "SELECT id FROM user_skill WHERE user_id=1 AND skill_slug='alice-private'"
    ) is None

    assert bob.get(f"/api/skills/{bob_personal['id']}").status_code == 200
    print("per-user Skill management API checks passed")


if __name__ == "__main__":
    main()
