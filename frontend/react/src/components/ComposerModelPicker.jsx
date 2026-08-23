import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";


const valueOf = (value) => (
  value === undefined || value === null ? "" : String(value)
);

function pickModelId(models, preferredId = "") {
  const wanted = valueOf(preferredId);
  if (models.some((model) => valueOf(model.id) === wanted)) {
    return wanted;
  }
  return models.length ? valueOf(models[0].id) : "";
}

function modelDescription(model) {
  return [model?.provider, model?.modelName]
    .filter(Boolean)
    .join(" · ");
}

const REASONING_EFFORTS = Object.freeze([
  { id: "default", label: "自动" },
  { id: "low", label: "快速" },
  { id: "medium", label: "标准" },
  { id: "high", label: "深入" },
  { id: "xhigh", label: "最高" },
]);

export function ComposerModelPicker({ disabled = false, inputRef = null }) {
  const [models, setModels] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("default");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);

  const selectedModel = useMemo(
    () => models.find(
      (model) => valueOf(model.id) === selectedModelId,
    ) || null,
    [models, selectedModelId],
  );

  const closePicker = useCallback((restoreInputFocus = false) => {
    setOpen(false);
    setActiveIndex(-1);
    if (restoreInputFocus) {
      window.requestAnimationFrame(() => inputRef?.current?.focus());
    }
  }, [inputRef]);

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
    const handleOpenRequest = () => {
      if (disabled) return;
      if (!models.length) {
        window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
          detail: { page: "settings" },
        }));
        return;
      }
      setOpen(true);
    };
    window.addEventListener("knowflow:react-composer-model-open", handleOpenRequest);
    return () => window.removeEventListener(
      "knowflow:react-composer-model-open",
      handleOpenRequest,
    );
  }, [disabled, models.length]);

  useEffect(() => {
    if (!open) return;
    const selectedIndex = models.findIndex(
      (model) => valueOf(model.id) === selectedModelId,
    );
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : 0);
  }, [models, open, selectedModelId]);

  const openSettings = () => {
    closePicker();
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
      detail: { page: "settings" },
    }));
  };

  const selectModel = (model) => {
    const value = valueOf(model?.id);
    if (!value || disabled) return;
    setSelectedModelId(value);
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
    setOpen((current) => !current);
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
        if (!models.length) return -1;
        const start = current < 0 ? 0 : current;
        return (start + direction + models.length) % models.length;
      });
      return;
    }
    if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      selectModel(models[activeIndex]);
    }
  };

  const activeOptionId = open && activeIndex >= 0
    ? `composer-model-option-${models[activeIndex]?.id}`
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
        <svg className={"composer-model-chevron"} viewBox={"0 0 16 16"} aria-hidden={"true"} focusable={"false"}>
          <path d={"m4 6 4 4 4-4"} />
        </svg>
      </button>

      {open ? (
        <div className={"composer-model-popover"}>
          <div
            className={"composer-model-list"}
            id={"composer-model-listbox"}
            role={"listbox"}
            aria-label={"选择聊天模型"}
            aria-activedescendant={activeOptionId}
          >
            {models.map((model, index) => {
              const selected = valueOf(model.id) === selectedModelId;
              const active = index === activeIndex;
              return (
                <button
                  className={[
                    "composer-model-option",
                    selected ? "selected" : "",
                    active ? "active" : "",
                  ].filter(Boolean).join(" ")}
                  id={`composer-model-option-${model.id}`}
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
