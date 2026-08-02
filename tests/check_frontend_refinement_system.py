from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    source = read("frontend/refinement.css")
    main_js = read("frontend/react/src/main.jsx")
    sync = read("frontend/scripts/sync-assets.mjs")
    assert '["refinement.css", "react/src/refinement.css"]' in sync
    assert 'import "./refinement.css";' in main_js
    assert main_js.index('import "./styles.css";') < main_js.index(
        'import "./refinement.css";'
    )
    for token in (
        "--kf-type-page",
        "--kf-type-title",
        "--kf-type-body",
        "--kf-radius-control",
        "--kf-space-4",
        "/* KnowFlow refinement: foundation */",
    ):
        assert token in source, f"missing refinement token: {token}"
    for token in (
        "/* KnowFlow refinement: shell and controls */",
        "body {",
        ":focus-visible",
        ".workspace-page",
        ".settings-header",
        ".icon-button",
        ".secondary-button",
    ):
        assert token in source, f"missing foundation rule: {token}"
    drawer = read("frontend/react/src/components/ChatEvidenceDrawer.jsx")
    trace = read("frontend/react/src/components/AgentTraceView.jsx")
    assert 'aria-live={"polite"}' in drawer
    assert 'aria-atomic={"true"}' in drawer
    assert 'aria-label={"Agent运行步骤"}' in trace
    for token in (
        "/* KnowFlow refinement: composer */",
        "/* KnowFlow refinement: run drawer */",
        ".composer-shell",
        ".composer-model-popover",
        ".agent-trace-node",
        ".agent-trace-step-detail",
    ):
        assert token in source, f"missing chat refinement: {token}"
    form = read("frontend/react/src/components/ModelConfigForm.jsx")
    for field in ('name={"temperature"}', 'name={"topP"}'):
        assert field not in form, f"non-essential field returned: {field}"
    for token in (
        "/* KnowFlow refinement: settings */",
        ".settings-workspace-shell",
        ".model-config-item",
        ".model-config-details",
        ".model-config-form",
    ):
        assert token in source, f"missing settings refinement: {token}"
    for token in (
        "/* KnowFlow refinement: management pages */",
        "#page-knowledge",
        "#page-skills",
        "#page-memory",
        "#page-tools",
        ".skills-list-row",
        ".memory-item",
        ".mcp-server-card",
    ):
        assert token in source, f"missing management refinement: {token}"
    print("frontend refinement system is wired")


if __name__ == "__main__":
    main()
