from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    sidebar = read("frontend/react/src/components/Sidebar.jsx")
    styles = read("frontend/styles.css")
    assert "latest_run" in sidebar
    assert "sessionRunView" in sidebar
    assert 'active: [],' in sidebar
    assert 'failed: [],' in sidebar
    assert 'waiting_approval' in sidebar
    assert 'className={"session-run-status"}' in sidebar
    assert '"session-run-progress"' in sidebar
    assert "loadingSessions" in sidebar
    assert "switchingSessionId" in sidebar
    assert "switchingSessionRef" in sidebar
    assert 'knowflow:react-session-switch-state' in sidebar
    assert 'aria-busy={isSwitching}' in sidebar
    assert "sessionLoadFailed" in sidebar
    assert '"新任务会显示在这里"' in sidebar
    assert "session-title-row" in sidebar
    assert "indeterminate" in sidebar
    assert ".session-run-status" in styles
    assert ".session-run-progress" in styles
    assert ".session-row.failed" in styles
    assert ".session-list-skeleton" in styles
    assert ".session-list-feedback" in styles
    assert ".session-row.switching" in styles
    assert ".session-switch-state" in styles
    print("frontend session history exposes Agent task state")


if __name__ == "__main__":
    main()
