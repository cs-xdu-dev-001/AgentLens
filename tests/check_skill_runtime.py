from __future__ import annotations

from pathlib import Path
import tempfile
import sys

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import AgentRunner, ToolRegistry
from knowflow.services.skill_runtime import (
    ActivateSkillArguments,
    ReadSkillResourceArguments,
    SkillActivationSession,
    SkillRuntimeError,
)
from knowflow.services.skill_store import SkillStore, SkillStoreError
from knowflow.schemas import ChatRequest
from knowflow.routers.chat import should_route_to_agent


class FakeStore:
    def __init__(self):
        self.resolve_calls = []
        self.resource_calls = []

    def activation_candidates(self, user_id, available_tools):
        assert user_id == 7
        assert set(available_tools) == {"web_search"}
        return [
            {
                "id": 41,
                "slug": "research",
                "name": "Research",
                "description": "Research with evidence.",
            }
        ]

    def resolve_for_activation(self, user_id, skill, available_tools):
        self.resolve_calls.append((user_id, skill, tuple(available_tools)))
        if skill in {404, "missing"}:
            error = ValueError("Skill not found.")
            error.code = "skill_not_found"
            raise error
        return {
            "installationId": 41,
            "packageId": 9,
            "slug": "research",
            "displayName": "Research",
            "version": "1.2.3",
            "contentHash": "a" * 64,
            "sourceKind": "personal",
            "requiredTools": ["web_search"],
            "requiredMcp": [],
            "systemMessage": (
                "<activated-skill slug=\"research\">\n"
                "Bounded private body: user@example.com key=secret\n"
                "</activated-skill>"
            ),
        }

    def read_text_resource(self, user_id, skill_id, path):
        self.resource_calls.append((user_id, skill_id, path))
        if not path.startswith("references/"):
            error = ValueError("Invalid Skill resource.")
            error.code = "skill_resource_invalid"
            raise error
        return "reference text"


class Gateway:
    def __init__(self):
        self.calls = []

    def complete(self, messages, config, *, tools=None, tool_choice=None):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": tools,
            }
        )
        if len(self.calls) == 1:
            names = {
                item["function"]["name"]
                for item in tools
            }
            assert names == {"activate_skill", "web_search"}
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "activate-1",
                        "type": "function",
                        "function": {
                            "name": "activate_skill",
                            "arguments": '{"skill":"research"}',
                        },
                    }
                ],
            }
        if len(self.calls) == 2:
            names = {
                item["function"]["name"]
                for item in tools
            }
            assert names == {"read_skill_resource", "web_search"}
            assert "Bounded private body" in self.calls[-1]["messages"][-1]["content"]
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}


