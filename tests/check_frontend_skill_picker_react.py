from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    target = ROOT / path
    if not target.exists():
        raise AssertionError(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(f"missing {label} in {path}: {needle}")


def forbid(path: str, needle: str, label: str) -> None:
    if needle in read(path):
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def require_in_order(text: str, needles: tuple[str, ...], label: str) -> None:
    position = 0
    for needle in needles:
        found = text.find(needle, position)
        if found < 0:
            raise AssertionError(f"missing or out-of-order {label}: {needle}")
        position = found + len(needle)


def main() -> None:
    picker = "frontend/react/src/components/SkillPicker.jsx"
    composer = "frontend/react/src/components/ChatComposerForm.jsx"
    styles = "frontend/styles.css"

    for needle, label in [
        ("export function SkillPicker", "SkillPicker component"),
        ("status", "Skill loading status"),
        ("onRetry", "Skill loading retry callback"),
        ('id={"skill-picker-listbox"}', "stable listbox id"),
        ('role={"listbox"}', "listbox role"),
        ('aria-label={"Skills"}', "listbox accessible name"),
        ('aria-busy={status === "loading"}', "listbox loading state"),
        ('{"正在加载Skills…"}', "Skill loading copy"),
        ('{"Skills加载失败"}', "Skill loading error copy"),
        ('{"重试"}', "Skill loading retry copy"),
        ('role={"option"}', "option role"),
        ("`skill-option-${skill.id}`", "stable option id"),
        ("aria-selected={active}", "selected option state"),
        ('className={active ? "skill-picker-option active" : "skill-picker-option"}', "active option class"),
        ("key={skill.id}", "option key"),
        ("event.preventDefault()", "focus-preserving pointer selection"),
        ("onSelect(skill)", "option selection callback"),
        ('{"前往安装Skill"}', "empty-state install action"),
        ('{"管理Skills"}', "management footer"),
        ("onManage", "management callback"),
    ]:
        require(picker, needle, label)
    forbid(picker, "dangerouslySetInnerHTML", "unsafe picker HTML")

    composer_text = read(composer)
    for state in (
        "availableSkills",
        "selectedSkill",
        "pickerOpen",
        "pickerQuery",
        "activeIndex",
        "slashRange",
    ):
        require(composer, state, f"{state} state")
    for needle, label in [
        ('const slashPattern = /(^|\\s)\\/([^\\s/]*)$/;', "slash word-boundary pattern"),
        ("const [activeIndex, setActiveIndex] = useState(-1);", "closed picker active index"),
        ("selectionStart", "cursor-aware slash analysis"),
        ("slice(0, cursor)", "text before cursor only"),
        ("skillApi.list()", "lazy Skill list"),
        ("skill.enabled && skill.available", "enabled and available filtering"),
        ('knowflow:react-skills-updated', "Skill update refresh"),
        ("requestGenerationRef", "latest-request guard"),
        ("mountedRef", "unmount guard"),
        ('const [skillsStatus, setSkillsStatus] = useState("idle");', "Skill request state"),
        ('setSkillsStatus("loading");', "Skill loading transition"),
        ('setSkillsStatus("ready");', "Skill ready transition"),
        ('setSkillsStatus("error");', "Skill error transition"),
        ("skill.name", "name query matching"),
        ("skill.slug", "slug query matching"),
        ("skill.description", "description query matching"),
        ('event.key === "ArrowDown"', "ArrowDown picker navigation"),
        ('event.key === "ArrowUp"', "ArrowUp picker navigation"),
        ('event.key === "Enter"', "Enter picker selection"),
        ('event.key === "Escape"', "Escape picker dismissal"),
        ('event.key === "Backspace"', "Backspace selected Skill removal"),
        ("event.isComposing", "IME composition guard"),
        ("question.slice(0, slashRange.start)", "slash range prefix preservation"),
        ("question.slice(slashRange.end)", "slash range suffix preservation"),
        ("setSelectedSkill(skill)", "selected Skill assignment"),
        ("setSelectionRange(cursor, cursor)", "cursor restoration"),
        ('className={"selected-skill-pill"}', "selected Skill pill"),
        ("removeSelectedSkill", "explicit selected Skill removal"),
        (".detail.skillId = selectedSkill?.id ?? null", "Skill id event payload"),
        ('aria-controls={mentionOpen ? "workspace-mention-listbox" : pickerOpen ? "skill-picker-listbox" : undefined}', "textarea picker controls"),
        ("aria-expanded={mentionOpen || pickerOpen}", "textarea picker expanded state"),
        ('aria-label={"消息"}', "textarea accessible name"),
        ('aria-haspopup={"listbox"}', "textarea popup semantics"),
        ("pickerOpen && activeIndex >= 0 && filteredSkills[activeIndex]", "active option aria guard"),
        ("aria-activedescendant={activeOptionId}", "textarea active descendant"),
        ('detail: { page: "skills" }', "event-driven Skills navigation"),
    ]:
        require(composer, needle, label)
    if composer_text.count(".detail.skillId = selectedSkill?.id ?? null") < 2:
        raise AssertionError("both submit event paths must include selected Skill id")
    if composer_text.count("setActiveIndex(-1);") < 3:
        raise AssertionError(
            "close, slash open, and empty filtering must all clear the active option"
        )
    catch_branch = composer_text.split("} catch {", 1)[1].split("}", 1)[0]
    if "skillsLoadedRef.current = true" in catch_branch:
        raise AssertionError("failed Skill requests must remain retryable")
    require_in_order(
        composer_text,
        (
            "const beforeCursor = value.slice(0, cursor);",
            "const match = beforeCursor.match(slashPattern);",
            "if (!match)",
        ),
        "selectionStart-only slash matching",
    )
    require_in_order(
        composer_text,
        (
            "setQuestion(\"\");",
            "setSelectedSkill(null);",
            "closeSkillPicker();",
        ),
        "composer reset clears question, Skill pill, and picker",
    )
    require_in_order(
        composer_text,
        (
            "const nextSkills = (Array.isArray(skills) ? skills : []).filter(",
            "(skill) => skill.enabled && skill.available,",
            "setAvailableSkills(nextSkills);",
            "setSelectedSkill((current) =>",
            "!nextSkills.some((skill) => skill.id === current.id)",
            "? null",
            ": current",
        ),
        "successful Skill refresh invalidates a stale selection functionally",
    )
    require_in_order(
        composer_text,
        (
            'if (event.key === "ArrowDown") {',
            "if (!filteredSkills.length) return -1;",
            "return current < 0 ? 0 : (current + 1) % filteredSkills.length;",
            'if (event.key === "ArrowUp") {',
            "if (!filteredSkills.length) return -1;",
            "return current < 0",
            "? filteredSkills.length - 1",
            ": (current - 1 + filteredSkills.length) % filteredSkills.length;",
            'if (event.key === "Enter") {',
            "event.preventDefault();",
            "if (activeIndex >= 0 && filteredSkills[activeIndex])",
        ),
        "empty-safe picker keyboard navigation and selection",
    )
    require_in_order(
        composer_text,
        (
            "if (!pickerOpen || !filteredSkills.length) {",
            "setActiveIndex(-1);",
            "return;",
            "setActiveIndex((current) => {",
            "if (current < 0 || current >= filteredSkills.length) return 0;",
            "return current;",
            "}, [filteredSkills, pickerOpen]);",
        ),
        "every filtered option set recomputes the active index",
    )

    for needle, label in [
        (".skill-picker", "picker surface"),
        ("max-height:", "scroll height limit"),
        ("overflow-y: auto", "scrollable option list"),
        (".skill-picker-option.active", "selected option styling"),
        (".skill-picker-description", "ellipsized description"),
        ("text-overflow: ellipsis", "description ellipsis"),
        (".selected-skill-pill", "selected Skill pill styling"),
        (":focus-visible", "keyboard focus styling"),
        ("transform: scale(0.96)", "press feedback"),
        ("@media (prefers-reduced-motion: reduce)", "reduced motion"),
        ("@media (max-width: 760px)", "mobile width guard"),
        ("left: 0", "mobile left containment"),
        ("right: 0", "mobile right containment"),
        (':root[data-theme="mono-dark"] .skill-picker', "dark picker surface"),
    ]:
        require(styles, needle, label)
    for path in (picker, composer):
        forbid(path, "dangerouslySetInnerHTML", "unsafe HTML rendering")
        forbid(path, "stats-card", "statistics card")

    # The slash expression must reject URL/path fragments while accepting a
    # whitespace-delimited command token. Mirror the source expression here.
    pattern = re.compile(r"(^|\s)/([^\s/]*)$")
    assert pattern.search("/")
    assert pattern.search("提问 /skill")
    assert pattern.search("前缀 /skill")
    assert not pattern.search("https://example.com")
    assert not pattern.search("abc/foo")
    assert not pattern.search("abc /foo/bar")

    print("React slash Skill picker contract is present")


if __name__ == "__main__":
    main()
