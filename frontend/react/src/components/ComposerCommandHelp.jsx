import { useEffect, useMemo, useRef, useState } from "react";

const HELP_TABS = Object.freeze([
  { id: "shortcuts", label: "快捷键" },
  { id: "commands", label: "内置命令" },
  { id: "skills", label: "Skills" },
]);

const WEB_SHORTCUTS = Object.freeze([
  { value: "Ctrl/⌘+K", label: "命令面板", description: "从任意页面搜索并执行现有命令" },
  { value: "Alt+T", label: "打开运行面板", description: "查看当前任务状态和恢复操作" },
  { value: "Alt+E", label: "查看运行过程", description: "直达步骤、工具调用和错误详情" },
  { value: "Alt+G", label: "查看文件变更", description: "直达本轮新增、修改和删除内容" },
  { value: "Ctrl/⌘+F", label: "搜索对话", description: "查找当前对话中实际显示的内容" },
  { value: "Ctrl/⌘+S", label: "暂存或恢复草稿", description: "临时收起输入内容，再次按下即可恢复" },
  { value: "Shift+Tab", label: "切换权限模式", description: "在计划、询问、自动编辑和完全访问间切换" },
  { value: "Esc×2", label: "从历史继续", description: "空输入框下快速回到最近问题并创建分支" },
]);

function normalize(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function matchesQuery(item, query) {
  if (!query) return true;
  return [
    item.value,
    item.label,
    item.description,
    item.category,
    item.name,
    item.slug,
  ].some((value) => normalize(value).includes(query));
}

function helpItemId(tab, item, index) {
  const identity = item.value || item.id || item.slug || index;
  return `composer-help-${tab}-${String(identity).replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

export function ComposerCommandHelp({
  commands,
  skills,
  skillsStatus,
  onClose,
  onCommand,
  onSkill,
  onRetrySkills,
  onManageSkills,
}) {
  const [tab, setTab] = useState("shortcuts");
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const searchRef = useRef(null);
  const activeItemRef = useRef(null);

  const groups = useMemo(() => ({
    shortcuts: WEB_SHORTCUTS,
    commands,
    skills,
  }), [commands, skills]);
  const normalizedQuery = normalize(query);
  const items = useMemo(
    () => (groups[tab] || []).filter((item) => matchesQuery(item, normalizedQuery)),
    [groups, normalizedQuery, tab],
  );

  useEffect(() => {
    searchRef.current?.focus();
  }, []);

  useEffect(() => {
    setActiveIndex(items.length ? 0 : -1);
  }, [items, tab]);

  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const selectTab = (nextTab) => {
    setTab(nextTab);
    setActiveIndex(0);
    window.requestAnimationFrame(() => searchRef.current?.focus());
  };

  const takeItem = (item) => {
    if (!item || tab === "shortcuts") return;
    if (tab === "skills") onSkill(item);
    else onCommand(item);
  };

  const handleKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      if (event.target === searchRef.current && query) return;
      event.preventDefault();
      const current = HELP_TABS.findIndex((item) => item.id === tab);
      const delta = event.key === "ArrowLeft" ? -1 : 1;
      selectTab(HELP_TABS[(current + delta + HELP_TABS.length) % HELP_TABS.length].id);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!items.length) return;
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => (current + delta + items.length) % items.length);
      return;
    }
    if (event.key === "Enter" && tab !== "shortcuts" && items[activeIndex]) {
      event.preventDefault();
      takeItem(items[activeIndex]);
    }
  };

  const emptyCopy = query
    ? "没有匹配项，换个关键词试试"
    : tab === "skills"
      ? "当前没有可用Skill，可前往Skills页面安装"
      : "当前分组没有可用内容";

  return (
    <section
      className={"composer-command-help"}
      data-testid={"composer-command-help"}
      aria-label={"AgentLens命令帮助"}
      onKeyDown={handleKeyDown}
    >
      <div className={"composer-command-help-heading"}>
        <strong>{"AgentLens帮助"}</strong>
        <button type={"button"} onClick={onClose} aria-label={"关闭命令帮助"}>{"关闭"}</button>
      </div>
      <div className={"composer-command-help-tabs"} role={"tablist"} aria-label={"帮助分组"}>
        {HELP_TABS.map((item) => (
          <button
            key={item.id}
            id={`composer-help-tab-${item.id}`}
            className={tab === item.id ? "active" : ""}
            type={"button"}
            role={"tab"}
            aria-selected={tab === item.id}
            aria-controls={"composer-help-listbox"}
            onClick={() => selectTab(item.id)}
          >
            {`${item.label} ${groups[item.id]?.length || 0}`}
          </button>
        ))}
      </div>
      <label className={"composer-command-help-search"}>
        <input
          ref={searchRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label={"搜索命令、快捷键或Skills"}
          placeholder={"搜索命令、快捷键或Skills"}
          autoComplete={"off"}
          spellCheck={false}
        />
      </label>
      <div
        className={"composer-command-help-list"}
        id={"composer-help-listbox"}
        role={tab === "shortcuts" ? "list" : "listbox"}
        aria-labelledby={`composer-help-tab-${tab}`}
        aria-busy={tab === "skills" && skillsStatus === "loading"}
      >
        {items.map((item, index) => {
          const active = index === activeIndex;
          const title = item.value || item.name || item.slug || "未命名Skill";
          const label = item.label || item.description || item.slug || "无说明";
          const description = item.description && item.label ? item.description : "";
          const source = tab === "commands"
            ? item.category
            : tab === "skills"
              ? item.sourceKind === "builtin" ? "内置Skill" : "个人Skill"
              : "快捷键";
          const Tag = tab === "shortcuts" ? "div" : "button";
          return (
            <Tag
              key={`${tab}:${item.value || item.id || item.slug || index}`}
              id={helpItemId(tab, item, index)}
              className={active ? "composer-command-help-item active" : "composer-command-help-item"}
              {...(tab === "shortcuts" ? {
                role: "listitem",
              } : {
                type: "button",
                role: "option",
                "aria-selected": active,
                onClick: () => takeItem(item),
              })}
              ref={active ? activeItemRef : null}
            >
              <code>{title}</code>
              <span className={"composer-command-help-copy"}>
                <strong>{label}</strong>
                {description ? <span>{description}</span> : null}
              </span>
              <span className={"composer-command-help-source"}>{source}</span>
            </Tag>
          );
        })}
        {tab === "skills" && skillsStatus === "loading" ? (
          <div className={"composer-command-help-state"} role={"status"}>{"正在加载Skills…"}</div>
        ) : null}
        {!items.length && !(tab === "skills" && skillsStatus === "loading") ? (
          <div className={"composer-command-help-state"} role={skillsStatus === "error" ? "alert" : "status"}>
            {skillsStatus === "error" && tab === "skills" ? "Skills加载失败，可重试或前往管理" : emptyCopy}
          </div>
        ) : null}
      </div>
      <div className={"composer-command-help-footer"}>
        <span>{"←→切换分组 · ↑↓选择 · Enter取用 · Esc关闭"}</span>
        {tab === "skills" && skillsStatus === "error" ? (
          <button type={"button"} onClick={onRetrySkills}>{"重试Skills"}</button>
        ) : null}
        {tab === "skills" ? (
          <button type={"button"} onClick={onManageSkills}>{"管理Skills"}</button>
        ) : null}
      </div>
    </section>
  );
}
