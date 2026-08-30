import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  COMPOSER_PERMISSION_BEHAVIORS,
  COMPOSER_PERMISSION_MODES,
  normalizeComposerPermissionRule,
  permissionRuleCount,
  readComposerPermissionMode,
  readComposerPermissionRules,
  setComposerPermissionMode,
  setComposerPermissionRules,
  subscribeComposerPermissionMode,
  subscribeComposerPermissionRules,
  updateComposerPermissionRules,
} from "./composerPermissions.js";

export function ComposerPermissionPicker({ disabled = false, inputRef = null }) {
  const [mode, setMode] = useState(readComposerPermissionMode);
  const [rules, setRules] = useState(readComposerPermissionRules);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [page, setPage] = useState("modes");
  const [ruleBehavior, setRuleBehavior] = useState("allow");
  const [ruleDraft, setRuleDraft] = useState("");
  const [ruleError, setRuleError] = useState("");
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const listboxRef = useRef(null);
  const ruleInputRef = useRef(null);
  const ruleTabRefs = useRef([]);
  const permissionItemCount = COMPOSER_PERMISSION_MODES.length + 1;
  const rulesItemIndex = COMPOSER_PERMISSION_MODES.length;

  const selectedMode = useMemo(
    () => COMPOSER_PERMISSION_MODES.find((item) => item.id === mode)
      || COMPOSER_PERMISSION_MODES[0],
    [mode],
  );

  const closePicker = useCallback((restoreInputFocus = false) => {
    setOpen(false);
    setPage("modes");
    setRuleDraft("");
    setRuleError("");
    if (restoreInputFocus) {
      window.requestAnimationFrame(() => inputRef?.current?.focus());
    }
  }, [inputRef]);

  useEffect(() => subscribeComposerPermissionMode(setMode), []);
  useEffect(() => subscribeComposerPermissionRules(setRules), []);

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
      if (disabled) return;
      setPage("modes");
      setOpen(true);
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
    if (!open || page !== "modes") return;
    window.requestAnimationFrame(() => listboxRef.current?.focus());
  }, [open, page]);

  useEffect(() => {
    if (disabled && open) closePicker();
  }, [closePicker, disabled, open]);

  const chooseMode = (nextMode) => {
    if (disabled) return;
    setMode(setComposerPermissionMode(nextMode));
    closePicker(true);
  };

  const openRules = () => {
    setPage("rules");
    setRuleError("");
    window.requestAnimationFrame(() => ruleInputRef.current?.focus());
  };

  const selectRuleBehavior = (nextBehavior, focus = false) => {
    const index = COMPOSER_PERMISSION_BEHAVIORS.findIndex(
      (item) => item.id === nextBehavior,
    );
    if (index < 0) return;
    setRuleBehavior(nextBehavior);
    setRuleError("");
    if (focus) {
      window.requestAnimationFrame(() => ruleTabRefs.current[index]?.focus());
    }
  };

  const handleRuleTabKeyDown = (event, index) => {
    let nextIndex = index;
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) {
      nextIndex = (index + COMPOSER_PERMISSION_BEHAVIORS.length - 1)
        % COMPOSER_PERMISSION_BEHAVIORS.length;
    } else if (["ArrowRight", "ArrowDown"].includes(event.key)) {
      nextIndex = (index + 1) % COMPOSER_PERMISSION_BEHAVIORS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = COMPOSER_PERMISSION_BEHAVIORS.length - 1;
    } else {
      return;
    }
    event.preventDefault();
    selectRuleBehavior(COMPOSER_PERMISSION_BEHAVIORS[nextIndex].id, true);
  };

  const persistRules = (nextRules) => {
    setRules(setComposerPermissionRules(nextRules));
  };

  const addRule = (event) => {
    event.preventDefault();
    const normalized = normalizeComposerPermissionRule(ruleDraft);
    if (!normalized) {
      setRuleError("输入有效工具名，例如web_search或workspace.*");
      ruleInputRef.current?.focus();
      return;
    }
    persistRules(updateComposerPermissionRules(rules, ruleBehavior, normalized));
    setRuleDraft("");
    setRuleError("");
    ruleInputRef.current?.focus();
  };

  const removeRule = (behavior, toolName) => {
    persistRules(updateComposerPermissionRules(rules, behavior, toolName, true));
  };

  const handleKeyDown = (event) => {
    if (disabled) return;
    if (event.key === "Escape" && open) {
      event.preventDefault();
      if (page === "rules") {
        setPage("modes");
        triggerRef.current?.focus();
        return;
      }
      closePicker();
      triggerRef.current?.focus();
      return;
    }
    if (page !== "modes") return;
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => (
        current + direction + permissionItemCount
      ) % permissionItemCount);
      return;
    }
    if (["Home", "End"].includes(event.key) && open) {
      event.preventDefault();
      setActiveIndex(event.key === "Home" ? 0 : rulesItemIndex);
      return;
    }
    if (["Enter", " "].includes(event.key) && open) {
      event.preventDefault();
      if (activeIndex === rulesItemIndex) openRules();
      else chooseMode(COMPOSER_PERMISSION_MODES[activeIndex].id);
    }
  };

  const activePermissionItemId = activeIndex === rulesItemIndex
    ? "composer-permission-rules-entry"
    : `composer-permission-option-${COMPOSER_PERMISSION_MODES[activeIndex].id}`;

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
        aria-controls={open
          ? page === "modes"
            ? "composer-permission-listbox"
            : "composer-permission-rules"
          : undefined}
        aria-haspopup={"listbox"}
        title={`${selectedMode.description} · Shift+Tab切换`}
        onClick={() => {
          if (open) closePicker();
          else {
            setPage("modes");
            setOpen(true);
          }
        }}
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
          {page === "modes" ? (
            <>
              <div className={"composer-permission-heading"}>
                <strong>{"权限"}</strong>
                <span>{"本次浏览器会话"}</span>
              </div>
              <div
                className={"composer-model-list"}
                id={"composer-permission-listbox"}
                ref={listboxRef}
                role={"listbox"}
                tabIndex={0}
                aria-label={"选择权限模式"}
                aria-activedescendant={activePermissionItemId}
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
                      tabIndex={-1}
                      onFocus={() => setActiveIndex(index)}
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
                <button
                  className={[
                    "composer-permission-rules-entry",
                    activeIndex === rulesItemIndex ? "active" : "",
                  ].filter(Boolean).join(" ")}
                  id={"composer-permission-rules-entry"}
                  type={"button"}
                  role={"option"}
                  aria-selected={false}
                  tabIndex={-1}
                  onFocus={() => setActiveIndex(rulesItemIndex)}
                  onMouseEnter={() => setActiveIndex(rulesItemIndex)}
                  onClick={openRules}
                >
                  <span>
                    <strong>{"工具规则"}</strong>
                    <small>{"Allow / Ask / Deny"}</small>
                  </span>
                  <span aria-hidden={"true"}>{`${permissionRuleCount(rules)}条  ›`}</span>
                </button>
              </div>
            </>
          ) : (
            <div className={"composer-permission-rules"} id={"composer-permission-rules"}>
              <div className={"composer-permission-heading composer-permission-rules-heading"}>
                <button
                  className={"composer-permission-back"}
                  type={"button"}
                  aria-label={"返回权限模式"}
                  onClick={() => setPage("modes")}
                >
                  {"‹"}
                </button>
                <strong>{"工具规则"}</strong>
                <span>{`${permissionRuleCount(rules)}条`}</span>
              </div>
              <div className={"composer-permission-rule-tabs"} role={"tablist"} aria-label={"规则行为"}>
                {COMPOSER_PERMISSION_BEHAVIORS.map((item, index) => (
                  <button
                    className={ruleBehavior === item.id ? "active" : ""}
                    key={item.id}
                    type={"button"}
                    role={"tab"}
                    ref={(node) => {
                      ruleTabRefs.current[index] = node;
                    }}
                    aria-selected={ruleBehavior === item.id}
                    tabIndex={ruleBehavior === item.id ? 0 : -1}
                    onKeyDown={(event) => handleRuleTabKeyDown(event, index)}
                    onClick={() => selectRuleBehavior(item.id)}
                  >
                    {item.label}
                    <span>{rules[item.id].length}</span>
                  </button>
                ))}
              </div>
              <p className={"composer-permission-rule-description"}>
                {COMPOSER_PERMISSION_BEHAVIORS.find((item) => item.id === ruleBehavior)?.description}
              </p>
              <div className={"composer-permission-rule-list"}>
                {rules[ruleBehavior].length ? rules[ruleBehavior].map((rule) => (
                  <div className={"composer-permission-rule-row"} key={`${ruleBehavior}:${rule}`}>
                    <code>{rule}</code>
                    <button
                      type={"button"}
                      aria-label={`删除${rule}规则`}
                      onClick={() => removeRule(ruleBehavior, rule)}
                    >
                      {"删除"}
                    </button>
                  </div>
                )) : (
                  <span className={"composer-permission-rule-empty"}>{"暂无规则"}</span>
                )}
              </div>
              <form className={"composer-permission-rule-add"} onSubmit={addRule}>
                <input
                  ref={ruleInputRef}
                  value={ruleDraft}
                  maxLength={120}
                  aria-label={`添加${ruleBehavior}工具规则`}
                  placeholder={"工具名或前缀*"}
                  onChange={(event) => {
                    setRuleDraft(event.target.value);
                    setRuleError("");
                  }}
                />
                <button type={"submit"}>{"添加"}</button>
              </form>
              {ruleError ? <div className={"composer-permission-rule-error"} role={"alert"}>{ruleError}</div> : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
