from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "123456"},
    )
    assert response.status_code == 200, response.text


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "tool-config.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "tool-config-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    tool_config_router = importlib.import_module("knowflow.routers.tool_configs")

    class FakeProvider:
        def search(self, query: str, top_k: int = 5):
            assert query == "AgentLens connectivity check"
            assert top_k == 1
            return [{"title": "AgentLens", "url": "https://example.com"}]

    tool_config_router.make_web_search_provider = lambda api_key: FakeProvider()
    alice = TestClient(app_module.app)
    bob = TestClient(app_module.app)
    register(alice, "tool-alice")
    register(bob, "tool-bob")

    saved = alice.put(
        "/api/tool-configs/web_search",
        json={"enabled": True, "apiKey": "unit-test-secret"},
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["toolName"] == "web_search"
    assert data["provider"] == "tavily"
    assert data["enabled"] is True
    assert data["configured"] is True
    assert "unit-test-secret" not in str(data)

    row = runtime.fetch_one("SELECT * FROM tool_config WHERE tool_name='web_search'")
    assert row["api_key_cipher"] != "unit-test-secret"
    assert runtime.cipher.decrypt(row["api_key_cipher"]) == "unit-test-secret"
    assert bob.get("/api/tool-configs").json()["data"] == []

    retained = alice.put(
        "/api/tool-configs/web_search",
        json={"enabled": False, "apiKey": ""},
    ).json()["data"]
    assert retained["configured"] is True
    current = runtime.fetch_one(
        "SELECT api_key_cipher FROM tool_config WHERE id=:id",
        {"id": row["id"]},
    )
    assert runtime.cipher.decrypt(current["api_key_cipher"]) == "unit-test-secret"

    checked = alice.post("/api/tool-configs/web_search/test")
    assert checked.status_code == 200, checked.text
    assert checked.json()["data"]["resultCount"] == 1
    assert "1 credit" in checked.json()["data"]["message"]
    assert bob.post("/api/tool-configs/web_search/test").status_code == 400

    missing_key = bob.put(
        "/api/tool-configs/web_search",
        json={"enabled": True, "apiKey": ""},
    )
    assert missing_key.status_code == 400, missing_key.text

    assert alice.delete("/api/tool-configs/web_search").status_code == 200
    assert alice.get("/api/tool-configs").json()["data"] == []
    assert bob.delete("/api/tool-configs/web_search").status_code == 200
    print("tool configurations are encrypted and isolated per user")


if __name__ == "__main__":
    main()
