import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { skillApi, workspaceApi } from "../api/client.js";
import { ComposerModelPicker } from "./ComposerModelPicker.jsx";
import { ComposerSlashPicker } from "./ComposerSlashPicker.jsx";
import {
  composerCommandSuggestions,
  resolveComposerCommand,
} from "./composerCommands.js";
import {
  applyWorkspaceMention,
  workspaceMentionAtCursor,
  workspaceMentionCommonPrefix,
  workspaceMentionSuggestions,
} from "./composerMentions.js";
import { WorkspaceMentionPicker } from "./WorkspaceMentionPicker.jsx";

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));
const slashPattern = /(^|\s)\/([^\s/]*)$/;
const queuePriorityLabels = Object.freeze({ now: "立即", next: "接下来", later: "稍后" });
const queueBlockLabels = Object.freeze({
  approval: "等待权限确认",
  question: "等待你的回答",
  run: "等待当前任务继续",
  failed: "发送失败，队列已暂停",
  cancelled: "已停止，待发送已暂停",
});
const idleAgentState = Object.freeze({
  mode: "idle",
  label: "就绪",
  detail: "",
  actionable: false,
});

function pickKnowledgeValue(knowledgeBases, currentValue) {
  const wanted = valueOf(currentValue);
  if (knowledgeBases.some((kb) => valueOf(kb.id) === wanted)) return wanted;
  return "";
}

