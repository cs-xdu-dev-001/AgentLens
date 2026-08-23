import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  COMPOSER_PERMISSION_MODES,
  readComposerPermissionMode,
  setComposerPermissionMode,
  subscribeComposerPermissionMode,
} from "./composerPermissions.js";

export function ComposerPermissionPicker({ disabled = false, inputRef = null }) {
  const [mode, setMode] = useState(readComposerPermissionMode);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);

  const selectedMode = useMemo(
    () => COMPOSER_PERMISSION_MODES.find((item) => item.id === mode)
      || COMPOSER_PERMISSION_MODES[0],
    [mode],
  );

  const closePicker = useCallback((restoreInputFocus = false) => {
    setOpen(false);
    if (restoreInputFocus) {
      window.requestAnimationFrame(() => inputRef?.current?.focus());
    }
  }, [inputRef]);

  useEffect(() => subscribeComposerPermissionMode(setMode), []);

  useEffect(() => {
    const handleOutsidePointer = (event) => {
      if (!rootRef.current?.contains(event.target)) closePicker();
    };
    document.addEventListener("pointerdown", handleOutsidePointer);
    return () => document.removeEventListener("pointerdown", handleOutsidePointer);
  }, [closePicker]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = COMPOSER_PERMISSION_MODES.findIndex(
      (item) => item.id === mode,
    );
    setActiveIndex(Math.max(0, selectedIndex));
  }, [mode, open]);

  useEffect(() => {
    const handleOpenRequest = () => {
      if (!disabled) setOpen(true);
    };
    window.addEventListener(
      "knowflow:react-composer-permissions-open",
      handleOpenRequest,
    );
    return () => window.removeEventListener(
      "knowflow:react-composer-permissions-open",
      handleOpenRequest,
    );
  }, [disabled]);

  useEffect(() => {
    if (disabled && open) closePicker();
  }, [closePicker, disabled, open]);

  const chooseMode = (nextMode) => {
    if (disabled) return;
    setMode(setComposerPermissionMode(nextMode));
    closePicker(true);
  };

  const handleKeyDown = (event) => {
    if (disabled) return;
    if (event.key === "Escape" && open) {
      event.preventDefault();
      closePicker();
      triggerRef.current?.focus();
      return;
    }
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => (
        current + direction + COMPOSER_PERMISSION_MODES.length
      ) % COMPOSER_PERMISSION_MODES.length);
      return;
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      chooseMode(COMPOSER_PERMISSION_MODES[activeIndex].id);
    }
  };

  return (
    <div
      className={[
        "composer-model-picker",
        "composer-permission-picker",
        open ? "open" : "",
        `mode-${mode}`,
      ].filter(Boolean).join(" ")}
      ref={rootRef}
      onKeyDown={handleKeyDown}
    >
      <button
        className={"composer-model-trigger composer-permission-trigger"}
        ref={triggerRef}
        type={"button"}
        disabled={disabled}
        aria-label={`切换权限模式，当前为${selectedMode.label}`}
        aria-expanded={open}
        aria-controls={open ? "composer-permission-listbox" : undefined}
        aria-haspopup={"listbox"}
        title={`${selectedMode.description} · Shift+Tab切换`}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={"composer-permission-mark"} aria-hidden={"true"}>
          <svg viewBox={"0 0 16 16"} focusable={"false"}>
            <path d={"M8 1.7 13 3.6v3.5c0 3.1-2 5.7-5 7.2-3-1.5-5-4.1-5-7.2V3.6L8 1.7Z"} />
            <path d={"m5.8 8 1.4 1.4 3-3.1"} />
          </svg>
        </span>
        <span>{selectedMode.label}</span>
        <svg className={"composer-model-chevron"} viewBox={"0 0 16 16"} aria-hidden={"true"} focusable={"false"}>
          <path d={"m4 6 4 4 4-4"} />
        </svg>
      </button>

      {open ? (
        <div className={"composer-model-popover composer-permission-popover"}>
          <div className={"composer-permission-heading"}>
            <strong>{"权限模式"}</strong>
            <span>{"仅影响本次浏览器会话"}</span>
          </div>
          <div
            className={"composer-model-list"}
            id={"composer-permission-listbox"}
            role={"listbox"}
            aria-label={"选择权限模式"}
            aria-activedescendant={`composer-permission-option-${COMPOSER_PERMISSION_MODES[activeIndex].id}`}
          >
            {COMPOSER_PERMISSION_MODES.map((item, index) => {
              const selected = item.id === mode;
              const active = index === activeIndex;
              return (
                <button
                  className={[
                    "composer-model-option",
                    "composer-permission-option",
                    selected ? "selected" : "",
                    active ? "active" : "",
                    item.id === "full_access" ? "danger" : "",
                  ].filter(Boolean).join(" ")}
                  id={`composer-permission-option-${item.id}`}
                  key={item.id}
                  type={"button"}
                  role={"option"}
                  aria-selected={selected}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => chooseMode(item.id)}
                >
                  <span className={"composer-model-copy"}>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                  <span className={"composer-model-check"} aria-hidden={"true"}>
                    {selected ? "✓" : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
