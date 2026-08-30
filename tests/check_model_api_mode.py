from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{Path(tmp, 'api-mode.db').as_posix()}"
        os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
        os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
        app_module = importlib.import_module("knowflow.app")
        client = TestClient(app_module.app)
        assert client.post("/api/auth/register", json={"username": "api-mode", "email": "api-mode@example.com", "password": "123456"}).status_code == 200

        base = {"name": "m", "provider": "openai", "modelType": "chat", "baseUrl": "https://example/v1", "apiKey": "k", "modelName": "x"}
        data = client.post("/api/model-configs", json=base).json()["data"]
        assert data["apiMode"] == "chat_completions"
        created = client.post("/api/model-configs", json={**base, "apiMode": "responses"}).json()["data"]
        cid = created["id"]
        assert client.get(f"/api/model-configs/{cid}").json()["data"]["apiMode"] == "responses"
        updated = client.put(f"/api/model-configs/{cid}", json={"apiMode": "chat_completions"}).json()["data"]
        assert updated["apiMode"] == "chat_completions"
        assert client.put(f"/api/model-configs/{cid}", json={"apiMode": "responses"}).json()["data"]["apiMode"] == "responses"
        assert client.post("/api/model-configs", json={**base, "apiMode": "auto"}).status_code == 400
        assert client.post("/api/model-configs", json={**base, "modelType": "embedding", "apiMode": "responses"}).status_code == 400
        assert client.post("/api/model-configs", json={**base, "modelType": "rerank", "apiMode": "responses"}).status_code == 400
        import knowflow.routers.model_configs as model_configs_router

        original_test = model_configs_router.gateway.test
        try:
            calls = []
            model_configs_router.gateway.test = lambda _config: (
                "unavailable",
                "Responses API connection failed: HTTP 403: upstream_error",
            )
            diagnosed = client.post(f"/api/model-configs/{cid}/test").json()["data"]
            assert diagnosed["status"] == "unavailable"
            assert diagnosed["code"] == "access_denied"
            assert diagnosed["retryable"] is False
            assert len(diagnosed["checkedProtocols"]) == 2
            assert "recommendedApiMode" not in diagnosed

            def protocol_test(config):
                calls.append(config["api_mode"])
                if config["api_mode"] == "chat_completions":
                    return "available", "Chat Completions connection succeeded."
                return (
                    "unavailable",
                    "Responses API connection failed: HTTP 403: upstream_error",
                )

            model_configs_router.gateway.test = protocol_test
            recommended = client.post(
                f"/api/model-configs/{cid}/test"
            ).json()["data"]
            assert calls == ["responses", "chat_completions"]
            assert recommended["status"] == "unavailable"
            assert recommended["recommendedApiMode"] == "chat_completions"
            assert recommended["checkedProtocols"][1]["status"] == "available"
            assert (
                client.get(f"/api/model-configs/{cid}").json()["data"]["apiMode"]
                == "responses"
            )
        finally:
            model_configs_router.gateway.test = original_test
        import knowflow.runtime as runtime
        runtime.db.engine.dispose()


if __name__ == "__main__":
    main()
