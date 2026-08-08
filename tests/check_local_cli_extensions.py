from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry  # noqa: E402
from knowflow.services.agent_tooling import register_mcp_tools  # noqa: E402
from knowflow.services.local_cli_extensions import (  # noqa: E402
    LocalExtensionError,
    LocalExtensionStore,
)
from knowflow.services.local_cli_runtime import (  # noqa: E402
    LocalAgentRuntime,
    LocalCliConfigStore,
)


def main() -> None:
    with TemporaryDirectory() as folder:
        root = Path(folder)
        config = LocalCliConfigStore(root / "config")
        config.save(
            provider="custom",
            base_url="https://gateway.example/v1",
            model_name="agent-model",
            api_mode="responses",
            api_key="model-secret",
        )
        extensions = LocalExtensionStore(config, root / "data")
        extensions.save_web_search(api_key="tavily-secret", enabled=True)
        public_text = config.config_path.read_text(encoding="utf-8")
        private = json.loads(config.credentials_path.read_text(encoding="utf-8"))
        assert "tavily-secret" not in public_text
        assert private["tools"]["web_search"]["api_key"] == "tavily-secret"
        assert config.load()["api_key"] == "model-secret"

        runtime = LocalAgentRuntime(
            config_store=config,
            workspace_root=root / "workspace",
            data_root=root / "data",
        )
        names = {
            str((schema.get("function") or {}).get("name") or "")
            for schema in runtime.tool_schemas()
        }
        assert "web_search" in names

        skill = root / "sample-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\n"
            "name: sample-skill\n"
            "description: Sample local skill\n"
            "metadata:\n"
            "  knowflow:\n"
            "    display_name: Sample Skill\n"
            "    version: 1.0.0\n"
            "---\n"
            "Follow these test instructions.\n",
            encoding="utf-8",
        )
        installed = extensions.install_skill(skill)
        assert installed["slug"] == "sample-skill"
        assert any(item["slug"] == "sample-skill" for item in extensions.list_skills())
        capability_text = json.dumps(extensions.capability_status(), ensure_ascii=False)
        assert "Follow these test instructions" not in capability_text
        assert str(root) not in capability_text
        assert extensions.remove_skill("sample-skill")
        try:
            extensions.remove_skill("")
        except LocalExtensionError:
            pass
        else:
            raise AssertionError("empty Skill slug unexpectedly accepted")

        if os.name != "nt":
            linked = root / "linked-skill"
            linked.mkdir()
            (linked / "SKILL.md").write_text(
                "---\nname: linked-skill\ndescription: linked\n---\n",
                encoding="utf-8",
            )
            (root / "outside.txt").write_text("outside", encoding="utf-8")
            (linked / "outside.txt").symlink_to(root / "outside.txt")
            try:
                extensions.install_skill(linked)
            except LocalExtensionError as exc:
                assert "符号链接" in str(exc)
            else:
                raise AssertionError("symlinked Skill source unexpectedly accepted")

        extensions.save_memory(
            public={
                "enabled": False,
                "llm_base_url": "https://llm.example/v1",
                "llm_model": "memory-model",
                "embedder_base_url": "https://embed.example/v1",
                "embedder_model": "embedding-model",
                "embedding_dims": 4096,
            },
            secrets={
                "llm_api_key": "llm-secret",
                "embedder_api_key": "embed-secret",
            },
        )
        assert extensions.memory_settings()["configured"]
        extensions.set_memory_enabled(True)
        assert extensions.memory_settings()["enabled"]
        assert extensions.memory_provider() is extensions.memory_provider()
        assert "llm-secret" not in config.config_path.read_text(encoding="utf-8")
        status_text = json.dumps(extensions.capability_status(), ensure_ascii=False)
        assert "llm-secret" not in status_text
        assert "embed-secret" not in status_text

        try:
            extensions.save_memory(
                public={
                    "enabled": False,
                    "llm_base_url": "http://memory.example/v1",
                    "llm_model": "memory-model",
                    "embedder_base_url": "https://embed.example/v1",
                    "embedder_model": "embedding-model",
                    "embedding_dims": 1536,
                },
                secrets={
                    "llm_api_key": "llm-secret",
                    "embedder_api_key": "embed-secret",
                },
            )
        except ValueError:
            pass
        else:
            raise AssertionError("insecure memory API URL accepted")

    registry = ToolRegistry()
    calls: list[tuple[str, dict]] = []
    register_mcp_tools(
        registry,
        tools=[
            {
                "modelName": "mcp__notion__search",
                "remoteName": "search",
                "serverId": "notion",
                "serverName": "Notion",
                "description": "Search Notion",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                "annotations": {"readOnlyHint": True},
            }
        ],
        max_tools=8,
        call_tool=lambda item, arguments, _read_only: calls.append(
            (str(item["remoteName"]), arguments)
        ) or {"ok": True},
    )
    prepared = registry.prepare(
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "mcp__notion__search",
                "arguments": json.dumps({"query": "roadmap"}),
            },
        },
        engine_name="langgraph",
    )
    execution = registry.invoke(prepared)
    assert execution.status == "success"
    assert calls == [("search", {"query": "roadmap"})]

    print("local CLI extensions checks passed")


if __name__ == "__main__":
    main()
