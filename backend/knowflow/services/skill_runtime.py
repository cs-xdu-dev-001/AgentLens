from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .agent_loop import ToolHandlerResult, ToolRegistry


class SkillRuntimeError(ValueError):
    def __init__(self, code: str, message: str = "Skill activation failed."):
        self.code = code
        super().__init__(message)


class ActivateSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    skill: str = Field(min_length=1, max_length=120)


class ReadSkillResourceArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(min_length=1, max_length=500)

    @field_validator("path")
    @classmethod
    def validate_reference_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (
            value != normalized
            or not normalized.startswith("references/")
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("Skill resources must be under references/.")
        return value


@dataclass(frozen=True)
class ActivatedSkill:
    installation_id: int
    package_id: int
    slug: str
    display_name: str
    version: str
    content_hash: str
    source_kind: str
    required_tools: tuple[str, ...]
    required_mcp: tuple[str, ...]
    planning: str
    system_message: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "skillId": self.installation_id,
            "skillSlug": self.slug,
            "skillVersion": self.version,
            "skillContentHash": self.content_hash,
        }

    def audit(self) -> dict[str, Any]:
        return {
            "snapshot": self.snapshot(),
            "displayName": self.display_name,
            "version": self.version,
            "sourceKind": self.source_kind,
            "requiredTools": list(self.required_tools),
            "requiredMcp": list(self.required_mcp),
            "planning": self.planning,
        }


class SkillActivationSession:
    def __init__(
        self,
        *,
        store: Any,
        user_id: int,
        available_tools: Iterable[str],
    ):
        self.store = store
        self.user_id = int(user_id)
        self.available_tools = tuple(
            dict.fromkeys(str(name) for name in available_tools)
        )
        self.active: ActivatedSkill | None = None

    def catalog(self) -> list[dict[str, Any]]:
        candidates = self.store.activation_candidates(
            self.user_id,
            self.available_tools,
        )
        return [
            {
                "id": int(item["id"]),
                "slug": str(item["slug"]),
                "name": str(item["name"]),
                "description": str(item["description"]),
            }
            for item in candidates
        ]

    @staticmethod
    def _runtime_error(exc: Exception) -> SkillRuntimeError:
        return SkillRuntimeError(
            str(getattr(exc, "code", "") or "skill_activation_failed"),
            str(exc) or "Skill activation failed.",
        )

    def activate(self, skill: str | int) -> ToolHandlerResult:
        if self.active is not None:
            raise SkillRuntimeError(
                "skill_already_active",
                "A Skill is already active for this run.",
            )
        try:
            item = self.store.resolve_for_activation(
                self.user_id,
                skill,
                self.available_tools,
            )
        except Exception as exc:
            raise self._runtime_error(exc) from exc
        active = ActivatedSkill(
            installation_id=int(item["installationId"]),
            package_id=int(item["packageId"]),
            slug=str(item["slug"]),
            display_name=str(item["displayName"]),
            version=str(item["version"]),
            content_hash=str(item["contentHash"]),
            source_kind=str(item["sourceKind"]),
            required_tools=tuple(item.get("requiredTools") or ()),
            required_mcp=tuple(item.get("requiredMcp") or ()),
            planning=str(item.get("planning") or "auto"),
            system_message=str(item["systemMessage"]),
        )
        self.active = active
        return ToolHandlerResult(
            output={
                "activated": True,
                "skill": active.snapshot(),
                "instructions": active.system_message,
            },
            audit_output=active.audit(),
            skill_snapshot=active.snapshot(),
        )

    def restore(self, snapshot: dict[str, Any]) -> ActivatedSkill:
        try:
            expected = {
                "skillId": int(snapshot.get("skillId") or 0),
                "skillSlug": str(snapshot.get("skillSlug") or ""),
                "skillVersion": str(snapshot.get("skillVersion") or ""),
                "skillContentHash": str(
                    snapshot.get("skillContentHash") or ""
                ),
            }
        except (TypeError, ValueError) as exc:
            raise SkillRuntimeError(
                "skill_snapshot_invalid",
                "The saved Skill snapshot is invalid.",
            ) from exc
        if (
            expected["skillId"] <= 0
            or not expected["skillSlug"]
            or not expected["skillVersion"]
            or not expected["skillContentHash"]
        ):
            raise SkillRuntimeError(
                "skill_snapshot_invalid",
                "The saved Skill snapshot is invalid.",
            )
        if self.active is None:
            self.activate(expected["skillId"])
        if self.active is None or self.active.snapshot() != expected:
            self.active = None
            raise SkillRuntimeError(
                "skill_snapshot_changed",
                "The saved Skill version is no longer available.",
            )
        return self.active

    def read_resource(self, path: str) -> ToolHandlerResult:
        if self.active is None:
            raise SkillRuntimeError(
                "skill_not_active",
                "Activate a Skill before reading its resources.",
            )
        try:
            validated = ReadSkillResourceArguments(path=path)
            content = self.store.read_text_resource(
                self.user_id,
                self.active.package_id,
                validated.path,
            )
        except SkillRuntimeError:
            raise
        except Exception as exc:
            if isinstance(exc, ValidationError):
                raise SkillRuntimeError(
                    "skill_resource_invalid",
                    "Invalid Skill resource path.",
                ) from exc
            raise self._runtime_error(exc) from exc
        return ToolHandlerResult(
            output={"path": validated.path, "content": str(content)},
            audit_output={
                "characterCount": len(str(content)),
            },
            skill_snapshot=self.active.snapshot(),
        )

    def register_read_resource(self, registry: ToolRegistry) -> None:
        if self.active is None:
            raise SkillRuntimeError("skill_not_active")
        registry.register(
            name="read_skill_resource",
            description=(
                "Read a UTF-8 text resource from the active Skill's "
                "references/ directory."
            ),
            arguments_model=ReadSkillResourceArguments,
            handler=lambda args: self.read_resource(args.path),
            read_only=True,
            engine_names={"current", "langgraph"},
            trace_kind="skill",
            internal=True,
        )

    def register_activation_tool(self, registry: ToolRegistry) -> None:
        def activate(args: ActivateSkillArguments) -> ToolHandlerResult:
            result = self.activate(args.skill)
            self.register_read_resource(registry)
            return result

        registry.register(
            name="activate_skill",
            description=(
                "Activate exactly one available Skill for this agent run."
            ),
            arguments_model=ActivateSkillArguments,
            handler=activate,
            read_only=True,
            engine_names={"current", "langgraph"},
            trace_kind="skill",
            internal=True,
            becomes_parent_on_success=True,
            remove_after_success=True,
        )
