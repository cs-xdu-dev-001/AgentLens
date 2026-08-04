from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Callable

from pydantic import BaseModel


@dataclass
class ToolDefinition:
    name: str
    description: str
    handler: Callable[[Any], Any]
    arguments_model: type[BaseModel] | None = None
    input_schema: dict[str, Any] | None = None
    read_only: bool = True
    engine_names: frozenset[str] = frozenset({"langgraph"})
    trace_kind: str = "tool"
    risk: str = "read"
    server_name: str | None = None
    internal: bool = False
    becomes_parent_on_success: bool = False
    remove_after_success: bool = False
    ends_run_on_success: bool = False

    def __post_init__(self) -> None:
        if (self.arguments_model is None) == (self.input_schema is None):
            raise ValueError(
                "exactly one of arguments_model or input_schema is required"
            )
        if self.input_schema is not None:
            try:
                from jsonschema import Draft202012Validator

                Draft202012Validator.check_schema(self.input_schema)
            except Exception as exc:
                raise ValueError("invalid input schema") from exc


@dataclass
class ToolHandlerResult:
    output: dict[str, Any]
    audit_output: dict[str, Any] | None = None
    skill_snapshot: dict[str, Any] | None = None


@dataclass
class ToolExecution:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    output: dict[str, Any]
    status: str
    error_code: str | None
    error_message: str | None
    latency_ms: int
    audit_output: dict[str, Any] | None = None
    skill_snapshot: dict[str, Any] | None = None

    def model_content(self) -> str:
        return json.dumps(
            {
                "ok": self.status == "success",
                "result": (
                    self.output if self.status == "success" else None
                ),
                "error": (
                    {
                        "code": self.error_code,
                        "message": self.error_message,
                    }
                    if self.status != "success"
                    else None
                ),
            },
            ensure_ascii=False,
        )

    def public_output(self) -> dict[str, Any]:
        return (
            self.audit_output
            if self.audit_output is not None
            else self.output
        )


@dataclass
class PreparedToolCall:
    definition: ToolDefinition | None
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    error: ToolExecution | None = None


@dataclass
class AgentRunResult:
    answer: str
    executions: list[ToolExecution]
    trace: list[dict[str, Any]]
    paused: bool = False
    interrupt: dict[str, Any] | None = None
    memories: list[dict[str, Any]] | None = None
    memory_recalled: bool = False
    retrieval_chunks: list[dict[str, Any]] | None = None
    retrieval_quality: dict[str, Any] | None = None
    retrieval_run: dict[str, Any] | None = None
    retrieval_completed: bool = False


