from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"missing {label}: {needle}")


def forbid(source: str, needle: str, label: str) -> None:
    if needle in source:
        raise AssertionError(f"unexpected {label}: {needle}")


def main() -> None:
    page = read("frontend/react/src/components/SettingsPage.jsx")
    details = read("frontend/react/src/components/ModelConfigDetails.jsx")
    model_list = read("frontend/react/src/components/ModelListPanel.jsx")

    require(page, "connectionResult", "inline connection result state")
    require(page, "latencyMs", "measured connection latency")
    require(details, 'className={"model-config-capabilities"}', "capability summary")
    require(details, 'className={"model-config-connection-result"', "connection result surface")
    require(details, "connectionResultPresentation", "structured connection diagnosis")
    require(details, "查看技术详情", "collapsed technical error details")
    require(details, "model-config-protocol-switch", "one-click protocol recovery")
    require(page, "handleProtocolApply", "protocol recommendation application")
    require(details, 'model-config-more-menu', "progressive disclosure menu")
    require(details, 'aria-label={"更多模型操作"}', "accessible action menu")
    forbid(details, 'className={"secondary-button danger"}', "prominent destructive action")
    require(model_list, 'className={"model-config-item-title"}', "compact list title row")

    for stylesheet in (
        "frontend/refinement.css",
        "frontend/react/src/refinement.css",
    ):
        source = read(stylesheet)
        require(
            source,
            "/* AgentLens refinement: model settings workspace */",
            "model settings refinement marker",
        )
        require(source, ".model-config-capabilities", "capability styling")
        require(source, ".model-config-connection-result", "connection result styling")
        require(source, ".model-config-connection-action", "actionable recovery styling")
        require(source, ".model-config-connection-technical", "technical detail styling")
        require(source, ".model-config-protocol-switch", "protocol switch styling")
        require(source, ".model-config-more-menu", "action menu styling")
        require(source, "background: transparent !important;", "unboxed detail text")

    print("model settings workspace is compact, factual, and interactive")


if __name__ == "__main__":
    main()
