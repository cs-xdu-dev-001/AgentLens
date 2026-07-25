from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    env = os.environ.copy()
    env["KNOWFLOW_DB_URL"] = "sqlite:///./data/tdd_relative_path.db"
    env["KNOWFLOW_VECTOR_BACKEND"] = "local"

    script = (
        "from knowflow import runtime; "
        "from pathlib import Path; "
        "print(runtime.DB_URL); "
        "actual = Path(runtime.DB_URL.removeprefix('sqlite:///')).parent.resolve(); "
        "expected = runtime.DATA_DIR.resolve(); "
        "assert actual == expected, f'{actual} != {expected}'"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit(result.returncode)

    print("sqlite relative DB URL resolves to project data directory")


if __name__ == "__main__":
    main()
