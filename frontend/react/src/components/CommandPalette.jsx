import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { searchComposerCommands } from "./composerCommands.js";

const modalSelector = 'dialog[open], [aria-modal="true"]';

export function isCommandPaletteShortcut(event) {
  return !event.defaultPrevented && !event.repeat && !event.isComposing
    && event.keyCode !== 229 && !event.altKey && !event.shiftKey
    && Boolean(event.ctrlKey) !== Boolean(event.metaKey)
    && String(event.key || "").toLowerCase() === "k";
}

export function CommandPalette({ commands, disabled = false, onCommand }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const dialogRef = useRef(null);
  const inputRef = useRef(null);
  const closeButtonRef = useRef(null);
  const originRef = useRef(null);
  const items = useMemo(
    () => disabled ? [] : searchComposerCommands(commands, query),
    [commands, disabled, query],
  );
  const selectedIndex = Math.min(activeIndex, items.length - 1);
  const selected = items[selectedIndex];
  const optionId = (command) => `palette-command-${command.value.slice(1)}`;

  const close = useCallback((restoreFocus = true) => {
    dialogRef.current?.close();
    setOpen(false);
    const origin = originRef.current;
    if (restoreFocus && origin?.element?.isConnected) {
      origin.element.focus({ preventScroll: true });
      if (typeof origin.start === "number") {
        origin.element.setSelectionRange(origin.start, origin.end, origin.direction);
      }
    }
  }, []);

  useEffect(() => {
    const show = () => {
      if (document.querySelector(modalSelector)) return;
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
      if (document.querySelector(modalSelector)) return;
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

  useEffect(() => {
    if (!open) return undefined;
    const dialog = dialogRef.current;
    dialog.showModal();
    inputRef.current?.focus({ preventScroll: true });
    return () => dialog.close();
  }, [open]);

  useEffect(() => setActiveIndex(0), [query]);
  useEffect(() => {
    if (selected) document.getElementById(optionId(selected))?.scrollIntoView({ block: "nearest" });
  }, [selected, open]);

  const execute = (command) => {
    if (disabled || !commands.some((item) => item.value === command?.value)) return;
    close(false);
    onCommand(command);
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
            placeholder={"搜索命令或输入 /model…"}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete={"off"}
            spellCheck={false}
          />
          <button ref={closeButtonRef} type={"button"} aria-label={"关闭命令面板"} onClick={() => close()}>Esc</button>
        </div>
        <div className={"command-palette-list"} id={"command-palette-list"} role={"listbox"} aria-label={"可用命令"} aria-busy={disabled}>
          {items.map((command, index) => (
            <button
              key={command.value}
              id={optionId(command)}
              type={"button"}
              role={"option"}
              tabIndex={-1}
              aria-selected={index === selectedIndex}
              className={"command-palette-option"}
              onMouseMove={() => setActiveIndex(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => execute(command)}
            >
              <span>{command.label}</span>
              <code>{command.value}</code>
            </button>
          ))}
        </div>
        <div className={"command-palette-footer"} role={"status"}>
          <span>{disabled ? "正在打开任务，请稍候" : selected?.description || "没有匹配命令，换个关键词试试"}</span>
          {selected ? <kbd>{"↑↓选择 · Enter执行"}</kbd> : null}
        </div>
      </div>
    </dialog>,
    document.body,
  );
}
