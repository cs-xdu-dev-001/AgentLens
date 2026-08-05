from __future__ import annotations

from dataclasses import dataclass
import json
import re
import threading
import time
from typing import Any, Callable

from pydantic import BaseModel, Field

from .tool_result_store import (
    ReadToolResultArguments,
    ToolResultStore,
)


DEFAULT_MAX_TOOL_RESULT_CHARS = 12_000


class ToolSearchArguments(BaseModel):
    query: str = Field(default="", max_length=240)
    tool_names: list[str] = Field(default_factory=list, max_length=12)
    top_k: int = Field(default=6, ge=1, le=12)


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
    destructive: bool = False
    concurrency_safe: bool | Callable[[dict[str, Any]], bool] = False
    interrupt_behavior: str = "block"
    max_result_size_chars: int = DEFAULT_MAX_TOOL_RESULT_CHARS
    search_hint: str | None = None
    should_defer: bool = False
    always_load: bool = False

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
        if self.destructive and self.read_only:
            raise ValueError("destructive tools cannot be read-only")
        if self.interrupt_behavior not in {"block", "cancel"}:
            raise ValueError("invalid tool interrupt behavior")
        if self.max_result_size_chars < 1:
            raise ValueError("max_result_size_chars must be positive")
        if self.should_defer and self.always_load:
            raise ValueError("deferred tools cannot always load")

    def can_run_concurrently(self, arguments: dict[str, Any]) -> bool:
        if (
            self.requires_approval
            or self.becomes_parent_on_success
            or self.remove_after_success
            or self.ends_run_on_success
        ):
            return False
        if callable(self.concurrency_safe):
            try:
                return bool(self.concurrency_safe(arguments))
            except Exception:
                return False
        return bool(self.concurrency_safe)

    @property
    def requires_approval(self) -> bool:
        return bool(not self.read_only or self.destructive)


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
    def __init__(
        self,
        *,
        result_store: ToolResultStore | None = None,
        default_max_result_size_chars: int = (
            DEFAULT_MAX_TOOL_RESULT_CHARS
        ),
    ) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._result_store = result_store
        self._default_max_result_size_chars = max(
            1,
            int(default_max_result_size_chars),
        )
        self._result_reader_lock = threading.Lock()
        self._tool_search_enabled = False
        self._activated_deferred_tools: set[str] = set()

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
        destructive: bool = False,
        concurrency_safe: (
            bool | Callable[[dict[str, Any]], bool]
        ) = False,
        interrupt_behavior: str = "block",
        max_result_size_chars: int | None = None,
        search_hint: str | None = None,
        should_defer: bool = False,
        always_load: bool = False,
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
            destructive=destructive,
            concurrency_safe=concurrency_safe,
            interrupt_behavior=interrupt_behavior,
            max_result_size_chars=(
                self._default_max_result_size_chars
                if max_result_size_chars is None
                else int(max_result_size_chars)
            ),
            search_hint=search_hint,
            should_defer=should_defer,
            always_load=always_load,
        )

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def eligible_names(self, engine_name: str) -> frozenset[str]:
        return frozenset(
            definition.name
            for definition in self._definitions.values()
            if engine_name in definition.engine_names
            and self._is_exposed(definition)
        )

    def _is_exposed(self, definition: ToolDefinition) -> bool:
        return bool(
            not self._tool_search_enabled
            or not definition.should_defer
            or definition.always_load
            or definition.name in self._activated_deferred_tools
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
            ) or not self._is_exposed(definition):
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

    def enable_tool_search(self, *, threshold: int = 8) -> bool:
        deferred = [
            definition
            for definition in self._definitions.values()
            if definition.should_defer and not definition.always_load
        ]
        if len(deferred) < max(1, int(threshold)):
            return False
        self._tool_search_enabled = True

        def search(args: ToolSearchArguments) -> dict[str, Any]:
            return self.search_tools(
                query=args.query,
                tool_names=args.tool_names,
                top_k=args.top_k,
            )

        self.register(
            name="tool_search",
            description=(
                "Find and load relevant deferred tools before calling them. "
                "Use tool_names for exact selection when names are known."
            ),
            handler=search,
            arguments_model=ToolSearchArguments,
            read_only=True,
            internal=True,
            concurrency_safe=False,
            interrupt_behavior="cancel",
            search_hint="find available tools by capability",
            always_load=True,
        )
        return True

    def search_tools(
        self,
        *,
        query: str = "",
        tool_names: list[str] | None = None,
        top_k: int = 6,
    ) -> dict[str, Any]:
        if not self._tool_search_enabled:
            return {"loaded": [], "message": "Tool search is not enabled."}
        requested = {
            str(name or "").strip()
            for name in (tool_names or [])
            if str(name or "").strip()
        }
        terms = [
            term
            for term in re.findall(r"[\w-]+", query.lower(), flags=re.UNICODE)
            if len(term) > 1
        ]
        ranked: list[tuple[int, str, ToolDefinition]] = []
        for definition in self._definitions.values():
            if not definition.should_defer or definition.always_load:
                continue
            if requested:
                score = 10_000 if definition.name in requested else 0
            else:
                haystack = " ".join(
                    filter(
                        None,
                        (
                            definition.name,
                            definition.description,
                            definition.search_hint,
                            definition.server_name,
                        ),
                    )
                ).lower()
                score = sum(
                    4 if term in definition.name.lower() else 1
                    for term in terms
                    if term in haystack
                )
            if score > 0:
                ranked.append((score, definition.name, definition))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = [
            definition
            for _score, _name, definition in ranked[: max(1, top_k)]
        ]
        self._activated_deferred_tools.update(
            definition.name for definition in selected
        )
        return {
            "loaded": [
                {
                    "name": definition.name,
                    "description": definition.description,
                    "serverName": definition.server_name,
                    "readOnly": definition.read_only,
                    "risk": definition.risk,
                }
                for definition in selected
            ],
            "remainingDeferred": max(
                0,
                sum(
                    1
                    for definition in self._definitions.values()
                    if definition.should_defer
                    and definition.name
                    not in self._activated_deferred_tools
                ),
            ),
        }

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
                output = self._compact_output(
                    definition,
                    prepared,
                    raw.output,
                )
                return ToolExecution(
                    prepared.call_id,
                    prepared.tool_name,
                    prepared.arguments,
                    output,
                    "success",
                    None,
                    None,
                    int((time.perf_counter() - started) * 1000),
                    raw.audit_output,
                    raw.skill_snapshot,
                )
            output = raw if isinstance(raw, dict) else {"value": raw}
            return ToolExecution(
                prepared.call_id,
                prepared.tool_name,
                prepared.arguments,
                self._compact_output(definition, prepared, output),
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

    def _compact_output(
        self,
        definition: ToolDefinition,
        prepared: PreparedToolCall,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        if self._result_store is None:
            return output
        compacted = self._result_store.compact(
            call_id=prepared.call_id,
            tool_name=prepared.tool_name,
            output=output,
            max_result_size_chars=definition.max_result_size_chars,
        )
        if compacted is not output:
            self._ensure_result_reader()
        return compacted

    def _ensure_result_reader(self) -> None:
        if (
            self._result_store is None
            or "read_tool_result" in self._definitions
        ):
            return

        with self._result_reader_lock:
            if "read_tool_result" in self._definitions:
                return

            def read_result(
                args: ReadToolResultArguments,
            ) -> dict[str, Any]:
                return self._result_store.read(
                    args.result_id,
                    offset=args.offset,
                    limit=args.limit,
                )

            self.register(
                name="read_tool_result",
                description=(
                    "Read one bounded chunk from a large result previously "
                    "stored during this Agent run."
                ),
                handler=read_result,
                arguments_model=ReadToolResultArguments,
                read_only=True,
                internal=True,
                concurrency_safe=True,
                interrupt_behavior="cancel",
                max_result_size_chars=24_000,
                search_hint="read remaining large tool output",
                always_load=True,
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
