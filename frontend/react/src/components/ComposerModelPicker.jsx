import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Fuse from "fuse.js";


const valueOf = (value) => (
  value === undefined || value === null ? "" : String(value)
);

const RECENT_MODELS_KEY = "agentlens.recentChatModels.v1";
const RECENT_MODELS_LIMIT = 5;

function readRecentModelIds() {
  try {
    const value = JSON.parse(window.localStorage.getItem(RECENT_MODELS_KEY) || "[]");
    return Array.isArray(value) ? value.map(valueOf).filter(Boolean).slice(0, RECENT_MODELS_LIMIT) : [];
  } catch {
    return [];
  }
}

function rememberModelId(modelId, current = []) {
  const value = valueOf(modelId);
  if (!value) return current;
  const next = [value, ...current.filter((item) => valueOf(item) !== value)]
    .slice(0, RECENT_MODELS_LIMIT);
  try {
    window.localStorage.setItem(RECENT_MODELS_KEY, JSON.stringify(next));
  } catch {
    // Model selection remains usable when storage is unavailable.
  }
  return next;
}

function protocolLabel(apiMode) {
  return String(apiMode || "").toLocaleLowerCase() === "responses"
    ? "Responses"
    : "Chat Completions";
}

function pickModelId(models, preferredId = "") {
  const wanted = valueOf(preferredId);
  if (models.some((model) => valueOf(model.id) === wanted)) {
    return wanted;
  }
  return models.length ? valueOf(models[0].id) : "";
}

function modelDescription(model) {
  return [model?.provider, model?.modelName, protocolLabel(model?.apiMode)]
    .filter(Boolean)
    .join(" · ");
}

function formatContextTokens(value) {
  const tokens = Math.max(0, Number(value) || 0);
  if (tokens < 1000) return `${Math.round(tokens)} tokens`;
  const compact = (tokens / 1000).toFixed(tokens < 10_000 ? 1 : 0);
  return `${compact.replace(/\.0$/, "")}k tokens`;
}

const REASONING_EFFORTS = Object.freeze([
  { id: "default", label: "自动" },
  { id: "low", label: "快速" },
  { id: "medium", label: "标准" },
  { id: "high", label: "深入" },
  { id: "xhigh", label: "最高" },
]);

