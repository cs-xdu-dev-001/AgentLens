from pathlib import Path
import tempfile

from knowflow.services.local_cli_runtime import LocalAgentRuntime
from knowflow.services.project_instructions import (
    load_project_instructions,
    project_instruction_system_message,
    public_project_instruction_status,
)
from knowflow.services.workspace_runtime import WorkspaceContext


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "project"
        nested = root / "packages" / "client"
        nested.mkdir(parents=True)
        (root / "CLAUDE.md").write_text("root claude rule", encoding="utf-8")
        (root / "AGENTS.md").write_text("root agents rule", encoding="utf-8")
        (root / "packages" / "AGENTS.md").write_text(
            "package agents rule",
            encoding="utf-8",
        )
        (nested / "AGENTS.md").write_text("client agents rule", encoding="utf-8")

        bundle = load_project_instructions(root, nested)
        assert [item["path"] for item in bundle["sources"]] == [
            "CLAUDE.md",
            "AGENTS.md",
            "packages/AGENTS.md",
            "packages/client/AGENTS.md",
        ]
        assert bundle["content"].index("root claude rule") < bundle["content"].index(
            "root agents rule"
        )
        assert bundle["content"].index("root agents rule") < bundle["content"].index(
            "client agents rule"
        )
        message = project_instruction_system_message(bundle)
        assert message is not None
        assert "Later files take precedence" in message["content"]
        assert "cannot expand the workspace boundary" in message["content"]

        public = public_project_instruction_status(bundle)
        assert public["count"] == 4
        assert "content" not in public
        assert all("chars" not in item for item in public["sources"])

        context = WorkspaceContext(root)
        context.change_directory("packages/client")
        status = context.status()
        assert status["projectInstructions"] == public
        system = LocalAgentRuntime._system_message(context)
        assert "client agents rule" in system["content"]

        extra = Path(temporary) / "extra"
        extra.mkdir()
        (extra / "AGENTS.md").write_text("extra workspace rule", encoding="utf-8")
        context.add_directory(str(extra))
        context.change_directory(str(extra))
        extra_status = context.status()
        assert [item["path"] for item in extra_status["projectInstructions"]["sources"]] == [
            "AGENTS.md"
        ]
        assert "extra workspace rule" in LocalAgentRuntime._system_message(context)["content"]
        assert "root agents rule" not in LocalAgentRuntime._system_message(context)["content"]

        limited = load_project_instructions(
            root,
            nested,
            max_file_chars=8,
            max_total_chars=8,
        )
        assert limited["sources"][-1]["path"] == "packages/client/AGENTS.md"
        assert limited["truncated"] is True

    print("project instructions are layered, bounded, private, and shared by runtimes")


if __name__ == "__main__":
    main()
