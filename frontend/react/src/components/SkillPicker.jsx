import { useEffect, useRef } from "react";

function skillLabel(skill) {
  return skill.name || skill.slug || "未命名Skill";
}

export function SkillPicker({
  skills,
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
    <div className={"skill-picker"} data-testid={"skill-picker"}>
      <div
        className={"skill-picker-options"}
        id={"skill-picker-listbox"}
        role={"listbox"}
        aria-label={"Skills"}
        aria-busy={status === "loading"}
      >
        {status === "ready" ? skills.map((skill, index) => {
          const active = index === activeIndex;
          return (
            <button
              className={active ? "skill-picker-option active" : "skill-picker-option"}
              id={`skill-option-${skill.id}`}
              key={skill.id}
              type={"button"}
              role={"option"}
              aria-selected={active}
              tabIndex={-1}
              ref={active ? activeOptionRef : null}
              onMouseDown={(event) => preserveFocus(event, () => onSelect(skill))}
            >
              <span className={"skill-picker-icon"} aria-hidden={"true"}>{"/"}</span>
              <span className={"skill-picker-copy"}>
                <strong>{skillLabel(skill)}</strong>
                <span className={"skill-picker-description"}>
                  {skill.description || skill.slug || "无说明"}
                </span>
              </span>
              <span className={"skill-picker-source"}>
                {skill.sourceKind === "builtin" ? "内置" : "个人"}
              </span>
            </button>
          );
        }) : null}
        {status === "loading" ? (
          <div className={"skill-picker-empty"} role={"status"}>
            {"正在加载Skills…"}
          </div>
        ) : null}
        {status === "error" ? (
          <div className={"skill-picker-empty"} role={"alert"}>
            {"Skills加载失败"}
          </div>
        ) : null}
        {status === "ready" && !skills.length ? (
          <div className={"skill-picker-empty"} role={"status"}>
            {"没有匹配的Skill"}
          </div>
        ) : null}
      </div>
      <div className={"skill-picker-footer"}>
        {status === "error" ? (
          <button
            type={"button"}
            onMouseDown={(event) => event.preventDefault()}
            onClick={onRetry}
          >
            {"重试"}
          </button>
        ) : null}
        {status === "ready" && !skills.length ? (
          <button
            type={"button"}
            onMouseDown={(event) => event.preventDefault()}
            onClick={onManage}
          >
            {"前往安装Skill"}
          </button>
        ) : null}
        <button
          type={"button"}
          onMouseDown={(event) => event.preventDefault()}
          onClick={onManage}
        >
          {"管理Skills"}
        </button>
      </div>
    </div>
  );
}
