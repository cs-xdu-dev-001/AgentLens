import importlib
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    if TestClient is None:
        print("skipped: fastapi test client is not installed in this interpreter")
        return
    db_path = ROOT / "data" / "test-dbs" / "auth-test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "auth-flow-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_BASE_URL"] = "http://127.0.0.1:8010"
    os.environ["KNOWFLOW_OAUTH_RETURN_ORIGINS"] = "http://127.0.0.1:5173"
    os.environ["KNOWFLOW_GITHUB_CLIENT_ID"] = "test-client"
    os.environ["KNOWFLOW_GITHUB_CLIENT_SECRET"] = "test-secret"
    sys.path.insert(0, str(BACKEND))
    main_module = importlib.import_module("main")
    client = TestClient(main_module.app)

    locked = client.get("/api/model-configs")
    assert locked.status_code == 401, locked.text

    missing_login = client.post("/api/auth/login", json={"account": "missing", "password": "123456"})
    assert missing_login.status_code == 401, missing_login.text
    missing_body = missing_login.json()
    assert missing_body["code"] == 40102, missing_body
    assert "Account not found" in missing_body["message"], missing_body

    invalid_register = client.post(
        "/api/auth/register",
        json={"username": "x", "email": "bad-email", "password": "123", "displayName": "Bad"},
    )
    assert invalid_register.status_code == 422, invalid_register.text
    invalid_body = invalid_register.json()
    assert invalid_body["code"] == 42200, invalid_body
    assert "parameter error" in invalid_body["message"].lower(), invalid_body

    registered = client.post(
        "/api/auth/register",
        json={"username": "tester", "email": "tester@example.com", "password": "123456", "displayName": "Tester"},
    )
    assert registered.status_code == 200, registered.text
    assert "knowflow_session" in registered.headers.get("set-cookie", "")
    assert registered.json()["data"]["user"]["username"] == "tester"

    device_client = TestClient(main_module.app)
    device_started = device_client.post(
        "/api/auth/cli/device",
        json={"clientName": "KnowFlow CLI test"},
    )
    assert device_started.status_code == 200, device_started.text
    device_data = device_started.json()["data"]
    assert device_data["verificationUri"].startswith(
        "http://127.0.0.1:8010/?page=cli-auth&userCode="
    )
    unauthenticated_decision = device_client.post(
        "/api/auth/cli/device/decision",
        json={"userCode": device_data["userCode"], "decision": "approve"},
    )
    assert unauthenticated_decision.status_code == 401
    pending = device_client.post(
        "/api/auth/cli/device/token",
        json={"deviceCode": device_data["deviceCode"]},
    )
    assert pending.json()["data"]["status"] == "pending"
    approved = client.post(
        "/api/auth/cli/device/decision",
        json={"userCode": device_data["userCode"], "decision": "approve"},
    )
    assert approved.status_code == 200, approved.text
    authorized = device_client.post(
        "/api/auth/cli/device/token",
        json={"deviceCode": device_data["deviceCode"]},
    )
    assert authorized.status_code == 200, authorized.text
    authorized_data = authorized.json()["data"]
    assert authorized_data["status"] == "authorized"
    assert authorized_data["sessionToken"]
    cli_me = device_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {authorized_data['sessionToken']}"},
    )
    assert cli_me.json()["data"]["user"]["username"] == "tester"
    replayed = device_client.post(
        "/api/auth/cli/device/token",
        json={"deviceCode": device_data["deviceCode"]},
    )
    assert replayed.json()["data"]["status"] == "consumed"

    wrong_password = client.post("/api/auth/login", json={"account": "tester", "password": "bad-password"})
    assert wrong_password.status_code == 401, wrong_password.text
    wrong_body = wrong_password.json()
    assert wrong_body["code"] == 40103, wrong_body
    assert "Incorrect password" in wrong_body["message"], wrong_body

    me = client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["data"]["authenticated"] is True

    unlocked = client.get("/api/model-configs")
    assert unlocked.status_code == 200, unlocked.text

    session_token = client.cookies.get("knowflow_session")
    bearer_client = TestClient(main_module.app)
    bearer_me = bearer_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert bearer_me.status_code == 200, bearer_me.text
    assert bearer_me.json()["data"]["authenticated"] is True
    bearer_logout = bearer_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert bearer_logout.status_code == 200, bearer_logout.text
    revoked = client.get("/api/model-configs")
    assert revoked.status_code == 401, revoked.text

    logged_in_again = client.post(
        "/api/auth/login",
        json={"account": "tester", "password": "123456"},
    )
    assert logged_in_again.status_code == 200, logged_in_again.text

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200, logout.text

    locked_again = client.get("/api/model-configs")
    assert locked_again.status_code == 401, locked_again.text

    class FakeGitHubResponse:
        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_post(url, **kwargs):
        assert url == "https://github.com/login/oauth/access_token", url
        assert kwargs["data"]["redirect_uri"] == "http://127.0.0.1:8010/api/auth/oauth/github/callback"
        return FakeGitHubResponse({"access_token": "test-token"})

    def fake_get(url, **kwargs):
        if url == "https://api.github.com/user":
            return FakeGitHubResponse({"id": 42, "login": "github-user", "name": "GitHub User", "avatar_url": ""})
        if url == "https://api.github.com/user/emails":
            return FakeGitHubResponse([{"email": "github@example.com", "primary": True, "verified": True}])
        raise AssertionError(f"unexpected GitHub URL: {url}")

    auth_router = importlib.import_module("knowflow.routers.auth")
    auth_router.requests.post = fake_post
    auth_router.requests.get = fake_get

    frontend_url = "http://127.0.0.1:5173/"
    runtime = importlib.import_module("knowflow.runtime")
    assert runtime.is_allowed_oauth_return_url(frontend_url)
    assert not runtime.is_allowed_oauth_return_url("http://127.0.0.1:5174/capture")
    oauth_start = client.get(f"/api/auth/oauth/github/start?returnTo={frontend_url}", follow_redirects=False)
    assert oauth_start.status_code == 307, oauth_start.text
    oauth_location = oauth_start.headers["location"]
    query = parse_qs(urlparse(oauth_location).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8010/api/auth/oauth/github/callback"], query
    oauth_callback = client.get(
        f"/api/auth/oauth/github/callback?code=ok&state={query['state'][0]}",
        follow_redirects=False,
    )
    assert oauth_callback.status_code == 307, oauth_callback.text
    assert oauth_callback.headers["location"] == frontend_url, oauth_callback.headers["location"]
    assert "knowflow_session" in oauth_callback.headers.get("set-cookie", "")


if __name__ == "__main__":
    main()
