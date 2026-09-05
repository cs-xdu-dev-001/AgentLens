import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Fuse from "fuse.js";
import { searchComposerCommands } from "./composerCommands.js";

const modalSelector = 'dialog[open], [aria-modal="true"]';

export function isCommandPaletteShortcut(event) {
  return !event.defaultPrevented && !event.repeat && !event.isComposing
    && event.keyCode !== 229 && !event.altKey && !event.shiftKey
    && Boolean(event.ctrlKey) !== Boolean(event.metaKey)
    && String(event.key || "").toLowerCase() === "k";
}

function sessionTitle(session) {
  const title = String(session?.title || "").trim();
  if (title && title !== "新会话") return title;
  return String(session?.latest_run?.goalSummary || "新任务").trim() || "新任务";
}

function sessionSearchResults(sessions, query) {
  const available = (Array.isArray(sessions) ? sessions : [])
    .filter((session) => session && String(session.id || "").trim());
  const normalized = String(query || "").trim().toLocaleLowerCase();
  if (!normalized) return available.slice(0, 6);
  const fuse = new Fuse(available.map((session) => ({
    session,
    title: sessionTitle(session),
    goal: String(session.latest_run?.goalSummary || ""),
    id: String(session.id || ""),
  })), {
    threshold: 0.36,
    ignoreLocation: true,
    keys: [
      { name: "title", weight: 4 },
      { name: "goal", weight: 2 },
      { name: "id", weight: 1 },
    ],
  });
  return fuse.search(normalized).slice(0, 8).map((result) => result.item.session);
}

function sessionOptionId(session) {
  const safeId = String(session?.id || "session")
    .replace(/[^a-zA-Z0-9_-]/g, "-")
    .slice(0, 72);
  return `palette-session-${safeId}`;
}