class AgentLoopLimitError(RuntimeError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(
        self,
        *,
        name: str,
        description: str,
        handler: Callable[[Any], Any],
        read_only: bool = True,
        arguments_model: type[BaseModel] | None = None,
        input_schema: dict[str, Any] | None = None,
        engine_names: (
            set[str] | frozenset[str] | tuple[str, ...]
        ) = ("langgraph",),
        trace_kind: str = "tool",
        risk: str = "read",
        server_name: str | None = None,
        internal: bool = False,
        becomes_parent_on_success: bool = False,
        remove_after_success: bool = False,
        ends_run_on_success: bool = False,
    ) -> None:
        self._definitions[name] = ToolDefinition(
            name=name,
            description=description,
            handler=handler,
            arguments_model=arguments_model,
            input_schema=input_schema,
            read_only=read_only,
            engine_names=frozenset(engine_names),
            trace_kind=trace_kind,
            risk=risk,
            server_name=server_name,
            internal=internal,
            becomes_parent_on_success=becomes_parent_on_success,
            remove_after_success=remove_after_success,
            ends_run_on_success=ends_run_on_success,
        )

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def eligible_names(self, engine_name: str) -> frozenset[str]:
        return frozenset(
            definition.name
            for definition in self._definitions.values()
            if engine_name in definition.engine_names
        )

    def unregister(self, name: str) -> bool:
        return self._definitions.pop(name, None) is not None

    def schemas(
        self,
        allowed_names: set[str] | None = None,
        *,
        engine_name: str | None = None,
    ) -> list[dict[str, Any]]:
        schemas = []
        for definition in self._definitions.values():
            if (
                allowed_names is not None
                and definition.name not in allowed_names
            ) or (
                engine_name is not None
                and engine_name not in definition.engine_names
            ):
                continue
            parameters = (
                definition.arguments_model.model_json_schema()
                if definition.arguments_model
                else definition.input_schema
            )
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": definition.name,
                        "description": definition.description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas

    def prepare(
        self,
        tool_call: dict[str, Any],
        allowed_names: set[str] | None = None,
        *,
        engine_name: str | None = None,
    ) -> PreparedToolCall:
        function = tool_call.get("function") or {}
        call_id = str(tool_call.get("id") or "")
        name = str(function.get("name") or "")
        definition = self._definitions.get(name)
        started = time.perf_counter()
        if (
            allowed_names is not None and name not in allowed_names
        ) or (
            definition is not None
            and engine_name is not None
            and engine_name not in definition.engine_names
        ):
            definition = None
        if definition is None:
            return PreparedToolCall(
                None,
                call_id,
                name or "unknown",
                {},
                self._failure(
                    call_id,
                    name or "unknown",
                    {},
                    "unknown_tool",
                    "The requested tool is not registered.",
                    started,
                ),
            )
        try:
            raw = function.get("arguments") or "{}"
            arguments = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be an object.")
            if definition.arguments_model:
                validated = definition.arguments_model.model_validate(
                    arguments
                )
                normalized = validated.model_dump()
            else:
                from jsonschema import validate

                validate(instance=arguments, schema=definition.input_schema)
                normalized = arguments
            return PreparedToolCall(
                definition,
                call_id,
                name,
                normalized,
            )
        except Exception:
            return PreparedToolCall(
                definition,
                call_id,
                name,
                {},
                self._failure(
                    call_id,
                    name,
                    {},
                    "invalid_arguments",
                    "Invalid tool arguments.",
                    started,
                ),
            )

    def invoke(self, prepared: PreparedToolCall) -> ToolExecution:
        if prepared.error:
            return prepared.error
        started = time.perf_counter()
        definition = prepared.definition
        if definition is None:
            return self._failure(
                prepared.call_id,
                prepared.tool_name,
                prepared.arguments,
                "unknown_tool",
                "The requested tool is not registered.",
                started,
            )
        try:
            raw = definition.handler(
                prepared.arguments
                if definition.arguments_model is None
                else definition.arguments_model.model_validate(
                    prepared.arguments
                )
            )
            if isinstance(raw, ToolHandlerResult):
                return ToolExecution(
                    prepared.call_id,
                    prepared.tool_name,
                    prepared.arguments,
                    raw.output,
                    "success",
                    None,
                    None,
                    int((time.perf_counter() - started) * 1000),
                    raw.audit_output,
                    raw.skill_snapshot,
                )
            return ToolExecution(
                prepared.call_id,
                prepared.tool_name,
                prepared.arguments,
                raw if isinstance(raw, dict) else {"value": raw},
                "success",
                None,
                None,
                int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            return self._failure(
                prepared.call_id,
                prepared.tool_name,
                prepared.arguments,
                str(getattr(exc, "code", "") or "tool_execution_failed"),
                str(exc) or "Tool execution failed.",
                started,
            )

    def execute(self, tool_call: dict[str, Any]) -> ToolExecution:
        return self.invoke(self.prepare(tool_call))

    @staticmethod
    def _failure(
        call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        error_code: str,
        error_message: str,
        started_at: float,
    ) -> ToolExecution:
        return ToolExecution(
            call_id,
            tool_name,
            arguments,
            {},
            "failed",
            error_code,
            error_message,
            int((time.perf_counter() - started_at) * 1000),
        )
