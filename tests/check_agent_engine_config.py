from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def read_engine(value: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    env["KNOWFLOW_AGENT_ENGINE"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from knowflow.config import AGENT_ENGINE; print(AGENT_ENGINE)",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()[-1]


assert read_engine("") == "current"
assert read_engine("current") == "current"
assert read_engine("CURRENT") == "current"
assert read_engine("langgraph") == "current"
assert read_engine("typo") == "current"

print("agent engine configuration defaults safely to current")
