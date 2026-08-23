import { useEffect, useRef } from "react";

function optionId(option, index) {
  if (option.kind === "command") return `composer-command-${option.command.value.slice(1)}`;
  return `skill-option-${option.skill.id || index}`;
}

export function ComposerSlashPicker({
  options,
  status,
  activeIndex,
  onSelect,
  onRetry,
  onManage,
}) {
  const activeOptionRef = useRef(null);

  useEffect(() => {
    activeOptionRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  const preserveFocus = (event, callback) => {
    event.preventDefault();
    callback();
  };

  return (
    <div className={"skill-picker composer-slash-picker"} data-testid={"composer-slash-picker"}>
      <div
        className={"skill-picker-options"}
        id={"composer-slash-listbox"}
        role={"listbox"}
        aria-label={"命令与Skills"}
        aria-busy={status === "loading"}
      >
        {options.map((option, index) => {
          const active = index === activeIndex;
          const command = option.kind === "command" ? option.command : null;
          const skill = option.kind === "skill" ? option.skill : null;
          const title = command?.value || skill?.name || skill?.slug || "未命名Skill";
          const description = command
            ? `${command.label} · ${command.description}`
            : skill?.description || skill?.slug || "无说明";
          const source = command?.category || (skill?.sourceKind === "builtin" ? "内置Skill" : "个人Skill");
          return (
            <button
              className={active ? "skill-picker-option active" : "skill-picker-option"}
              id={optionId(option, index)}
              key={command?.value || `skill:${skill?.id || index}`}
              type={"button"}
              role={"option"}
              aria-selected={active}
              tabIndex={-1}
              ref={active ? activeOptionRef : null}
              onMouseDown={(event) => preserveFocus(event, () => onSelect(option))}
            >
              <span className={"skill-picker-icon"} aria-hidden={"true"}>{"/"}</span>
              <span className={"skill-picker-copy"}>
                <strong>{title}</strong>
                <span className={"skill-picker-description"}>{description}</span>
              </span>
              <span className={"skill-picker-source"}>{source}</span>
            </button>
          );
        })}
        {status === "loading" ? (
          <div className={"skill-picker-loading"} role={"status"}>{"正在加载Skills…"}</div>
        ) : null}
        {status === "error" && !options.length ? (
          <div className={"skill-picker-empty"} role={"alert"}>{"命令可用，Skills加载失败"}</div>
        ) : null}
        {status === "ready" && !options.length ? (
          <div className={"skill-picker-empty"} role={"status"}>{"没有匹配的命令或Skill"}</div>
        ) : null}
      </div>
      <div className={"skill-picker-footer composer-slash-footer"}>
        <span>{"↑↓选择 · Enter执行 · Tab补全 · Esc关闭"}</span>
        {status === "error" ? (
          <button type={"button"} onMouseDown={(event) => event.preventDefault()} onClick={onRetry}>
            {"重试Skills"}
          </button>
        ) : null}
        <button type={"button"} onMouseDown={(event) => event.preventDefault()} onClick={onManage}>
          {"管理Skills"}
        </button>
      </div>
    </div>
  );
}
