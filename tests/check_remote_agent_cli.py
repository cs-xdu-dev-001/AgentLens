from __future__ import annotations

from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from typer.testing import CliRunner  # noqa: E402
from knowflow import cli  # noqa: E402
from knowflow.services.agent_application import AgentExecution  # noqa: E402
from knowflow.services.remote_agent import (  # noqa: E402
    RemoteAgentClient,
    RemoteAgentError,
    RemoteProfileStore,
    iter_sse,
    normalize_server_url,
)


class FakeCookies:
    def __init__(self, token: str = ""):
        self.token = token

    def get(self, name: str):
        assert name == "knowflow_session"
        return self.token


class FakeResponse:
    def __init__(self, payload, *, lines=None, status=200):
        self.payload = payload
        self.lines = lines or []
        self.status_code = status
        self.ok = 200 <= status < 300

    def json(self):
        return self.payload

    def iter_lines(self, decode_unicode=True):
        assert decode_unicode
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class FakeSession:
    def __init__(self):
        self.cookies = FakeCookies("session-secret")
        self.calls = []
        self.responses = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def main() -> None:
    assert normalize_server_url("https://knowflow.example/") == (
        "https://knowflow.example"
    )
    assert normalize_server_url("http://127.0.0.1:8010") == (
        "http://127.0.0.1:8010"
    )
    try:
        normalize_server_url("http://knowflow.example")
    except ValueError:
        pass
    else:
        raise AssertionError("insecure remote URL accepted")
    try:
        normalize_server_url("https://knowflow.example/prefix")
    except ValueError:
        pass
    else:
        raise AssertionError("server URL path accepted")

    generic_error = RemoteAgentClient._error(FakeResponse({}, status=503))
    assert isinstance(generic_error, RemoteAgentError)
    assert generic_error.code == "http_503"
    assert "HTTP 503" in str(generic_error)

    with patch.object(cli.profile_store, "load", return_value=None):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KNOWFLOW_CLI_SERVER", None)
            try:
                cli._remote_client(None, local=False, remote=True)
            except Exception as exc:
                assert isinstance(exc, cli.typer.BadParameter)
                assert "auth login" in str(exc)
            else:
                raise AssertionError(
                    "missing remote profile silently fell back to local mode"
                )
            assert cli._remote_client(None, local=True) is None
            assert cli._remote_client(
                None,
                local=False,
                remote=False,
            ) is None

            class FakeExtensions:
                @staticmethod
                def list_skills():
                    return []

                @staticmethod
                def list_mcp():
                    return []

                @staticmethod
                def memory_provider():
                    return None

            class FakeLocalCatalog:
                extensions = FakeExtensions()

                @staticmethod
                def tool_schemas():
                    return [
                        {
                            "function": {
                                "name": "web_search",
                            }
                        }
                    ]

            with patch.object(
                cli,
                "_local_agent",
                return_value=FakeLocalCatalog(),
            ):
                for command in (
                    ["tools", "list"],
                    ["skills", "list"],
                    ["mcp", "list"],
                    ["memory", "list"],
                ):
                    response = CliRunner().invoke(cli.app, command)
                    assert response.exit_code == 0, (
                        command,
                        response.output,
                    )

            response = CliRunner().invoke(
                cli.app,
                ["tools", "list", "--remote"],
            )
            assert response.exit_code != 0
            assert "auth login" in response.output

            class FakeLocal:
                def run(self, task, *, tools, event_sink):
                    assert task == "local task"
                    return AgentExecution(
                        result={
                            "paused": False,
                            "answer": "local done",
                            "runId": "run_local",
                        }
                    )

            with patch.object(
                cli,
                "_runtime",
                side_effect=AssertionError("local runtime must stay lazy"),
            ), patch.object(
                cli,
                "_local_agent",
                return_value=FakeLocal(),
            ) as local_agent:
                response = CliRunner().invoke(
                    cli.app,
                    ["run", "local task"],
                )
            assert response.exit_code == 0, response.output
            local_agent.assert_called_once()

    events = list(
        iter_sse(
            [
                ": keepalive",
                "",
                "event: message",
                'data: {"content":',
                'data: "你好"}',
                "",
                "event: done",
                'data: {"runId":"run_remote"}',
                "",
            ]
        )
    )
    assert events == [
        {"content": "你好", "type": "message"},
        {"runId": "run_remote", "type": "done"},
    ]

    fake = FakeSession()
    fake.responses.append(
        FakeResponse(
            {
                "code": 0,
                "data": {"user": {"username": "alice"}},
            }
        )
    )
    client = RemoteAgentClient(
        "https://knowflow.example",
        session=fake,
    )
    login = client.login("alice", "not-stored")
    assert login["user"]["username"] == "alice"
    assert client.token == "session-secret"
    assert "Authorization" not in fake.calls[0][2]["headers"]
    assert fake.calls[0][2]["headers"]["User-Agent"] == "AgentLens-CLI"

    fake.responses.append(
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "deviceCode": "device-secret-value",
                    "userCode": "ABCDE-23456",
                    "verificationUri": "https://knowflow.example/?page=cli-auth",
                },
            }
        )
    )
    started = client.start_device_authorization()
    assert started["userCode"] == "ABCDE-23456"
    fake.responses.append(
        FakeResponse(
            {
                "code": 0,
                "data": {
                    "status": "authorized",
                    "sessionToken": "browser-session",
                    "user": {"username": "alice"},
                },
            }
        )
    )
    authorized = client.poll_device_authorization("device-secret-value")
    assert authorized["status"] == "authorized"
    assert client.token == "browser-session"

    fake.responses.append(
        FakeResponse(
            {},
            lines=[
                "event: run_snapshot",
                'data: {"run":{"id":"run_remote","status":"running"}}',
                "",
                "event: message",
                'data: {"content":"完成"}',
                "",
                "event: done",
                'data: {"runId":"run_remote","sessionId":"s1"}',
                "",
            ],
        )
    )
    execution = client.run({"question": "测试"})
    assert execution.result["answer"] == "完成"
    assert execution.result["runId"] == "run_remote"
    assert not execution.paused
    assert fake.calls[-1][2]["headers"]["Authorization"] == (
        "Bearer browser-session"
    )

    fake.responses.append(
        FakeResponse({"code": 0, "data": {"id": "s1", "title": "发布复盘"}})
    )
    renamed = client.rename_session("s1", "发布复盘")
    assert renamed["title"] == "发布复盘"
    assert fake.calls[-1][0] == "PUT"
    assert fake.calls[-1][1].endswith("/api/sessions/s1")
    assert fake.calls[-1][2]["json"] == {"title": "发布复盘"}

    fake.responses.append(FakeResponse({"code": 0, "data": True}))
    assert client.delete_session("s1") is True
    assert fake.calls[-1][0] == "DELETE"
    assert fake.calls[-1][1].endswith("/api/sessions/s1")

    cancelled_execution = RemoteAgentClient._collect(
        iter(
            [
                {
                    "type": "run_snapshot",
                    "run": {"id": "run_cancelled", "status": "running"},
                },
                {
                    "type": "cancelled",
                    "run": {"id": "run_cancelled", "status": "cancelled"},
                },
            ]
        ),
        None,
    )
    assert cancelled_execution.result["cancelled"] is True
    assert cancelled_execution.result["runId"] == "run_cancelled"

    with TemporaryDirectory() as folder:
        store = RemoteProfileStore(Path(folder) / "remote.json")
        store.save(
            {
                "server": "https://knowflow.example",
                "token": "secret",
            }
        )
        assert store.load()["token"] == "secret"
        if os.name != "nt":
            assert store.path.stat().st_mode & 0o777 == 0o600
        store.clear()
        assert store.load() is None

    class FakeRemote:
        def run(self, payload, event_sink):
            assert payload["question"] == "remote task"
            event_sink({"type": "done", "runId": "run_remote"})
            return AgentExecution(
                result={
                    "paused": False,
                    "answer": "remote done",
                    "runId": "run_remote",
                }
            )

    with patch.object(cli, "_remote_client", return_value=FakeRemote()):
        response = CliRunner().invoke(
            cli.app,
            ["run", "remote task", "--events", "--remote"],
        )
    assert response.exit_code == 0, response.output
    assert '"runId": "run_remote"' in response.output

    print("remote agent cli checks passed")


if __name__ == "__main__":
    main()
