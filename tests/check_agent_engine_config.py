import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_engine import select_agent_engine_name


config_source = (ROOT / "backend" / "knowflow" / "config.py").read_text(
    encoding="utf-8"
)
env_example = (ROOT / "backend" / ".env.example").read_text(
    encoding="utf-8"
)
assert "KNOWFLOW_AGENT_ENGINE" not in config_source
assert "KNOWFLOW_AGENT_ENGINE" not in env_example
assert select_agent_engine_name(None) == "langgraph"
assert select_agent_engine_name("") == "langgraph"
assert select_agent_engine_name("current") == "current"
assert select_agent_engine_name("CURRENT") == "current"
assert select_agent_engine_name("langgraph") == "langgraph"
assert select_agent_engine_name(" LANGGRAPH ") == "langgraph"
assert select_agent_engine_name("typo") == "langgraph"

print("new runs use LangGraph while historical engines remain recoverable")
