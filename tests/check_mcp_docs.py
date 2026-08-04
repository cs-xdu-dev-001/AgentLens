import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    requirements = read("backend/requirements.txt")
    assert "mcp==1.28.1" in requirements, "MCP SDK must stay pinned"

    env_example = read("backend/.env.example")
    variables = {
        "KNOWFLOW_MCP_CONNECT_TIMEOUT": "10",
        "KNOWFLOW_MCP_REQUEST_TIMEOUT": "30",
        "KNOWFLOW_MCP_APPROVAL_TIMEOUT": "300",
        "KNOWFLOW_MCP_MAX_RESPONSE_BYTES": "1048576",
        "KNOWFLOW_MCP_MAX_EXPOSED_TOOLS": "32",
        "KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS": "0",
    }
    for name, value in variables.items():
        assert f"{name}={value}" in env_example, f"missing {name}"

    start_script = read("start-dev.cmd")
    assert (
        "%KNOWFLOW_BASE_URL%/api/mcp/oauth/callback" in start_script
    ), "startup check must print the MCP OAuth callback"

    readme = read("README.md")
    for token, label in (
        ("https://mcp.notion.com/mcp", "Notion endpoint"),
        ("user OAuth", "per-user OAuth"),
        ("Streamable HTTP", "custom MCP transport"),
        ("No authentication", "no-auth option"),
        ("Static headers", "static-header option"),
        ("automatically", "automatic read operations"),
        ("approval", "write approval"),
        ("one backend worker", "process-local run coordinator limit"),
        ("test page", "safe Notion smoke test"),
    ):
        assert token in readme, f"missing README {label}: {token}"

    joined = "\n".join((env_example, start_script, readme))
    forbidden = (
        r"ntn_[A-Za-z0-9_-]{12,}",
        r"tvly-[A-Za-z0-9_-]{12,}",
        r"Bearer\s+[A-Za-z0-9._-]{20,}",
    )
    for pattern in forbidden:
        assert not re.search(pattern, joined, re.IGNORECASE), (
            f"credential-like value found: {pattern}"
        )
    print("MCP documentation and safe example configuration are complete")


if __name__ == "__main__":
    main()