export function CommandPalette({
  commands = [],
  sessions = [],
  disabled = false,
  shortcutEnabled = true,
  onCommand,
  onSessionSelect,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const dialogRef = useRef(null);
  const inputRef = useRef(null);
  const closeButtonRef = useRef(null);
  const originRef = useRef(null);
  const shortcutEnabledRef = useRef(shortcutEnabled);
  const disabledRef = useRef(disabled);
  const restoreFocusFrameRef = useRef(0);
  shortcutEnabledRef.current = shortcutEnabled;
  disabledRef.current = disabled;
  const commandItems = useMemo(
    () => disabled ? [] : searchComposerCommands(commands, query),
    [commands, disabled, query],
  );
  const sessionItems = useMemo(
    () => disabled || !onSessionSelect ? [] : sessionSearchResults(sessions, query),
    [disabled, onSessionSelect, query, sessions],
  );
  const items = useMemo(() => [
    ...commandItems.map((command) => ({ kind: "command", command })),
    ...sessionItems.map((session) => ({ kind: "session", session })),
  ], [commandItems, sessionItems]);
  const selectedIndex = Math.min(activeIndex, items.length - 1);
  const selected = items[selectedIndex];
  const optionId = (item) => item?.kind === "session"
    ? sessionOptionId(item.session)
    : `palette-command-${item.command.value.slice(1)}`;

  const close = useCallback((restoreFocus = true) => {
    if (restoreFocusFrameRef.current) {
      window.cancelAnimationFrame(restoreFocusFrameRef.current);
      restoreFocusFrameRef.current = 0;
    }
    dialogRef.current?.close();
    setOpen(false);
    const origin = originRef.current;
    if (restoreFocus && origin?.element?.isConnected) {
      const restore = () => {
        if (!origin.element?.isConnected || typeof origin.element.focus !== "function") return;
        origin.element.focus({ preventScroll: true });
        if (typeof origin.start === "number" && typeof origin.element.setSelectionRange === "function") {
          origin.element.setSelectionRange(origin.start, origin.end, origin.direction);
        }
      };
      // Native dialog close can restore focus after the React handler returns;
      // reclaim it on the next frame as well so keyboard flows stay deterministic.
      restore();
      restoreFocusFrameRef.current = window.requestAnimationFrame(() => {
        restoreFocusFrameRef.current = 0;
        restore();
      });
    }
  }, []);

  useEffect(() => {
    const show = () => {
      if (!shortcutEnabledRef.current || disabledRef.current || document.querySelector(modalSelector)) return;
      if (restoreFocusFrameRef.current) {
        window.cancelAnimationFrame(restoreFocusFrameRef.current);
        restoreFocusFrameRef.current = 0;
      }
      const element = document.activeElement;
      originRef.current = {
        element,
        start: element?.selectionStart,
        end: element?.selectionEnd,
        direction: element?.selectionDirection,
      };
      setQuery("");
      setActiveIndex(0);
      setOpen(true);
    };
    const onShortcut = (event) => {
      if (!isCommandPaletteShortcut(event)) return;
      if (!shortcutEnabledRef.current || disabledRef.current || document.querySelector(modalSelector)) return;
      event.preventDefault();
      show();
    };
    window.addEventListener("keydown", onShortcut);
    window.addEventListener("knowflow:react-command-palette-open", show);
    return () => {
      window.removeEventListener("keydown", onShortcut);
      window.removeEventListener("knowflow:react-command-palette-open", show);
    };
  }, []);

  useEffect(() => () => {
    if (restoreFocusFrameRef.current) {
      window.cancelAnimationFrame(restoreFocusFrameRef.current);
      restoreFocusFrameRef.current = 0;
    }
  }, []);

  useEffect(() => {
    if (!shortcutEnabled && open) close(false);
  }, [close, open, shortcutEnabled]);

  useEffect(() => {
    if (!open) return undefined;
    const dialog = dialogRef.current;
    if (!dialog) return undefined;
    if (!dialog.open) dialog.showModal();
    inputRef.current?.focus({ preventScroll: true });
    return () => dialog.close();
  }, [open]);

  useEffect(() => setActiveIndex(0), [query]);
  useEffect(() => {
    if (selected) document.getElementById(optionId(selected))?.scrollIntoView({ block: "nearest" });
  }, [selected, open]);

  const execute = (item) => {
    if (disabled || !item) return;
    if (item.kind === "session") {
      if (!onSessionSelect) return;
      close(false);
      onSessionSelect(item.session);
      return;
    }
    const command = item.command;
    if (!commands.some((entry) => entry.value === command?.value)) return;
    close(false);
    onCommand?.(command);
  };

  const handleKeyDown = (event) => {
    // Only this modal owns keyboard input; do not also fire workbench shortcuts.
    event.stopPropagation();
    if (event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229) return;
    if (event.key === "Escape" || isCommandPaletteShortcut(event)) {
      event.preventDefault();
      close();
    } else if (event.key === "Tab") {
      event.preventDefault();
      (document.activeElement === inputRef.current ? closeButtonRef : inputRef).current?.focus();
    } else if (event.target === inputRef.current) {
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        if (items.length) setActiveIndex((current) => (
          (Math.min(current, items.length - 1) + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length
        ));
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (selected) execute(selected);
      }
    }
  };

  if (!open) return null;
  return createPortal(
    <dialog
      ref={dialogRef}
      className={"command-palette"}
      id={"command-palette"}
      aria-label={"命令面板"}
      onKeyDown={handleKeyDown}
      onCancel={(event) => { event.preventDefault(); close(); }}
      onClick={(event) => { if (event.target === event.currentTarget) close(); }}
    >
      <div className={"command-palette-surface"}>
        <div className={"command-palette-search"}>
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"}><circle cx={"10.5"} cy={"10.5"} r={"6.5"} /><path d={"m16 16 4 4"} /></svg>
          <input
            ref={inputRef}
            role={"combobox"}
            aria-label={"搜索命令"}
            aria-autocomplete={"list"}
            aria-expanded={true}
            aria-controls={"command-palette-list"}
            aria-activedescendant={selected ? optionId(selected) : undefined}
            placeholder={"搜索命令、任务或输入 /model…"}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete={"off"}
            spellCheck={false}
          />
          <button ref={closeButtonRef} type={"button"} aria-label={"关闭命令面板"} onClick={() => close()}>Esc</button>
        </div>
        <div className={"command-palette-list"} id={"command-palette-list"} role={"listbox"} aria-label={"可用命令与最近任务"} aria-busy={disabled}>
          {items.map((item, index) => (
            <div key={item.kind === "session" ? `session-${item.session.id}` : item.command.value}>
              {item.kind === "session"
                && (index === 0 || items[index - 1]?.kind !== "session") ? (
                  <div className={"command-palette-group-label"}>最近任务</div>
                ) : null}
              {item.kind === "command"
                && (index === 0
                  || items[index - 1]?.kind !== "command"
                  || items[index - 1]?.command?.category !== item.command.category) ? (
                  <div className={"command-palette-group-label"}>{item.command.category || "命令"}</div>
                ) : null}
              <button
                id={optionId(item)}
                type={"button"}
                role={"option"}
                tabIndex={-1}
                aria-selected={index === selectedIndex}
                className={item.kind === "session" ? "command-palette-option palette-session-option" : "command-palette-option"}
                onMouseMove={() => setActiveIndex(index)}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => execute(item)}
              >
                {item.kind === "session" ? (
                  <span className={"palette-session-copy"}>
                    <span className={"palette-session-title"}>{sessionTitle(item.session)}</span>
                    {item.session.latest_run?.goalSummary ? (
                      <small>{String(item.session.latest_run.goalSummary)}</small>
                    ) : null}
                  </span>
                ) : (
                  <span className={"palette-command-copy"}>
                    <span className={"palette-command-label"}>{item.command.label}</span>
                    {item.command.description ? (
                      <small>{item.command.description}</small>
                    ) : null}
                  </span>
                )}
                <code>{item.kind === "session" ? "任务" : item.command.value}</code>
              </button>
            </div>
          ))}
          {!items.length ? (
            <div className={"command-palette-empty"} role={"status"}>
              <span className={"command-palette-empty-mark"} aria-hidden={"true"}>
                <svg viewBox={"0 0 24 24"}><circle cx={"10.5"} cy={"10.5"} r={"6.5"} /><path d={"m16 16 4 4"} /></svg>
              </span>
              <strong>{disabled ? "正在打开任务" : "没有匹配结果"}</strong>
              <span>{disabled ? "请稍候，任务列表正在同步。" : "换个关键词，或输入/查看可用命令。"}</span>
            </div>
          ) : null}
        </div>
        <div className={"command-palette-footer"} role={"status"}>
          <span>
            {disabled
              ? "正在打开任务，请稍候"
              : selected?.kind === "session"
                ? `打开任务：${sessionTitle(selected.session)}`
                : selected?.command?.description || "没有匹配命令，换个关键词试试"}
          </span>
          {selected ? <kbd>{"↑↓选择 · Enter执行"}</kbd> : null}
        </div>
      </div>
    </dialog>,
    document.body,
  );
}
