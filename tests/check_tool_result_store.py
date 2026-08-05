from pathlib import Path
import json
import os
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolDefinition, ToolRegistry
from knowflow.services.tool_result_store import ToolResultStore


EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def tool_call(name: str, arguments: dict | None = None) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments or {}),
        },
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "tool-results"
        store = ToolResultStore(
            root,
            user_id=7,
            run_id="run-large-output",
            max_storage_chars=100_000,
        )
        registry = ToolRegistry(
            result_store=store,
            default_max_result_size_chars=200,
        )
        registry.register(
            name="large_read",
            description="Return a deliberately large read-only result.",
            input_schema=EMPTY_SCHEMA,
            handler=lambda _args: {"content": "记忆片段" * 20_000},
            read_only=True,
            concurrency_safe=True,
            interrupt_behavior="cancel",
            search_hint="large test output",
        )

        definition = registry.definition("large_read")
        assert definition is not None
        assert definition.requires_approval is False
        assert definition.can_run_concurrently({}) is True
        assert definition.interrupt_behavior == "cancel"
        assert definition.search_hint == "large test output"

        execution = registry.execute(tool_call("large_read"))
        assert execution.status == "success"
        reference = execution.output["storedToolResult"]
        result_id = reference["resultId"]
        assert reference["complete"] is True
        assert reference["originalCharacters"] > 50_000
        assert "read_tool_result" in registry.names()
        assert len(execution.model_content()) < 1_000
        assert str(root) not in execution.model_content()

        first_page = registry.execute(
            tool_call(
                "read_tool_result",
                {
                    "result_id": result_id,
                    "offset": 0,
                    "limit": 20_000,
                },
            )
        )
        assert first_page.status == "success"
        assert "记忆片段" in first_page.output["content"]
        assert first_page.output["eof"] is False
        assert first_page.output["nextOffset"] == 20_000

        isolated = ToolResultStore(
            root,
            user_id=8,
            run_id="run-large-output",
        )
        try:
            isolated.read(result_id)
            raise AssertionError("another user read a stored tool result")
        except FileNotFoundError:
            pass

        try:
            store.read("../escape")
            raise AssertionError("invalid result identifier was accepted")
        except ValueError:
            pass

        expired = root / ("a" * 32)
        expired.mkdir()
        (expired / "result.json").write_text("{}", encoding="utf-8")
        old_time = time.time() - 120
        os.utime(expired / "result.json", (old_time, old_time))
        os.utime(expired, (old_time, old_time))
        cleanup_store = ToolResultStore(
            root,
            user_id=9,
            run_id="run-cleanup",
            retention_seconds=60,
        )
        assert cleanup_store.cleanup_expired() == 1
        assert not expired.exists()
        assert cleanup_store.cleanup_expired() == 0

        write_definition = ToolDefinition(
            name="write_note",
            description="Write a note.",
            handler=lambda args: args,
            input_schema=EMPTY_SCHEMA,
            read_only=False,
            destructive=True,
        )
        assert write_definition.requires_approval is True

        try:
            ToolDefinition(
                name="invalid_delete",
                description="Invalid metadata.",
                handler=lambda args: args,
                input_schema=EMPTY_SCHEMA,
                read_only=True,
                destructive=True,
            )
            raise AssertionError("destructive read-only tool was accepted")
        except ValueError:
            pass

    print(
        "tool contracts bound model context and isolate stored results"
    )


if __name__ == "__main__":
    main()
