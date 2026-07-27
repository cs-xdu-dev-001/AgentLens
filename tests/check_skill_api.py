from __future__ import annotations

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
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)
    TEST_ROOT.mkdir(parents=True)
    os.environ.update(
        KNOWFLOW_DB_URL=f"sqlite:///{(TEST_ROOT / 'db.sqlite').as_posix()}",
        KNOWFLOW_SKILL_DIR=str(TEST_ROOT / "skills"),
        KNOWFLOW_SKILL_IMPORT_DIR=str(TEST_ROOT / "imports"),
        KNOWFLOW_SECRET_KEY="skill-api-test",
        KNOWFLOW_COOKIE_SECURE="0",
        KNOWFLOW_VECTOR_BACKEND="local",
    )
    sys.path.insert(0, str(BACKEND))
    for name in list(sys.modules):
        if name == "main" or name.startswith("knowflow"):
            sys.modules.pop(name, None)
    app = importlib.import_module("main").app
    runtime = importlib.import_module("knowflow.runtime")
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
