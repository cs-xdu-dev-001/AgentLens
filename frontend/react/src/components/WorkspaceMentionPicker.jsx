import { useEffect, useRef } from "react";

export function WorkspaceMentionPicker({ paths, status, activeIndex, onSelect, onRetry }) {
  const activeOptionRef = useRef(null);

  useEffect(() => {
    activeOptionRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  return (
    <div className={"skill-picker workspace-mention-picker"} data-testid={"workspace-mention-picker"}>
      <div
        className={"skill-picker-options"}
        id={"workspace-mention-listbox"}
        role={"listbox"}
        aria-label={"工作区文件"}
        aria-busy={status === "loading"}
      >
        {status === "ready" ? paths.map((path, index) => {
          const active = index === activeIndex;
          const directory = path.endsWith("/");
          return (
            <button
              className={active ? "skill-picker-option active" : "skill-picker-option"}
              id={`workspace-mention-${index}`}
              key={path}
              type={"button"}
              role={"option"}
              aria-selected={active}
              tabIndex={-1}
              ref={active ? activeOptionRef : null}
              onMouseDown={(event) => {
                event.preventDefault();
                onSelect(path);
              }}
            >
              <span className={"skill-picker-icon"} aria-hidden={"true"}>{"@"}</span>
              <span className={"skill-picker-copy"}>
                <strong>{path}</strong>
              </span>
              <span className={"skill-picker-source"}>{directory ? "目录" : "文件"}</span>
            </button>
          );
        }) : null}
        {status === "loading" ? <div className={"skill-picker-empty"} role={"status"}>{"正在索引工作区…"}</div> : null}
        {status === "error" ? <div className={"skill-picker-empty"} role={"alert"}>{"工作区索引失败"}</div> : null}
        {status === "ready" && !paths.length ? <div className={"skill-picker-empty"} role={"status"}>{"没有匹配的文件"}</div> : null}
      </div>
      {status === "error" ? (
        <div className={"skill-picker-footer"}>
          <button type={"button"} onMouseDown={(event) => event.preventDefault()} onClick={onRetry}>{"重试"}</button>
        </div>
      ) : null}
    </div>
  );
}
