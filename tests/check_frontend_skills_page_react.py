from pathlib import Path
import re


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


def require_in_order(text: str, needles: tuple[str, ...], label: str) -> None:
    position = 0
    for needle in needles:
        found = text.find(needle, position)
        if found < 0:
            raise AssertionError(f"missing or out-of-order {label}: {needle}")
        position = found + len(needle)


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
    page_text = read(page)
    require(page, "mountedRef", "mounted request guard")
    require(page, "activeRef", "active page request guard")
    require(page, "requestGenerationRef", "request generation guard")
    require_in_order(
        page_text,
        (
            "const requestId = ++requestGenerationRef.current;",
            "const items = await skillApi.list();",
            "if (!canCommitRequest(requestId)) return;",
            "setSkills(",
        ),
        "latest-only Skill list success write",
    )
    load_match = re.search(
        r"const loadSkills = useCallback\(async \(\) => \{(?P<body>.*?)\n  \}, "
        r"\[canCommitRequest\]\);",
        page_text,
        flags=re.DOTALL,
    )
    if not load_match:
        raise AssertionError("loadSkills must remain a stable async callback")
    load_body = load_match.group("body")
    if load_body.count("if (!canCommitRequest(requestId)) return;") < 3:
        raise AssertionError(
            "success, error, and finally writes must all use the latest request guard"
        )
    require_in_order(
        load_body,
        (
            "} catch (error) {",
            "if (!canCommitRequest(requestId)) return;",
            "setLoadError(",
            "} finally {",
            "if (!canCommitRequest(requestId)) return;",
            "setLoading(false);",
        ),
        "latest-only Skill list error and loading writes",
    )
    cleanup_match = re.search(
        r"return \(\) => \{\s*mountedRef\.current = false;\s*"
        r"requestGenerationRef\.current \+= 1;\s*\};",
        page_text,
    )
    if not cleanup_match:
        raise AssertionError("unmount must invalidate every in-flight Skill list request")
    require_in_order(
        page_text,
        (
            "activeRef.current = active;",
            "requestGenerationRef.current += 1;",
            "if (active) loadSkills();",
        ),
        "inactive request invalidation before active-only reload",
    )

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