async function collectWorkspaceMentionPaths() {
  const index = await workspaceApi.mentions();
  return Array.isArray(index?.paths) ? index.paths : [];
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
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionStatus, setMentionStatus] = useState("idle");
  const [mentionPaths, setMentionPaths] = useState([]);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionRange, setMentionRange] = useState(null);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(-1);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [sending, setSending] = useState(false);
  const [queuedChats, setQueuedChats] = useState([]);
  const [queuePaused, setQueuePaused] = useState(false);
  const [queueBlockReason, setQueueBlockReason] = useState("");
  const [switchingSession, setSwitchingSession] = useState(false);
  const [agentState, setAgentState] = useState(idleAgentState);
  const textareaRef = useRef(null);
  const mountedRef = useRef(false);
  const pickerOpenRef = useRef(false);
  const skillsLoadedRef = useRef(false);
  const mentionsLoadedRef = useRef(false);
  const mentionsLoadedAtRef = useRef(0);
  const requestGenerationRef = useRef(0);
  const agentStateResetRef = useRef(null);

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

  const closeMentionPicker = useCallback(() => {
    setMentionOpen(false);
    setMentionQuery("");
    setMentionRange(null);
    setMentionActiveIndex(-1);
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

  const loadWorkspaceMentions = useCallback(async () => {
    setMentionStatus("loading");
    try {
      const paths = await collectWorkspaceMentionPaths();
      if (!mountedRef.current) return;
      setMentionPaths(paths);
      mentionsLoadedRef.current = true;
      mentionsLoadedAtRef.current = Date.now();
      setMentionStatus("ready");
    } catch {
      if (!mountedRef.current) return;
      mentionsLoadedRef.current = false;
      setMentionStatus("error");
    }
  }, []);

  useEffect(() => {
    const handleComposerFocus = () => {
      window.requestAnimationFrame(() => textareaRef.current?.focus());
    };
    window.addEventListener("knowflow:react-composer-focus", handleComposerFocus);
    return () => window.removeEventListener("knowflow:react-composer-focus", handleComposerFocus);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const handleSessionSwitchState = (event) => {
      setSwitchingSession(event.detail?.status === "loading");
    };
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
    return () => window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
  }, []);

  useEffect(() => {
    pickerOpenRef.current = pickerOpen;
    if (pickerOpen && !skillsLoadedRef.current) loadAvailableSkills();
  }, [loadAvailableSkills, pickerOpen]);

  useEffect(() => {
    const stale = Date.now() - mentionsLoadedAtRef.current >= 5_000;
    if (mentionOpen && (!mentionsLoadedRef.current || stale) && mentionStatus !== "loading") {
      loadWorkspaceMentions();
    }
  }, [loadWorkspaceMentions, mentionOpen, mentionStatus]);

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
      closeMentionPicker();
      window.requestAnimationFrame(() => {
        resizeTextarea();
        if (shouldFocus) textareaRef.current?.focus();
      });
    };
    window.addEventListener("knowflow:react-composer-reset", handleComposerReset);
    return () => window.removeEventListener("knowflow:react-composer-reset", handleComposerReset);
  }, [closeMentionPicker, closeSkillPicker]);

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

  useEffect(() => {
    const clearAgentStateTimer = () => {
      if (!agentStateResetRef.current) return;
      window.clearTimeout(agentStateResetRef.current);
      agentStateResetRef.current = null;
    };
    const handleAgentComposerState = (event) => {
      clearAgentStateTimer();
      const detail = event.detail || {};
      const next = {
        mode: String(detail.mode || "idle"),
        label: String(detail.label || "就绪"),
        detail: String(detail.detail || ""),
        actionable: Boolean(detail.actionable),
      };
      setAgentState((current) => (
        current.mode === next.mode
        && current.label === next.label
        && current.detail === next.detail
        && current.actionable === next.actionable
          ? current
          : next
      ));
      if (["completed", "cancelled"].includes(next.mode)) {
        agentStateResetRef.current = window.setTimeout(() => {
          agentStateResetRef.current = null;
          setAgentState(idleAgentState);
        }, 2400);
      }
    };
    window.addEventListener(
      "knowflow:react-agent-composer-state",
      handleAgentComposerState,
    );
    return () => {
      clearAgentStateTimer();
      window.removeEventListener(
        "knowflow:react-agent-composer-state",
        handleAgentComposerState,
      );
    };
  }, []);

  useEffect(() => {
    const handleQueueUpdated = (event) => {
      setQueuedChats(Array.isArray(event.detail?.items) ? event.detail.items : []);
      setQueuePaused(Boolean(event.detail?.paused));
      setQueueBlockReason(String(event.detail?.blockedReason || ""));
    };
    window.addEventListener("knowflow:react-chat-queue-updated", handleQueueUpdated);
    return () => window.removeEventListener("knowflow:react-chat-queue-updated", handleQueueUpdated);
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
    if (switchingSession) return;
    const command = resolveComposerCommand(question);
    if (command) {
      setQuestion("");
      closeSkillPicker();
      runComposerCommand(command);
      window.requestAnimationFrame(() => resizeTextarea());
      return;
    }
    const submitEvent = new CustomEvent("knowflow:react-chat-submit", {
      detail: { question: question.trim() },
    });
    submitEvent.detail.skillId = selectedSkill?.id ?? null;
    window.dispatchEvent(submitEvent);
  };

  const handleStopClick = (event) => {
    event?.preventDefault();
    window.dispatchEvent(new CustomEvent("knowflow:react-chat-stop"));
  };

  const handleQueueAction = (action, requestId = null, priority = null) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-chat-queue-action", {
      detail: { action, requestId, priority },
    }));
  };

  const handleOpenAgentWorkbench = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
  };

  const runComposerCommand = (command) => {
    const pageActions = new Set([
      "knowledge",
      "workspace",
      "tools",
      "skills",
      "memory",
      "settings",
    ]);
    if (pageActions.has(command.action)) {
      window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
        detail: { page: command.action },
      }));
      return;
    }
    if (command.action === "new-chat") {
      window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
      return;
    }
    if (command.action === "model") {
      window.dispatchEvent(new CustomEvent("knowflow:react-composer-model-open"));
      return;
    }
    if (command.action === "tasks") {
      handleOpenAgentWorkbench();
      return;
    }
    if (command.action === "stop") handleStopClick();
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

  const updateComposerPicker = (value, cursor) => {
    const beforeCursor = value.slice(0, cursor);
    if (beforeCursor.match(slashPattern)) {
      closeMentionPicker();
      updateSkillPicker(value, cursor);
      return;
    }
    closeSkillPicker();
    const mention = workspaceMentionAtCursor(value, cursor);
    if (!mention) {
      closeMentionPicker();
      return;
    }
    setMentionOpen(true);
    setMentionQuery(mention.query);
    setMentionRange({ start: mention.start, end: mention.end });
    setMentionActiveIndex(-1);
  };

  const handleChatInput = (event) => {
    const value = event.target.value;
    const cursor = event.target.selectionStart ?? value.length;
    setQuestion(value);
    resizeTextarea(event.target);
    updateComposerPicker(value, cursor);
  };

  const handleChatPaste = (event) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-chat-paste", { detail: { clipboardData: event.clipboardData, preventDefault: () => event.preventDefault() } }));
  };

  const handleChatKeyDown = (event) => {
    if (event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229) return;
    if (mentionOpen) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        setMentionActiveIndex((current) => {
          if (!filteredMentionPaths.length) return -1;
          if (event.key === "ArrowDown") return current < 0 ? 0 : (current + 1) % filteredMentionPaths.length;
          return current < 0
            ? filteredMentionPaths.length - 1
            : (current - 1 + filteredMentionPaths.length) % filteredMentionPaths.length;
        });
        return;
      }
      if (["Enter", "Tab"].includes(event.key)
        || (event.key === "ArrowRight" && event.currentTarget.selectionStart === question.length)) {
        event.preventDefault();
        if (event.key === "Tab") completeWorkspaceMention();
        else {
          const selected = filteredMentionPaths[mentionActiveIndex];
          if (selected) selectWorkspaceMention(selected);
        }
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeMentionPicker();
        return;
      }
    }
    if (pickerOpen) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((current) => {
          if (!slashOptions.length) return -1;
          return current < 0 ? 0 : (current + 1) % slashOptions.length;
        });
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((current) => {
          if (!slashOptions.length) return -1;
          return current < 0
            ? slashOptions.length - 1
            : (current - 1 + slashOptions.length) % slashOptions.length;
        });
        return;
      }
      if (event.key === "Tab") {
        event.preventDefault();
        if (activeIndex >= 0 && slashOptions[activeIndex]) {
          completeSlashOption(slashOptions[activeIndex]);
        }
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        if (activeIndex >= 0 && slashOptions[activeIndex]) {
          selectSlashOption(slashOptions[activeIndex]);
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
    const command = resolveComposerCommand(question);
    if (command) {
      setQuestion("");
      closeSkillPicker();
      runComposerCommand(command);
      window.requestAnimationFrame(() => resizeTextarea());
      return;
    }
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

  const filteredCommands = useMemo(
    () => composerCommandSuggestions(pickerQuery, { sending }),
    [pickerQuery, sending],
  );

  const slashOptions = useMemo(() => [
    ...filteredCommands.map((command) => ({ kind: "command", command })),
    ...filteredSkills.map((skill) => ({ kind: "skill", skill })),
  ], [filteredCommands, filteredSkills]);

  const filteredMentionPaths = useMemo(
    () => workspaceMentionSuggestions(mentionPaths, mentionQuery),
    [mentionPaths, mentionQuery],
  );

  useEffect(() => {
    if (!pickerOpen || !slashOptions.length) {
      setActiveIndex(-1);
      return;
    }
    setActiveIndex((current) => {
      if (current < 0 || current >= slashOptions.length) return 0;
      return current;
    });
  }, [pickerOpen, slashOptions]);

  useEffect(() => {
    if (!mentionOpen || !filteredMentionPaths.length) {
      setMentionActiveIndex(-1);
      return;
    }
    setMentionActiveIndex((current) => (
      current < 0 || current >= filteredMentionPaths.length ? 0 : current
    ));
  }, [filteredMentionPaths, mentionOpen]);

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

  const selectSlashOption = (option) => {
    if (option?.kind === "skill") {
      selectSkill(option.skill);
      return;
    }
    if (!slashRange || option?.kind !== "command") return;
    const nextQuestion =
      question.slice(0, slashRange.start) +
      question.slice(slashRange.end);
    const cursor = slashRange.start;
    setQuestion(nextQuestion);
    closeSkillPicker();
    window.requestAnimationFrame(() => {
      runComposerCommand(option.command);
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
      resizeTextarea(textarea);
    });
  };

  const completeSlashOption = (option) => {
    if (option?.kind === "skill") {
      selectSkill(option.skill);
      return;
    }
    if (!slashRange || option?.kind !== "command") return;
    const completed = `${option.command.value} `;
    const nextQuestion =
      question.slice(0, slashRange.start) +
      completed +
      question.slice(slashRange.end);
    const cursor = slashRange.start + completed.length;
    setQuestion(nextQuestion);
    closeSkillPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(cursor, cursor);
      resizeTextarea(textarea);
    });
  };

  const selectWorkspaceMention = (path) => {
    if (!mentionRange) return;
    const next = applyWorkspaceMention(question, mentionRange, path);
    setQuestion(next.value);
    closeMentionPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(next.cursor, next.cursor);
      resizeTextarea(textarea);
    });
  };

  const completeWorkspaceMention = () => {
    if (!mentionRange || !filteredMentionPaths.length) return;
    const commonPrefix = workspaceMentionCommonPrefix(filteredMentionPaths);
    const partial = filteredMentionPaths.length > 1 && commonPrefix.length > mentionQuery.length;
    if (!partial) {
      const selected = filteredMentionPaths[mentionActiveIndex];
      if (selected) selectWorkspaceMention(selected);
      return;
    }
    const next = applyWorkspaceMention(question, mentionRange, commonPrefix, { complete: false });
    setQuestion(next.value);
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(next.cursor, next.cursor);
      resizeTextarea(textarea);
      updateComposerPicker(next.value, next.cursor);
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
  const selectedKnowledgeBaseName =
    knowledgeBases.find((kb) => valueOf(kb.id) === selectedKnowledgeBaseId)?.name ||
    "不使用知识库";
  const activeOptionId =
    mentionOpen && mentionActiveIndex >= 0 && filteredMentionPaths[mentionActiveIndex]
      ? `workspace-mention-${mentionActiveIndex}`
      : pickerOpen && activeIndex >= 0 && slashOptions[activeIndex]
      ? slashOptions[activeIndex].kind === "command"
        ? `composer-command-${slashOptions[activeIndex].command.value.slice(1)}`
        : `skill-option-${slashOptions[activeIndex].skill.id}`
      : undefined;
  const queueHeading = queuePaused
    ? queueBlockLabels[queueBlockReason] || "待发送已暂停"
    : `接下来 ${queuedChats.length}`;
  const canResumeQueue = queuePaused
    && !["approval", "question", "run"].includes(queueBlockReason);
  const queueInteractionBlocked = ["approval", "question", "run"].includes(
    queueBlockReason,
  );
  const visibleAgentState = switchingSession
    ? {
        mode: "running",
        label: "正在打开任务",
        detail: "同步消息与运行状态",
        actionable: false,
      }
    : agentState.mode !== "idle"
      ? agentState
      : sending
        ? {
            mode: "running",
            label: "Agent正在工作",
            detail: queuedChats.length
              ? `当前任务运行中，另有${queuedChats.length}条待发送`
              : "正在规划、调用工具或生成答案",
            actionable: false,
          }
        : idleAgentState;

  return (
    <form className={"composer"} id={"chat-form"} onSubmit={handleChatSubmit}>
      {mentionOpen ? (
        <WorkspaceMentionPicker
          paths={filteredMentionPaths}
          status={mentionStatus}
          activeIndex={mentionActiveIndex}
          onSelect={selectWorkspaceMention}
          onRetry={loadWorkspaceMentions}
        />
      ) : null}
      {pickerOpen ? (
        <ComposerSlashPicker
          options={slashOptions}
          status={skillsStatus}
          activeIndex={activeIndex}
          onSelect={selectSlashOption}
          onRetry={loadAvailableSkills}
          onManage={handleManageSkills}
        />
      ) : null}
      {queuedChats.length ? (
        <div className={"composer-queue"} aria-live={"polite"}>
          <div className={"composer-queue-heading"}>
            <strong>{queueHeading}</strong>
            <span>
              {canResumeQueue ? (
                <button type={"button"} onClick={() => handleQueueAction("resume")}>{"继续发送"}</button>
              ) : null}
              <button type={"button"} onClick={() => handleQueueAction("clear")}>{"清空"}</button>
            </span>
          </div>
          <div className={"composer-queue-list"} role={"list"} aria-label={"待发送任务"}>
          {queuedChats.slice(0, 3).map((item, index) => {
            const priority = Object.prototype.hasOwnProperty.call(queuePriorityLabels, item.priority)
              ? item.priority
              : "next";
            return (
            <div className={"composer-queue-row"} key={item.id} role={"listitem"}>
              <span aria-hidden={"true"}>{index + 1}</span>
              <select
                className={`composer-queue-priority priority-${priority}`}
                aria-label={`设置任务优先级：${item.question}`}
                title={priority === "now"
                  ? queueInteractionBlocked
                    ? "完成当前确认后优先执行"
                    : "立即任务会停止当前运行并优先执行"
                  : "设置待发送顺序"}
                value={priority}
                onChange={(event) => handleQueueAction("priority", item.id, event.target.value)}
              >
                <option value={"now"}>{queuePriorityLabels.now}</option>
                <option value={"next"}>{queuePriorityLabels.next}</option>
                <option value={"later"}>{queuePriorityLabels.later}</option>
              </select>
              <p>{item.question}</p>
              <button
                type={"button"}
                aria-label={`移除待发送任务：${item.question}`}
                onClick={() => handleQueueAction("remove", item.id)}
              >
                {"×"}
              </button>
            </div>
            );
          })}
          </div>
          {queuedChats.length > 3 ? <div className={"composer-queue-more"}>{`另有${queuedChats.length - 3}条`}</div> : null}
        </div>
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
      {visibleAgentState.mode !== "idle" ? (
        <div
          className={`composer-agent-state ${visibleAgentState.mode}`}
          role={visibleAgentState.mode === "failed" ? "alert" : "status"}
          aria-live={visibleAgentState.mode === "failed" ? "assertive" : "polite"}
        >
          <span className={"composer-agent-state-dot"} aria-hidden={"true"}></span>
          <div className={"composer-agent-state-copy"}>
            <strong>{visibleAgentState.label}</strong>
            <span>{visibleAgentState.detail}</span>
          </div>
          {visibleAgentState.actionable ? (
            <button type={"button"} onClick={handleOpenAgentWorkbench}>
              {visibleAgentState.mode === "failed" ? "查看恢复操作" : "查看并处理"}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className={"composer-shell"}>
        <button className={composerPlusClassName} id={"composer-plus-btn"} type={"button"} aria-label={"添加文件或工具"} onClick={handleComposerMenuToggle} disabled={sending || switchingSession}>
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
              <strong className={"menu-item-label"}>{"上传文件"}</strong>
            </label>
          </section>
          <section className={"composer-settings-panel"} id={"composer-settings-panel"}>
            <label className={"menu-select-card knowledge-select-card"}>
              <span className={"menu-icon"} aria-hidden={"true"}>
                <svg viewBox={"0 0 24 24"} focusable={"false"}>
                  <ellipse cx={"12"} cy={"6"} rx={"7"} ry={"3"} />
                  <path d={"M5 6v6c0 1.66 3.13 3 7 3s7-1.34 7-3V6"} />
                  <path d={"M5 12v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6"} />
                </svg>
              </span>
              <strong className={"menu-item-label"}>{"知识库"}</strong>
              <span className={"menu-item-current"}>{selectedKnowledgeBaseName}</span>
              <span className={"menu-select-chevron"} aria-hidden={"true"}>
                <svg viewBox={"0 0 24 24"} focusable={"false"}>
                  <path d={"M8 10l4 4 4-4"} />
                </svg>
              </span>
              <select id={"composer-kb-select"} aria-label={"选择知识库"} value={selectedKnowledgeBaseId} onChange={handleComposerKnowledgeBaseChange}>
                <option value={""}>{"不使用知识库"}</option>
                {knowledgeBases.map((kb) => (
                  <option value={valueOf(kb.id)} key={kb.id}>{kb.name}</option>
                ))}
              </select>
            </label>
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
            placeholder={switchingSession ? "正在打开任务…" : sending ? "继续输入，Enter加入待发送" : "有问题尽管问。输入 / 选择命令或Skill，@ 引用工作区文件"}
            value={question}
            disabled={switchingSession}
            aria-controls={mentionOpen ? "workspace-mention-listbox" : pickerOpen ? "composer-slash-listbox" : undefined}
            aria-expanded={mentionOpen || pickerOpen}
            aria-haspopup={"listbox"}
            aria-label={"消息"}
            aria-activedescendant={activeOptionId}
            onInput={handleChatInput}
            onPaste={handleChatPaste}
            onKeyDown={handleChatKeyDown}
          />
          <ComposerModelPicker disabled={sending || switchingSession} inputRef={textareaRef} />
        </div>
        <button
          className={"composer-send-button"}
          id={"chat-submit-btn"}
          type={"submit"}
          disabled={switchingSession}
          aria-label={sending ? "停止生成" : "发送消息"}
          title={sending ? "停止生成" : "发送消息"}
          onClick={sending ? handleStopClick : undefined}
        >
          {sending ? <span className={"stop-square"} aria-hidden={"true"}></span> : <svg className={"send-arrow"} viewBox={"0 0 24 24"} aria-hidden={"true"}><path d={"M12 19V5m0 0-6 6m6-6 6 6"} fill={"none"} stroke={"currentColor"} strokeWidth={"2.35"} strokeLinecap={"round"} strokeLinejoin={"round"}></path></svg>}
        </button>
      </div>
    </form>
  );
}