def main() -> None:
    explicit_request = ChatRequest(
        question="hello",
        autoAgent=False,
        enableTools=False,
        skillId=41,
    )
    assert explicit_request.skillId == 41
    assert should_route_to_agent(explicit_request) is True

    for model, value in (
        (ActivateSkillArguments, {"skill": ""}),
        (ReadSkillResourceArguments, {"path": "../secret"}),
        (ActivateSkillArguments, {"skill": "research", "extra": True}),
    ):
        try:
            model.model_validate(value)
            raise AssertionError("strict bounded model should reject input")
        except ValidationError:
            pass

    store = FakeStore()
    session = SkillActivationSession(
        store=store,
        user_id=7,
        available_tools={"web_search"},
    )
    assert session.catalog() == [
        {
            "id": 41,
            "slug": "research",
            "name": "Research",
            "description": "Research with evidence.",
        }
    ]
    registry = ToolRegistry()
    registry.register(
        name="web_search",
        description="search",
        input_schema={"type": "object", "additionalProperties": False},
        handler=lambda args: {"results": []},
    )
    session.register_activation_tool(registry)
    gateway = Gateway()
    result = AgentRunner(gateway=gateway).run(
        messages=[
            {"role": "system", "content": "base"},
            {"role": "user", "content": "research"},
        ],
        config={},
        registry=registry,
    )
    assert result.answer == "done"
    activation = result.executions[0]
    assert "Bounded private body" in activation.model_content()
    assert "Bounded private body" not in str(activation.public_output())
    assert activation.skill_snapshot == {
        "skillId": 41,
        "skillSlug": "research",
        "skillVersion": "1.2.3",
        "skillContentHash": "a" * 64,
    }
    assert set(registry.names()) == {"web_search", "read_skill_resource"}
    assert "scripts" not in str(gateway.calls)
    try:
        session.activate("research")
        raise AssertionError("only one Skill may be active")
    except SkillRuntimeError as exc:
        assert exc.code == "skill_already_active"

    fresh = SkillActivationSession(
        store=store,
        user_id=7,
        available_tools={"web_search"},
    )
    try:
        fresh.read_resource("references/info.txt")
        raise AssertionError("resource reads require activation")
    except SkillRuntimeError as exc:
        assert exc.code == "skill_not_active"
    fresh.activate(41)
    resource = fresh.read_resource("references/info.txt")
    assert resource.output == {"path": "references/info.txt", "content": "reference text"}
    assert resource.audit_output == {"characterCount": 14}
    assert "references/info.txt" not in str(resource.audit_output)
    try:
        fresh.read_resource("../secret")
        raise AssertionError("traversal must fail")
    except SkillRuntimeError as exc:
        assert exc.code == "skill_resource_invalid"

    with tempfile.TemporaryDirectory() as temporary:
        package = Path(temporary) / "package"
        references = package / "references"
        references.mkdir(parents=True)
        manifest_text = (
            "---\n"
            "name: local-check\n"
            "description: Local check.\n"
            "metadata:\n"
            "  knowflow:\n"
            "    display_name: Local Check\n"
            "    version: 2.0.0\n"
            "    required_tools: [web_search]\n"
            "    required_mcp: [notion]\n"
            "---\n"
            "Follow this bounded workflow.\n"
        )
        (package / "SKILL.md").write_text(manifest_text, encoding="utf-8")
        (references / "guide.txt").write_text("guide", encoding="utf-8")
        (references / "binary.bin").write_bytes(b"\x00\x01\x02")
        (references / "large.txt").write_text("x" * 20001, encoding="utf-8")
        (package / "scripts").mkdir()
        (package / "scripts" / "secret.txt").write_text("secret", encoding="utf-8")
        row = {
            "id": 9,
            "installation_id": 41,
            "package_id": 9,
            "slug": "local-check",
            "display_name": "Local Check",
            "description": "Local check.",
            "version": "2.0.0",
            "source_kind": "personal",
            "content_hash": __import__("hashlib").sha256(
                (package / "SKILL.md").read_bytes()
            ).hexdigest(),
            "package_path": "package",
            "enabled": 1,
        }
        real_store = SkillStore.__new__(SkillStore)
        real_store.skill_dir = Path(temporary).resolve()
        real_store.builtin_dir = Path(temporary).resolve()
        real_store.max_body_chars = 20000
        real_store._ensure_builtins_for_user = lambda user_id: None
        real_store.fetch_one = lambda statement, parameters: dict(row)
        real_store.fetch_all = lambda statement, parameters: [dict(row)]
        assert real_store.activation_candidates(
            7, {"web_search"}
        ) == []
        assert [
            item["slug"]
            for item in real_store.activation_candidates(
                7, {"web_search", "notion"}
            )
        ] == ["local-check"]
        resolved = real_store.resolve_for_activation(
            7, 41, {"web_search", "notion"}
        )
        assert resolved["systemMessage"].endswith("</activated-skill>")
        assert "Follow this bounded workflow." in resolved["systemMessage"]
        assert "scripts" not in resolved["systemMessage"]
        assert real_store.read_text_resource(
            7, 9, "references/guide.txt"
        ) == "guide"
        for invalid_path, expected in (
            ("../secret", "skill_resource_invalid"),
            ("scripts/secret.txt", "skill_resource_invalid"),
            ("references/binary.bin", "skill_resource_not_text"),
            ("references/large.txt", "skill_resource_too_large"),
        ):
            try:
                real_store.read_text_resource(7, 9, invalid_path)
                raise AssertionError(f"{invalid_path} should fail")
            except SkillStoreError as exc:
                assert exc.code == expected, (invalid_path, exc.code)

    print("Skill runtime activates one bounded Skill and protects private content")


if __name__ == "__main__":
    main()
