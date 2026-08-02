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

assert "ToolRegistry" in agent_loop_imports
assert "AgentRunner" not in agent_loop_imports
assert "build_agent_engine" in agent_engine_imports
assert len(factory_calls) == 1
assert len(engine_run_calls) == 2
assert "AGENT_ENGINE" in source

print("agent routes depend on the engine interface")
