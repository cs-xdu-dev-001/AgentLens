import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "backend" / ".env.example"
README = ROOT / "README.md"
GITIGNORE = ROOT / ".gitignore"

EXPECTED_ENV = {
    "KNOWFLOW_SKILL_DIR": "./data/skills",
    "KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES": "5242880",
    "KNOWFLOW_SKILL_MAX_EXTRACTED_BYTES": "20971520",
    "KNOWFLOW_SKILL_MAX_FILES": "200",
    "KNOWFLOW_SKILL_MAX_FILE_BYTES": "2097152",
    "KNOWFLOW_SKILL_MAX_DEPTH": "8",
    "KNOWFLOW_SKILL_MAX_BODY_CHARS": "50000",
    "KNOWFLOW_SKILL_IMPORT_TTL": "900",
    "KNOWFLOW_SKILL_GITHUB_TIMEOUT": "15",
}


def require_all(text: str, needles: list[str], label: str) -> None:
    missing = [needle for needle in needles if needle.lower() not in text.lower()]
    assert not missing, f"{label} is missing: {missing}"


def check_env_example() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assignments = dict(
        re.findall(r"^([A-Z][A-Z0-9_]*)=([^\r\n]*)$", text, flags=re.MULTILINE)
    )
    for name, expected in EXPECTED_ENV.items():
        assert assignments.get(name) == expected, (
            f"{name} must use the safe documented default {expected!r}"
        )
    require_all(
        text,
        ["per-user packages", "scripts/", "stored", "inspected", "never executed"],
        "backend/.env.example Skill safety comments",
    )


def check_readme() -> None:
    text = README.read_text(encoding="utf-8")
    require_all(
        text,
        [
            "SKILL.md",
            "name:",
            "description:",
            "metadata:",
            "knowflow:",
            "display_name:",
            "version:",
            "required_tools:",
            "required_mcp:",
            "GitHub",
            "ZIP",
            "preview",
            "install",
            "https",
            "github.com",
            "scripts/",
            "不会执行",
            "per-user",
            "builtin",
            "default",
            "one Skill",
            "Agent run",
            "`/`",
            "auto-activate",
            "enabled",
            "tool",
            "MCP",
            "approval",
            "UTF-8",
            "references/",
            "database",
            "data/skills",
            "backup",
            "write permission",
            "persistent volume",
            "data/skill-imports",
            "checks",
            "build",
            "Git",
            "backend/.env.example",
        ],
        "README Skill documentation",
    )
    limit_terms = [
        "archive",
        "extracted",
        "files",
        "file size",
        "depth",
        "body",
        "TTL",
        "timeout",
    ]
    require_all(text, limit_terms, "README Skill import limits")


def check_gitignore() -> None:
    lines = {
        line.strip().replace("\\", "/")
        for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    expected = {
        "data/skills/",
        "data/skill-imports/",
        "data/tool-results/",
        "backend/data/skills/",
        "backend/data/skill-imports/",
        "data/workspaces/",
    }
    assert expected <= lines, f".gitignore is missing: {sorted(expected - lines)}"
    assert not any("builtin_skills" in line for line in lines), (
        "builtin_skills source must not be ignored"
    )


def secret_findings(text: str) -> list[str]:
    findings = []
    token_patterns = {
        "GitHub classic token": r"\bgh[opsu]_[A-Za-z0-9]{30,}\b",
        "GitHub fine-grained token": r"\bgithub_pat_[A-Za-z0-9_]{40,}\b",
        "OpenAI-style secret": r"\bsk-[A-Za-z0-9_-]{20,}\b",
        "AWS access key": r"\bAKIA[A-Z0-9]{16}\b",
        "private key": r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    }
    findings.extend(
        label for label, pattern in token_patterns.items() if re.search(pattern, text)
    )

    sensitive_name = re.compile(
        r"(?:^|_)(?:SECRET|TOKEN|API_KEY|PASSWORD|PRIVATE_KEY|ACCESS_KEY)(?:_|$)"
    )
    assignment = re.compile(
        r"^\s*(?:(?:export|set)\s+|\$env:)?([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$",
        flags=re.MULTILINE,
    )
    placeholders = (
        "your_",
        "your-",
        "change-",
        "replace-",
        "example",
        "placeholder",
        "redacted",
        "<",
        "${",
        "***",
    )
    for name, raw_value in assignment.findall(text):
        if not sensitive_name.search(name):
            continue
        value = raw_value.strip().strip("`\"'").strip()
        if not value or value.lower().startswith(placeholders):
            continue
        findings.append(f"non-placeholder value assigned to {name}")
    return findings


def check_document_examples_for_secrets() -> None:
    docs = "\n".join(
        [
            ENV_EXAMPLE.read_text(encoding="utf-8"),
            README.read_text(encoding="utf-8"),
        ]
    )
    assert secret_findings("KNOWFLOW_GITHUB_CLIENT_SECRET=your_client_secret") == []
    secret_value = "release-value-" + "x" * 24
    for assignment in (
        f"KNOWFLOW_API_TOKEN={secret_value}",
        f"export KNOWFLOW_API_TOKEN={secret_value}",
        f"$env:KNOWFLOW_API_TOKEN={secret_value}",
        f"set KNOWFLOW_API_TOKEN={secret_value}",
    ):
        assert secret_findings(
            assignment
        ), "secret scanner must reject non-placeholder credential values"
    for placeholder in (
        "export KNOWFLOW_API_TOKEN=your_token",
        "$env:KNOWFLOW_API_TOKEN=''",
        "set KNOWFLOW_API_TOKEN=",
    ):
        assert secret_findings(placeholder) == []
    offenders = secret_findings(docs)
    assert not offenders, f"documentation contains secret-like values: {offenders}"


def main() -> None:
    check_env_example()
    check_readme()
    check_gitignore()
    check_document_examples_for_secrets()
    print("Skill documentation checks passed")


if __name__ == "__main__":
    main()
