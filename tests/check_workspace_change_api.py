from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    with TemporaryDirectory(prefix="knowflow-workspace-change-") as temp_dir:
        temp_root = Path(temp_dir)
        db_path = temp_root / "workspace-change-api.db"
        workspace_root = temp_root / "workspaces"
        os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["KNOWFLOW_SECRET_KEY"] = "workspace-change-api-secret"
        os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
        os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
        os.environ["KNOWFLOW_WORKSPACE_ENABLED"] = "1"
        os.environ["KNOWFLOW_WORKSPACE_DIR"] = str(workspace_root)
        sys.path.insert(0, str(BACKEND))

        app_module = importlib.import_module("main")
        runtime = importlib.import_module("knowflow.runtime")
        workspace_service = importlib.import_module(
            "knowflow.services.workspace_runtime"
        )
        client = TestClient(app_module.app)
        registered = client.post(
            "/api/auth/register",
            json={
                "username": "workspace-change-user",
                "email": "workspace-change-user@example.com",
                "password": "123456",
            },
        )
        assert registered.status_code == 200, registered.text
        user = runtime.fetch_one(
            "SELECT id FROM app_user WHERE username=:username",
            {"username": "workspace-change-user"},
        )
        user_id = int(user["id"])
        run = runtime.agent_runs.create_run(
            user_id=user_id,
            session_id="session-workspace-change",
            user_message_id=None,
            goal_summary="修改报告",
            trigger_mode="auto",
            run_id="run_workspace_change",
        )
        runtime.agent_runs.transition_run(user_id, run["id"], "running")
        tracked = workspace_service.tracked_workspace_runtime(
            workspace_root,
            user_id=user_id,
            run_id=run["id"],
        )
        written = tracked.write_text("report.md", "new\n", overwrite=False).output
        runtime.agent_runs.transition_run(user_id, run["id"], "completed")

        diff = client.get(
            "/api/workspace/changes",
            params={"run_id": run["id"], "path": "report.md"},
        )
        assert diff.status_code == 200, diff.text
        assert "+new" in diff.json()["data"]["patch"]

        undo = client.post(
            "/api/workspace/changes/undo",
            json={"runId": run["id"], "operationId": written["operationId"]},
        )
        assert undo.status_code == 200, undo.text
        assert undo.json()["data"]["artifact"]["reverted"] is True
        assert not (tracked.root / "report.md").exists()

        repeat = client.post(
            "/api/workspace/changes/undo",
            json={"runId": run["id"], "operationId": written["operationId"]},
        )
        assert repeat.status_code == 409, repeat.text
        client.close()
        runtime.db.engine.dispose()

    print("workspace change API keeps run ownership and conflict-safe undo")


if __name__ == "__main__":
    main()