export function ComposerModelPicker({
  contextStatus = null,
  disabled = false,
  inputRef = null,
}) {
  const [models, setModels] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("default");
  const [recentModelIds, setRecentModelIds] = useState(readRecentModelIds);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const searchRef = useRef(null);

  const orderedModels = useMemo(() => {
    const rank = new Map(recentModelIds.map((id, index) => [valueOf(id), index]));
    return [...models].sort((left, right) => {
      const selectedDelta = Number(valueOf(right.id) === selectedModelId)
        - Number(valueOf(left.id) === selectedModelId);
      if (selectedDelta) return selectedDelta;
      const leftRank = rank.get(valueOf(left.id)) ?? Number.MAX_SAFE_INTEGER;
      const rightRank = rank.get(valueOf(right.id)) ?? Number.MAX_SAFE_INTEGER;
      return leftRank - rightRank;
    });
  }, [models, recentModelIds, selectedModelId]);

  const visibleModels = useMemo(() => {
    const normalized = query.trim();
    if (!normalized) return orderedModels;
    return new Fuse(orderedModels, {
      threshold: 0.34,
      ignoreLocation: true,
      keys: [
        { name: "name", weight: 3 },
        { name: "modelName", weight: 3 },
        { name: "provider", weight: 1.5 },
        { name: "apiMode", weight: 1 },
      ],
    }).search(normalized).map((result) => result.item);
  }, [orderedModels, query]);

  const selectedModel = useMemo(
    () => models.find(
      (model) => valueOf(model.id) === selectedModelId,
    ) || null,
    [models, selectedModelId],
  );
  const context = useMemo(() => {
    if (!contextStatus || typeof contextStatus !== "object") return null;
    const maxTokens = Math.max(0, Number(contextStatus.maxTokens) || 0);
    if (!maxTokens) return null;
    const usedTokens = Math.max(0, Number(contextStatus.usedTokens) || 0);
    return {
      maxTokens,
      usedTokens,
      remainingTokens: Math.max(
        0,
        Number(contextStatus.remainingTokens) || (maxTokens - usedTokens),
      ),
      percent: Math.max(
        0,
        Math.min(100, Number(contextStatus.usagePercent) || ((usedTokens / maxTokens) * 100)),
      ),
      trimmed: Boolean(contextStatus.trimmed),
    };
  }, [contextStatus]);

  const closePicker = useCallback((restoreInputFocus = false) => {
    setOpen(false);
    setQuery("");
    setActiveIndex(-1);
    if (restoreInputFocus) {
      window.requestAnimationFrame(() => inputRef?.current?.focus());
    }
  }, [inputRef]);

  const openSettings = useCallback(() => {
    closePicker();
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
      detail: { page: "settings" },
    }));
  }, [closePicker]);

  useEffect(() => {
    const handleModelOptionsUpdated = (event) => {
      const nextModels = (
        Array.isArray(event.detail?.models) ? event.detail.models : []
      ).filter((model) => model.modelType === "chat");
      setModels(nextModels);
      setSelectedModelId((current) => pickModelId(
        nextModels,
        event.detail?.selectedModelId ?? current,
      ));
    };
    const handleModelSelectionUpdated = (event) => {
      setSelectedModelId((current) => pickModelId(
        models,
        event.detail?.selectedModelId ?? current,
      ));
    };
    window.addEventListener(
      "knowflow:react-model-options-updated",
      handleModelOptionsUpdated,
    );
    window.addEventListener(
      "knowflow:react-model-selection-updated",
      handleModelSelectionUpdated,
    );
    return () => {
      window.removeEventListener(
        "knowflow:react-model-options-updated",
        handleModelOptionsUpdated,
      );
      window.removeEventListener(
        "knowflow:react-model-selection-updated",
        handleModelSelectionUpdated,
      );
    };
  }, [models]);

  useEffect(() => {
    const handleReasoningUpdated = (event) => {
      const value = String(event.detail?.value || "default");
      if (REASONING_EFFORTS.some((item) => item.id === value)) {
        setReasoningEffort(value);
      }
    };
    window.addEventListener(
      "knowflow:react-reasoning-selection-updated",
      handleReasoningUpdated,
    );
    return () => window.removeEventListener(
      "knowflow:react-reasoning-selection-updated",
      handleReasoningUpdated,
    );
  }, []);

  useEffect(() => {
    const handleOutsidePointer = (event) => {
      if (!rootRef.current?.contains(event.target)) closePicker();
    };
    document.addEventListener("pointerdown", handleOutsidePointer);
    return () => document.removeEventListener(
      "pointerdown",
      handleOutsidePointer,
    );
  }, [closePicker]);

  useEffect(() => {
    if (disabled && open) closePicker();
  }, [closePicker, disabled, open]);

  useEffect(() => {
    const handleOpenRequest = (event) => {
      if (disabled) return;
      if (!models.length) {
        window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
          detail: { page: "settings" },
        }));
        return;
      }
      setOpen(true);
      const focusTarget = {
        context: ".composer-context-section",
        reasoning: ".composer-reasoning-section",
      }[event.detail?.focus];
      if (focusTarget) {
        window.requestAnimationFrame(() => rootRef.current
          ?.querySelector(focusTarget)
          ?.scrollIntoView({ block: "nearest" }));
      }
    };
    window.addEventListener("knowflow:react-composer-model-open", handleOpenRequest);
    return () => window.removeEventListener(
      "knowflow:react-composer-model-open",
      handleOpenRequest,
    );
  }, [disabled, models.length]);

  useEffect(() => {
    const handleShortcut = (event) => {
      if (disabled || event.defaultPrevented || !event.altKey || event.key.toLocaleLowerCase() !== "p") return;
      event.preventDefault();
      if (!models.length) {
        openSettings();
        return;
      }
      setOpen(true);
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [disabled, models.length, openSettings]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = visibleModels.findIndex(
      (model) => valueOf(model.id) === selectedModelId,
    );
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
    window.requestAnimationFrame(() => searchRef.current?.focus());
  }, [open, selectedModelId, visibleModels]);

  const selectModel = (model) => {
    const value = valueOf(model?.id);
    if (!value || disabled) return;
    setSelectedModelId(value);
    setRecentModelIds((current) => rememberModelId(value, current));
    window.dispatchEvent(new CustomEvent(
      "knowflow:react-chat-model-change",
      { detail: { value } },
    ));
    closePicker(true);
  };

  const selectReasoningEffort = (value) => {
    if (disabled || !REASONING_EFFORTS.some((item) => item.id === value)) return;
    setReasoningEffort(value);
    window.dispatchEvent(new CustomEvent(
      "knowflow:react-chat-reasoning-change",
      { detail: { value } },
    ));
  };

  const togglePicker = () => {
    if (disabled) return;
    if (!models.length) {
      openSettings();
      return;
    }
    if (open) {
      closePicker();
      return;
    }
    setOpen(true);
  };

  const handleKeyDown = (event) => {
    if (disabled) return;
    if (event.key === "Escape") {
      if (!open) return;
      event.preventDefault();
      closePicker();
      triggerRef.current?.focus();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setActiveIndex((current) => {
        if (!visibleModels.length) return -1;
        const start = current < 0 ? 0 : current;
        return (start + direction + visibleModels.length) % visibleModels.length;
      });
      return;
    }
    if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      selectModel(visibleModels[activeIndex]);
    }
  };

  const activeOptionId = open && activeIndex >= 0
    ? `composer-model-option-${activeIndex}`
    : undefined;

  return (
    <div
      className={open ? "composer-model-picker open" : "composer-model-picker"}
      ref={rootRef}
      onKeyDown={handleKeyDown}
    >
      <button
        className={"composer-model-trigger"}
        ref={triggerRef}
        type={"button"}
        disabled={disabled}
        aria-label={selectedModel ? `切换模型，当前为${selectedModel.name}` : "配置聊天模型"}
        aria-expanded={open}
        aria-controls={open ? "composer-model-listbox" : undefined}
        aria-haspopup={"listbox"}
        aria-keyshortcuts={"Alt+P"}
        onClick={togglePicker}
      >
        <span className={"composer-model-mark"} aria-hidden={"true"}>
          <svg viewBox={"0 0 16 16"} focusable={"false"}>
            <path d={"M9.2 1.5 4.7 8h3.1l-1 6.5 4.5-7H8.2l1-6Z"} />
          </svg>
        </span>
        <span>{selectedModel?.name || "配置模型"}</span>
        {reasoningEffort !== "default" ? (
          <span className={"composer-reasoning-value"}>
            {REASONING_EFFORTS.find((item) => item.id === reasoningEffort)?.label}
          </span>
        ) : null}
        {context ? (
          <span className={`composer-context-value${context.trimmed ? " trimmed" : ""}`}>
            {context.trimmed ? "已裁剪" : `上下文${Math.round(context.percent)}%`}
          </span>
        ) : null}
        <svg className={"composer-model-chevron"} viewBox={"0 0 16 16"} aria-hidden={"true"} focusable={"false"}>
          <path d={"m4 6 4 4 4-4"} />
        </svg>
      </button>

      {open ? (
        <div className={"composer-model-popover"}>
          <div className={"composer-model-search"}>
            <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
              <circle cx={"8.5"} cy={"8.5"} r={"5.5"} />
              <path d={"m13 13 4 4"} />
            </svg>
            <input
              ref={searchRef}
              type={"search"}
              value={query}
              placeholder={"搜索模型、提供商或协议"}
              aria-label={"搜索聊天模型"}
              role={"combobox"}
              aria-controls={"composer-model-listbox"}
              aria-expanded={true}
              aria-activedescendant={activeOptionId}
              onChange={(event) => setQuery(event.target.value)}
            />
            <kbd>{"Alt P"}</kbd>
          </div>
          <div
            className={"composer-model-list"}
            id={"composer-model-listbox"}
            role={"listbox"}
            aria-label={"选择聊天模型"}
            aria-activedescendant={activeOptionId}
          >
            {visibleModels.map((model, index) => {
              const selected = valueOf(model.id) === selectedModelId;
              const active = index === activeIndex;
              return (
                <button
                  className={[
                    "composer-model-option",
                    selected ? "selected" : "",
                    active ? "active" : "",
                  ].filter(Boolean).join(" ")}
                  id={`composer-model-option-${index}`}
                  key={model.id}
                  type={"button"}
                  role={"option"}
                  aria-selected={selected}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectModel(model)}
                >
                  <span className={"composer-model-copy"}>
                    <strong>{model.name || "未命名模型"}</strong>
                    <small>{modelDescription(model) || "聊天模型"}</small>
                  </span>
                  <span className={"composer-model-check"} aria-hidden={"true"}>
                    {selected ? "✓" : ""}
                  </span>
                </button>
              );
            })}
            {!visibleModels.length ? (
              <div className={"composer-model-empty"} role={"status"}>
                {`没有匹配“${query.trim()}”的模型`}
              </div>
            ) : null}
          </div>
          <div className={"composer-reasoning-section"}>
            <strong>{"推理强度"}</strong>
            <div role={"radiogroup"} aria-label={"推理强度"}>
              {REASONING_EFFORTS.map((item) => (
                <button
                  className={item.id === reasoningEffort ? "selected" : ""}
                  key={item.id}
                  type={"button"}
                  role={"radio"}
                  aria-checked={item.id === reasoningEffort}
                  onClick={() => selectReasoningEffort(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          {context ? (
            <section className={`composer-context-section${context.trimmed ? " trimmed" : ""}`} aria-label={"上下文预算"}>
              <div className={"composer-context-heading"}>
                <strong>{context.trimmed ? "上下文已安全裁剪" : "上下文预算"}</strong>
                <span>{`${Math.round(context.percent)}%`}</span>
              </div>
              <span
                className={"composer-context-track"}
                role={"progressbar"}
                aria-label={"上下文占用"}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(context.percent)}
              >
                <i style={{ transform: `scaleX(${context.percent / 100})` }}></i>
              </span>
              <div className={"composer-context-meta"}>
                <span>{`已用${formatContextTokens(context.usedTokens)}`}</span>
                <span>{`剩余${formatContextTokens(context.remainingTokens)}`}</span>
              </div>
            </section>
          ) : null}
          <button
            className={"composer-model-manage"}
            type={"button"}
            onClick={openSettings}
          >
            <span>{"管理模型"}</span>
            <span aria-hidden={"true"}>{"↗"}</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
