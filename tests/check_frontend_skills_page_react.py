from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def forbid(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle in text:
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def main() -> None:
    require("frontend/react/src/App.jsx", 'import { SkillsPage }', "Skills page import")
    require(
        "frontend/react/src/App.jsx",
        '<SkillsPage active={activePage === "skills"}',
        "Skills page mount",
    )
    require("frontend/react/src/data/navigation.js", 'key: "skills"', "Skills navigation")

    api = "frontend/react/src/api/client.js"
    require(api, "export const skillApi", "Skill API client")
    require(api, "inspectGitHub", "GitHub inspection API")
    require(api, "inspectUpload", "ZIP inspection API")
    require(api, "FormData", "multipart upload body")
    require(api, "/api/skills/import/github/inspect", "GitHub inspection route")
    require(api, "/api/skills/import/upload/inspect", "upload inspection route")
    require(api, "/check-update", "update inspection route")

    page = "frontend/react/src/components/SkillsPage.jsx"
    for state in (
        "skills",
        "activeTab",
        "query",
        "statusFilter",
        "loading",
        "busySkillId",
        "rowErrorById",
        "installOpen",
        "selectedSkill",
    ):
        require(page, state, f"{state} state")
    require(page, "skillApi.setEnabled", "non-optimistic enabled mutation")
    require(page, "knowflow:react-skills-updated", "mutation event")
    require(page, "sourceKind === \"builtin\"", "builtin filtering")

    dialog = "frontend/react/src/components/SkillInstallDialog.jsx"
    require(dialog, "sourceTab", "install source tabs")
    require(dialog, "phase", "install phase")
    require(dialog, '"preview"', "preview phase")
    require(dialog, "importId", "staged import id")
    require(dialog, "inlineError", "nearby install error")
    require(dialog, "脚本只保存，不执行", "script safety copy")

    drawer = "frontend/react/src/components/SkillDetailDrawer.jsx"
    require(drawer, "skillApi.get", "lazy detail load")
    require(drawer, "skillApi.content", "on-demand content load")
    require(drawer, 'className={"skill-source-view"}', "plain source viewer")
    require(drawer, "skillApi.checkUpdate", "GitHub update check")
    require(drawer, "skillApi.update", "GitHub update")
    require(drawer, "skillApi.delete", "personal Skill delete")

    styles = "frontend/styles.css"
    require(styles, ".skills-list-row", "flat Skill list row")
    require(styles, "@media (max-width: 760px)", "mobile layout guard")
    require(styles, "prefers-reduced-motion", "reduced motion guard")

    for path in (page, dialog, drawer, styles):
        forbid(path, "skills-overview", "Skill statistics overview")
        forbid(path, "dangerouslySetInnerHTML", "unsafe HTML rendering")
        forbid(path, "stats-card", "statistics card")

    print("React Skill management interface contract is present")


if __name__ == "__main__":
    main()
