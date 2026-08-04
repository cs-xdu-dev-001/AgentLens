from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


config_source = (ROOT / "backend" / "knowflow" / "config.py").read_text(
    encoding="utf-8"
)
env_example = (ROOT / "backend" / ".env.example").read_text(
    encoding="utf-8"
)
assert "KNOWFLOW_AGENT_ENGINE" not in config_source
assert "KNOWFLOW_AGENT_ENGINE" not in env_example

print("the retired engine selector is no longer configurable")
