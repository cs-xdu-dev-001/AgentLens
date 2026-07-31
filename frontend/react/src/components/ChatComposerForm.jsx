import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { skillApi } from "../api/client.js";
import { ComposerModelPicker } from "./ComposerModelPicker.jsx";
import { SkillPicker } from "./SkillPicker.jsx";

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));
const slashPattern = /(^|\s)\/([^\s/]*)$/;

function pickKnowledgeValue(knowledgeBases, currentValue) {
  const wanted = valueOf(currentValue);
  if (knowledgeBases.some((kb) => valueOf(kb.id) === wanted)) return wanted;
  return "";
}

export function ChatComposerForm() {
  const [attachments, setAttachments] = useState([]);
  const [availableSkills, setAvailableSkills] = useState([]);
  const [skillsStatus, setSkillsStatus] = useState("idle");
  const [selectedSkill, setSelectedSkill] = useState(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [slashRange, setSlashRange] = useState(null);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef(null);
  const mountedRef = useRef(false);
  const pickerOpenRef = useRef(false);
  const skillsLoadedRef = useRef(false);
  const requestGenerationRef = useRef(0);

  const resizeTextarea = (node = textareaRef.current) => {
    if (!node) return;
    node.style.height = "auto";
    node.style.height = Math.min(node.scrollHeight, 150) + "px";
  };

  const closeSkillPicker = useCallback(() => {
    setPickerOpen(false);
    setPickerQuery("");
    setActiveIndex(-1);
    setSlashRange(null);
  }, []);

  const loadAvailableSkills = useCallback(async () => {
    const requestId = ++requestGenerationRef.current;
    setSkillsStatus("loading");
    try {
      const skills = await skillApi.list();
      if (!mountedRef.current || requestId !== requestGenerationRef.current) return;
      const nextSkills = (Array.isArray(skills) ? skills : []).filter(
        (skill) => skill.enabled && skill.available,
      );
      setAvailableSkills(nextSkills);
      setSelectedSkill((current) =>
        current && !nextSkills.some((skill) => skill.id === current.id)
          ? null
          : current,
      );
      skillsLoadedRef.current = true;
      setSkillsStatus("ready");
    } catch {
      if (!mountedRef.current || requestId !== requestGenerationRef.current) return;
      skillsLoadedRef.current = false;
      setSkillsStatus("error");
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    pickerOpenRef.current = pickerOpen;
    if (pickerOpen && !skillsLoadedRef.current) loadAvailableSkills();
  }, [loadAvailableSkills, pickerOpen]);

  useEffect(() => {
    const handleSkillsUpdated = () => {
      const shouldRefresh = skillsLoadedRef.current || pickerOpenRef.current;
      skillsLoadedRef.current = false;
      if (shouldRefresh) loadAvailableSkills();
    };
    window.addEventListener("knowflow:react-skills-updated", handleSkillsUpdated);
    return () => window.removeEventListener("knowflow:react-skills-updated", handleSkillsUpdated);
  }, [loadAvailableSkills]);

  useEffect(() => {
    const handleDocumentClick = () => setMenuOpen(false);
    document.addEventListener("click", handleDocumentClick);
    return () => document.removeEventListener("click", handleDocumentClick);
  }, []);

  useEffect(() => {
    const handleComposerMenuClose = () => setMenuOpen(false);
    window.addEventListener("knowflow:react-composer-menu-close", handleComposerMenuClose);
    return () => window.removeEventListener("knowflow:react-composer-menu-close", handleComposerMenuClose);
  }, []);

  useEffect(() => {
    const handleComposerReset = (event) => {
      const shouldFocus = Boolean(event.detail?.focus);
      setQuestion("");
      setSelectedSkill(null);
      closeSkillPicker();
      window.requestAnimationFrame(() => {
        resizeTextarea();
        if (shouldFocus) textareaRef.current?.focus();
      });
    };
    window.addEventListener("knowflow:react-composer-reset", handleComposerReset);
    return () => window.removeEventListener("knowflow:react-composer-reset", handleComposerReset);
  }, [closeSkillPicker]);

  useEffect(() => {
    const handleAttachmentsUpdated = (event) => {
      setAttachments(Array.isArray(event.detail?.attachments) ? event.detail.attachments : []);
    };
    window.addEventListener("knowflow:react-attachments-updated", handleAttachmentsUpdated);
    return () => window.removeEventListener("knowflow:react-attachments-updated", handleAttachmentsUpdated);
  }, []);

  useEffect(() => {
    const handleKnowledgeOptionsUpdated = (event) => {
      const nextKnowledgeBases = Array.isArray(event.detail?.knowledgeBases) ? event.detail.knowledgeBases : [];
      setKnowledgeBases(nextKnowledgeBases);
      setSelectedKnowledgeBaseId((current) =>
        pickKnowledgeValue(nextKnowledgeBases, event.detail?.selectedChatKnowledgeBaseId ?? current),
      );
    };
    const handleKnowledgeSelectionUpdated = (event) => {
      if (!Object.prototype.hasOwnProperty.call(event.detail || {}, "selectedChatKnowledgeBaseId")) return;
      setSelectedKnowledgeBaseId(valueOf(event.detail?.selectedChatKnowledgeBaseId));
    };
    window.addEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated);
    window.addEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated);
    return () => {
      window.removeEventListener("knowflow:react-knowledge-options-updated", handleKnowledgeOptionsUpdated);
      window.removeEventListener("knowflow:react-knowledge-selection-updated", handleKnowledgeSelectionUpdated);
    };
  }, []);

  useEffect(() => {
    const handleSendingUpdated = (event) => setSending(Boolean(event.detail?.sending));
    window.addEventListener("knowflow:react-sending-updated", handleSendingUpdated);
    return () => window.removeEventListener("knowflow:react-sending-updated", handleSendingUpdated);
  }, []);

  const handleComposerMenuToggle = (event) => {
    event.stopPropagation();
    setMenuOpen((current) => !current);
  };
  const handleComposerMenuClick = (event) => event.stopPropagation();

  const handleChatFileChange = (event) => {
    setMenuOpen(false);
    window.dispatchEvent(new CustomEvent("knowflow:react-chat-files-change", { detail: { files: Array.from(event.target.files || []), input: event.target } }));
  };

  const handleComposerKnowledgeBaseChange = (event) => {
    const value = event.target.value || "";
    setSelectedKnowledgeBaseId(value);
    window.dispatchEvent(new CustomEvent("knowflow:react-composer-kb-change", { detail: { value } }));
  };

  const handleChatSubmit = (event) => {
    event.preventDefault();
    const submitEvent = new CustomEvent("knowflow:react-chat-submit", {
      detail: { question: question.trim() },
    });
    submitEvent.detail.skillId = selectedSkill?.id ?? null;
    window.dispatchEvent(submitEvent);
  };

  const updateSkillPicker = (value, cursor) => {
    const beforeCursor = value.slice(0, cursor);
    const match = beforeCursor.match(slashPattern);
    if (!match) {
      closeSkillPicker();
      return;
    }
    const query = match[2];
    setPickerOpen(true);
    setPickerQuery(query);
    setActiveIndex(-1);
    setSlashRange({
      start: cursor - query.length - 1,
      end: cursor,
    });
  };

  const handleChatInput = (event) => {
    const value = event.target.value;
    const cursor = event.target.selectionStart ?? value.length;
    setQuestion(value);
    resizeTextarea(event.target);
    updateSkillPicker(value, cursor);
  };

  const handleChatPaste = (event) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-chat-paste", { detail: { clipboardData: event.clipboardData, preventDefault: () => event.preventDefault() } }));
  };

  const handleChatKeyDown = (event) => {
    if (event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229) return;
    if (pickerOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((current) => {
          if (!filteredSkills.length) return -1;
          return current < 0 ? 0 : (current + 1) % filteredSkills.length;
        });
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) => {
          if (!filteredSkills.length) return -1;
          return current < 0
            ? filteredSkills.length - 1
            : (current - 1 + filteredSkills.length) % filteredSkills.length;
        });
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        if (activeIndex >= 0 && filteredSkills[activeIndex]) {
          selectSkill(filteredSkills[activeIndex]);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeSkillPicker();
        return;
      }
    }
    if (event.key === "Backspace" && !pickerOpen && !question && selectedSkill) {
      event.preventDefault();
      setSelectedSkill(null);
      return;
    }
    if (event.key !== "Enter" || event.shiftKey) return;
    event.preventDefault();
    const submitEvent = new CustomEvent("knowflow:react-chat-enter-submit", {
      detail: { question: question.trim() },
    });
    submitEvent.detail.skillId = selectedSkill?.id ?? null;
    window.dispatchEvent(submitEvent);
  };

  const filteredSkills = useMemo(() => {
    const query = pickerQuery.trim().toLocaleLowerCase();
    if (!query) return availableSkills;
    return availableSkills.filter((skill) =>
      [skill.name, skill.slug, skill.description].some((value) =>
        String(value || "").toLocaleLowerCase().includes(query),
      ),
    );
  }, [availableSkills, pickerQuery]);

  useEffect(() => {
    if (!pickerOpen || !filteredSkills.length) {
      setActiveIndex(-1);
      return;
    }
    setActiveIndex((current) => {
      if (current < 0 || current >= filteredSkills.length) return 0;
      return current;
    });
  }, [filteredSkills, pickerOpen]);

  const selectSkill = (skill) => {
    if (!slashRange) return;
    const nextQuestion =
      question.slice(0, slashRange.start) +
      question.slice(slashRange.end);
    const cursor = slashRange.start;
    setQuestion(nextQuestion);
    setSelectedSkill(skill);
    closeSkillPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
      resizeTextarea(textarea);
    });
  };

  const removeSelectedSkill = () => {
    setSelectedSkill(null);
    textareaRef.current?.focus();
  };

  const handleManageSkills = () => {
    closeSkillPicker();
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
      detail: { page: "skills" },
    }));
  };

  const handleRemoveAttachment = (attachmentId) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-attachment-remove", { detail: { attachmentId } }));
  };

  const composerPlusClassName = menuOpen ? "composer-plus active" : "composer-plus";
  const composerMenuClassName = menuOpen ? "composer-menu open" : "composer-menu";
  const activeOptionId =
    pickerOpen && activeIndex >= 0 && filteredSkills[activeIndex]
      ? `skill-option-${filteredSkills[activeIndex].id}`
      : undefined;

  return (
    <form className={"composer"} id={"chat-form"} onSubmit={handleChatSubmit}>
      {pickerOpen ? (
        <SkillPicker
          skills={filteredSkills}
          status={skillsStatus}
          activeIndex={activeIndex}
          onSelect={selectSkill}
          onRetry={loadAvailableSkills}
          onManage={handleManageSkills}
        />
      ) : null}
      <div className={"attachment-tray"} id={"attachment-tray"}>
        {attachments.map((attachment) => {
          const preview = attachment.previewUrl ? (
            <img className={"attachment-thumb"} src={attachment.previewUrl} alt={""} />
          ) : (
            <span className={"attachment-thumb attachment-file-thumb"}>{String(attachment.fileType || "file").slice(0, 3).toUpperCase()}</span>
          );
          return (
            <span className={"attachment-pill"} key={attachment.attachmentId}>
              {preview}
              <span>{attachment.filename}</span>
              <button
                type={"button"}
                title={"移除附件"}
                aria-label={`移除附件：${attachment.filename}`}
                onClick={() => handleRemoveAttachment(attachment.attachmentId)}
              >
                <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
                  <path
                    d={"M6 6l12 12M18 6 6 18"}
                    fill={"none"}
                    stroke={"currentColor"}
                    strokeWidth={"2"}
                    strokeLinecap={"round"}
                  />
                </svg>
              </button>
            </span>
          );
        })}
      </div>
      <div className={"composer-shell"}>
        <button className={composerPlusClassName} id={"composer-plus-btn"} type={"button"} aria-label={"添加文件或工具"} onClick={handleComposerMenuToggle} disabled={sending}>
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M12 5v14M5 12h14"} />
          </svg>
        </button>
        <div className={composerMenuClassName} id={"composer-menu"} aria-label={"文件与工具菜单"} onClick={handleComposerMenuClick}>
          <section>
            <label className={"menu-card upload-item"}>
              <input id={"chat-file-input"} type={"file"} multiple accept={".txt,.md,.markdown,.pdf,.docx,.xlsx,.xlsm,.pptx,.html,.htm,.json,.csv,.tsv,.yaml,.yml,.xml,.log,.rtf,.png,.jpg,.jpeg,.webp,.gif,.bmp"} onChange={handleChatFileChange} />
              <span className={"menu-icon"} aria-hidden={"true"}>
                <svg viewBox={"0 0 24 24"} focusable={"false"}>
                  <path d={"M12 15V4m0 0L8 8m4-4 4 4"} />
                  <path d={"M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4"} />
                </svg>
              </span>
              <span>
                <strong>{"文件"}</strong>
                <small>{"上传附件"}</small>
              </span>
            </label>
          </section>
          <section className={"composer-settings-panel"} id={"composer-settings-panel"}>
            <div className={"menu-section-title"}>
              <strong>{"知识库"}</strong>
            </div>
            <label className={"menu-select-card knowledge-select-card"}>
              <span>{"范围"}</span>
              <select id={"composer-kb-select"} aria-label={"选择知识库"} value={selectedKnowledgeBaseId} onChange={handleComposerKnowledgeBaseChange}>
                <option value={""}>{"不使用知识库"}</option>
                {knowledgeBases.map((kb) => (
                  <option value={valueOf(kb.id)} key={kb.id}>{kb.name}</option>
                ))}
              </select>
            </label>
            <p className={"composer-menu-summary"} id={"composer-context-summary"}>
              {selectedKnowledgeBaseId ? "已选择知识库" : "未选择知识库"}
            </p>
          </section>
        </div>
        <div className={"composer-input-stack"}>
          {selectedSkill ? (
            <span className={"selected-skill-pill"}>
              <span aria-hidden={"true"}>{"/"}</span>
              <strong>{selectedSkill.name || selectedSkill.slug}</strong>
              <button
                type={"button"}
                aria-label={`移除Skill：${selectedSkill.name || selectedSkill.slug}`}
                onClick={removeSelectedSkill}
              >
                {"×"}
              </button>
            </span>
          ) : null}
          <textarea
            ref={textareaRef}
            name={"question"}
            rows={"1"}
            placeholder={"有问题尽管问。输入 / 选择Skill"}
            value={question}
            disabled={sending}
            aria-controls={pickerOpen ? "skill-picker-listbox" : undefined}
            aria-expanded={pickerOpen}
            aria-haspopup={"listbox"}
            aria-label={"消息"}
            aria-activedescendant={activeOptionId}
            onInput={handleChatInput}
            onPaste={handleChatPaste}
            onKeyDown={handleChatKeyDown}
          />
          <ComposerModelPicker disabled={sending} inputRef={textareaRef} />
        </div>
        <button className={"composer-send-button"} id={"chat-submit-btn"} type={"submit"} aria-label={sending ? "停止生成" : "发送消息"} title={sending ? "停止生成" : "发送消息"}>
          {sending ? <span className={"stop-square"} aria-hidden={"true"}></span> : <svg className={"send-arrow"} viewBox={"0 0 24 24"} aria-hidden={"true"}><path d={"M12 19V5m0 0-6 6m6-6 6 6"} fill={"none"} stroke={"currentColor"} strokeWidth={"2.35"} strokeLinecap={"round"} strokeLinejoin={"round"}></path></svg>}
        </button>
      </div>
    </form>
  );
}
