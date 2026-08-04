from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
source = EXTENSIONS.read_text(encoding="utf-8")
tree = ast.parse(source)

agent_loop_imports = set()
agent_engine_imports = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "services.agent_loop":
        agent_loop_imports.update(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module == "services.agent_engine":
        agent_engine_imports.update(alias.name for alias in node.names)

factory_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "build_agent_engine"
]
engine_run_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and isinstance(node.func.value, ast.Name)
    and node.func.value.id == "engine"
    and node.func.attr == "run"
]
wrapped_run_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "engine_run"
]

assert "ToolRegistry" in agent_loop_imports
assert "AgentRunner" not in agent_loop_imports
assert "build_agent_engine" in agent_engine_imports
assert len(factory_calls) == 1
assert len(engine_run_calls) == 1
assert len(wrapped_run_calls) == 3
engine_keyword_names = {keyword.arg for keyword in engine_run_calls[0].keywords}
assert {
    "tool_operation_store",
    "approval_decision",
    "memory_recall",
    "memory_enabled",
}.issubset(
    engine_keyword_names
)
for call in wrapped_run_calls:
    keyword_names = {keyword.arg for keyword in call.keywords}
    assert {"user_id", "run_id"}.issubset(keyword_names)
assert sum(
    any(
        keyword.arg == "resume_from_checkpoint"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )
    for call in wrapped_run_calls
) == 1
assert "AGENT_ENGINE" in source
assert 'stored_request["_agentEngine"] = selected_engine_name' in source
assert 'request_payload.pop("_agentEngine", None)' in source
assert any(
    call.args
    and isinstance(call.args[0], ast.Name)
    and call.args[0].id == "selected_engine_name"
    for call in factory_calls
)

print("agent routes depend on the engine interface")
