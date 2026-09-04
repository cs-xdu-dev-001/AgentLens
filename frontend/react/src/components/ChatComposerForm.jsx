import { useAutoAnimate } from "@formkit/auto-animate/react";
import {
  ArrowUp,
  ChevronDown,
  Database,
  Plus,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { skillApi, workspaceApi } from "../api/client.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import {
  readComposerDraft,
  writeComposerDraft,
} from "../controller/composerDraftPersistence.js";
import {
  appendComposerHistory,
  readComposerHistory,
  writeComposerHistory,
} from "../controller/composerHistoryPersistence.js";
import { readActiveSessionPreference } from "../controller/sessionPersistence.js";
import { ComposerCommandHelp } from "./ComposerCommandHelp.jsx";
import { ComposerHistorySearch } from "./ComposerHistorySearch.jsx";
import { ComposerModelPicker } from "./ComposerModelPicker.jsx";
import { ComposerPermissionPicker } from "./ComposerPermissionPicker.jsx";
import { ComposerSlashPicker } from "./ComposerSlashPicker.jsx";
import {
  composerCommandSuggestions,
  parseComposerCommand,
} from "./composerCommands.js";
import {
  clearApprovalSessionGrants,
  cycleComposerPermissionMode,
  setComposerPermissionMode,
} from "./composerPermissions.js";
import {
  applyWorkspaceMention,
  workspaceMentionAtCursor,
  workspaceMentionCommonPrefix,
  workspaceMentionSuggestions,
} from "./composerMentions.js";
import { WorkspaceMentionPicker } from "./WorkspaceMentionPicker.jsx";
import { Tooltip } from "./Tooltip.jsx";

const valueOf = (value) => (value === undefined || value === null ? "" : String(value));
const slashPattern = /(^|\s)\/([^\s/]*)$/;
const doubleEscapeWindowMs = 800;
const pageActions = new Set(["knowledge", "workspace", "tools", "skills", "memory", "settings"]);
const queuePriorityLabels = Object.freeze({ now: "立即", next: "接下来", later: "稍后" });
const queueBlockLabels = Object.freeze({
  approval: "等待权限确认",
  question: "等待你的回答",
  run: "等待当前任务继续",
  failed: "发送失败，队列已暂停",
  cancelled: "已停止，待发送已暂停",
  restored: "已恢复，确认后继续",
});
const idleAgentState = Object.freeze({
  mode: "idle",
  label: "就绪",
  detail: "",
  actionable: false,
  runId: "",
  messageId: "",
  recoveryActions: [],
  failureCode: "",
  failedStepTitle: "",
  suggestedPrompt: "",
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

function initialComposerDraft(user) {
  const preference = readActiveSessionPreference(user);
  const sessionId = preference.kind === "session" ? preference.sessionId : "";
  const stored = readComposerDraft(user, sessionId);
  return {
    sessionId,
    draft: stored.kind === "draft" ? stored.draft : { question: "", skill: null },
  };
}

export function ChatComposerForm() {
  const { user } = useAuth();
  const draftOwnerId = valueOf(user?.id);
  const initialDraftRef = useRef(null);
  if (!initialDraftRef.current) initialDraftRef.current = initialComposerDraft(user);
  const initialDraft = initialDraftRef.current.draft;
  const initialHistoryRef = useRef(null);
  if (!initialHistoryRef.current) initialHistoryRef.current = readComposerHistory(user);
  const [attachments, setAttachments] = useState([]);
  const [availableSkills, setAvailableSkills] = useState([]);
  const [skillsStatus, setSkillsStatus] = useState("idle");
  const [selectedSkill, setSelectedSkill] = useState(initialDraft.skill);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(-1);
  const [slashRange, setSlashRange] = useState(null);
  const [commandHelpOpen, setCommandHelpOpen] = useState(false);
  const [historySearchOpen, setHistorySearchOpen] = useState(false);
  const [composerHistory, setComposerHistory] = useState(initialHistoryRef.current.entries);
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionStatus, setMentionStatus] = useState("idle");
  const [mentionPaths, setMentionPaths] = useState([]);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionRange, setMentionRange] = useState(null);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(-1);
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const [question, setQuestion] = useState(initialDraft.question);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [sending, setSending] = useState(false);
  const [queuedChats, setQueuedChats] = useState([]);
  const [queuePaused, setQueuePaused] = useState(false);
  const [queueBlockReason, setQueueBlockReason] = useState("");
  const [queueDurable, setQueueDurable] = useState(false);
  const [switchingSession, setSwitchingSession] = useState(false);
  const [agentState, setAgentState] = useState(idleAgentState);
  const [dismissedFollowUpKey, setDismissedFollowUpKey] = useState("");
  const [promptStash, setPromptStash] = useState(null);
  const [contextStatus, setContextStatus] = useState(null);
  const [contextOperation, setContextOperation] = useState({ status: "idle", message: "" });
  const [commandUsage, setCommandUsage] = useState({});
  const [queueListRef] = useAutoAnimate({
    duration: 180,
    easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  });
  const textareaRef = useRef(null);
  const mountedRef = useRef(false);
  const pickerOpenRef = useRef(false);
  const skillsLoadedRef = useRef(false);
  const mentionsLoadedRef = useRef(false);
  const mentionsLoadedAtRef = useRef(0);
  const requestGenerationRef = useRef(0);
  const agentStateResetRef = useRef(null);
  const autoResumeKeyRef = useRef("");
  const promptStashRef = useRef(null);
  const historySearchDraftRef = useRef(null);
  const composerHistoryRef = useRef(initialHistoryRef.current.entries);
  const pendingStashRestoreRef = useRef(false);
  const lastEmptyEscapeAtRef = useRef(0);
  const sessionSwitchingRef = useRef(false);
  const paletteCommandHandlerRef = useRef(null);
  const draftContextRef = useRef({
    userId: draftOwnerId,
    sessionId: initialDraftRef.current.sessionId,
  });
  const draftWriteTimerRef = useRef(null);
  const transientDraftsRef = useRef(new Map());
  const questionRef = useRef(question);
  const selectedSkillRef = useRef(selectedSkill);
  const attachmentsRef = useRef(attachments);
  questionRef.current = question;
  selectedSkillRef.current = selectedSkill;
  attachmentsRef.current = attachments;
  composerHistoryRef.current = composerHistory;

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

  const closeCommandHelp = useCallback((restoreFocus = true) => {
    setCommandHelpOpen(false);
    if (!restoreFocus) return;
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const closeComposerHistory = useCallback((restoreDraft = true) => {
    const snapshot = historySearchDraftRef.current;
    historySearchDraftRef.current = null;
    if (!restoreDraft) {
      setHistorySearchOpen(false);
      return;
    }
    if (snapshot) questionRef.current = snapshot.question;
    flushSync(() => {
      setHistorySearchOpen(false);
      if (snapshot) setQuestion(snapshot.question);
    });
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      const start = Math.min(snapshot?.selectionStart ?? textarea.value.length, textarea.value.length);
      const end = Math.min(snapshot?.selectionEnd ?? start, textarea.value.length);
      textarea.setSelectionRange(start, end);
      resizeTextarea(textarea);
    });
  }, []);

  const closeMentionPicker = useCallback(() => {
    setMentionOpen(false);
    setMentionQuery("");
    setMentionRange(null);
    setMentionActiveIndex(-1);
  }, []);

  const updatePromptStash = useCallback((value) => {
    promptStashRef.current = value;
    setPromptStash(value);
  }, []);

  const flushComposerDraft = useCallback(() => {
    if (draftWriteTimerRef.current !== null) {
      window.clearTimeout(draftWriteTimerRef.current);
      draftWriteTimerRef.current = null;
    }
    const context = draftContextRef.current;
    if (!context.userId) return false;
    return writeComposerDraft(
      { id: context.userId },
      context.sessionId,
      { question: questionRef.current, skill: selectedSkillRef.current },
    );
  }, []);

  const restoreSessionDraft = useCallback((sessionId) => {
    const nextSessionId = valueOf(sessionId).trim();
    const current = draftContextRef.current;
    if (!current.userId || nextSessionId === current.sessionId) return;
    flushComposerDraft();
    transientDraftsRef.current.set(current.sessionId, {
      draft: {
        question: questionRef.current,
        skill: selectedSkillRef.current,
      },
      attachments: attachmentsRef.current.map((attachment) => ({ ...attachment })),
      promptStash: promptStashRef.current,
    });

    const transient = transientDraftsRef.current.get(nextSessionId);
    const stored = readComposerDraft({ id: current.userId }, nextSessionId);
    const nextDraft = transient?.draft
      || (stored.kind === "draft" ? stored.draft : null)
      || { question: "", skill: null };
    const nextAttachments = (transient?.attachments || [])
      .map((attachment) => ({ ...attachment }));
    draftContextRef.current = { ...current, sessionId: nextSessionId };
    questionRef.current = nextDraft.question;
    selectedSkillRef.current = nextDraft.skill;
    attachmentsRef.current = nextAttachments;
    setQuestion(nextDraft.question);
    setSelectedSkill(nextDraft.skill);
    updatePromptStash(transient?.promptStash || null);
    window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
      detail: { attachments: nextAttachments },
    }));
    closeSkillPicker();
    closeMentionPicker();
    closeComposerHistory(false);
    window.requestAnimationFrame(() => resizeTextarea());
  }, [closeComposerHistory, closeMentionPicker, closeSkillPicker, flushComposerDraft, updatePromptStash]);

  const adoptCreatedSession = useCallback((sessionId) => {
    const nextSessionId = valueOf(sessionId).trim();
    const current = draftContextRef.current;
    if (!current.userId || current.sessionId || !nextSessionId) return false;
    if (draftWriteTimerRef.current !== null) {
      window.clearTimeout(draftWriteTimerRef.current);
      draftWriteTimerRef.current = null;
    }
    writeComposerDraft({ id: current.userId }, "", null);
    transientDraftsRef.current.delete("");
    draftContextRef.current = { ...current, sessionId: nextSessionId };
    writeComposerDraft(
      { id: current.userId },
      nextSessionId,
      { question: questionRef.current, skill: selectedSkillRef.current },
    );
    return true;
  }, []);

  const restorePromptStash = useCallback(() => {
    const stash = promptStashRef.current;
    if (!stash) return false;
    updatePromptStash(null);
    setQuestion(stash.question);
    setSelectedSkill(stash.skill || null);
    window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
      detail: { attachments: stash.attachments || [] },
    }));
    closeSkillPicker();
    closeMentionPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(stash.question.length, stash.question.length);
      resizeTextarea(textarea);
    });
    return true;
  }, [closeMentionPicker, closeSkillPicker, updatePromptStash]);

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
    const handleContextStatus = (event) => {
      const next = event.detail?.status;
      if (!next || typeof next !== "object" || !Number(next.maxTokens)) {
        setContextStatus(null);
        return;
      }
      setContextStatus({
        ...next,
        trimmed: Boolean(next.trimmed || next.compacted || next.contextTrimmed),
      });
    };
    const handleContextOperation = (event) => {
      setContextOperation({
        status: String(event.detail?.status || "idle"),
        message: String(event.detail?.message || ""),
      });
    };
    window.addEventListener("knowflow:react-context-status-updated", handleContextStatus);
    window.addEventListener("knowflow:react-context-compact-state", handleContextOperation);
    return () => {
      window.removeEventListener("knowflow:react-context-status-updated", handleContextStatus);
      window.removeEventListener("knowflow:react-context-compact-state", handleContextOperation);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const resizeFrame = window.requestAnimationFrame(() => resizeTextarea());
    return () => {
      window.cancelAnimationFrame(resizeFrame);
      mountedRef.current = false;
      requestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (draftWriteTimerRef.current !== null) {
      window.clearTimeout(draftWriteTimerRef.current);
    }
    draftWriteTimerRef.current = window.setTimeout(() => {
      draftWriteTimerRef.current = null;
      flushComposerDraft();
    }, 240);
    return () => {
      if (draftWriteTimerRef.current !== null) {
        window.clearTimeout(draftWriteTimerRef.current);
        draftWriteTimerRef.current = null;
      }
    };
  }, [flushComposerDraft, question, selectedSkill]);

  useLayoutEffect(() => {
    const current = draftContextRef.current;
    if (current.userId === draftOwnerId) return;
    flushComposerDraft();
    transientDraftsRef.current.clear();
    const nextInitial = initialComposerDraft({ id: draftOwnerId });
    const nextDraft = nextInitial.draft;
    const nextHistory = readComposerHistory({ id: draftOwnerId }).entries;
    draftContextRef.current = {
      userId: draftOwnerId,
      sessionId: nextInitial.sessionId,
    };
    questionRef.current = nextDraft.question;
    selectedSkillRef.current = nextDraft.skill;
    attachmentsRef.current = [];
    composerHistoryRef.current = nextHistory;
    setQuestion(nextDraft.question);
    setSelectedSkill(nextDraft.skill);
    setComposerHistory(nextHistory);
    updatePromptStash(null);
    window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
      detail: { attachments: [] },
    }));
    closeSkillPicker();
    closeMentionPicker();
    closeComposerHistory(false);
    window.requestAnimationFrame(() => resizeTextarea());
  }, [
    closeComposerHistory,
    closeMentionPicker,
    closeSkillPicker,
    draftOwnerId,
    flushComposerDraft,
    updatePromptStash,
  ]);

  useEffect(() => {
    const handlePageHide = () => flushComposerDraft();
    const handleActiveSession = (event) => {
      const sessionId = event.detail?.sessionId || "";
      if (!sessionSwitchingRef.current && adoptCreatedSession(sessionId)) return;
      restoreSessionDraft(sessionId);
    };
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("knowflow:react-active-session-updated", handleActiveSession);
    return () => {
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("knowflow:react-active-session-updated", handleActiveSession);
      flushComposerDraft();
    };
  }, [adoptCreatedSession, flushComposerDraft, restoreSessionDraft]);

  useEffect(() => {
    const handleSessionSwitchState = (event) => {
      const loading = event.detail?.status === "loading";
      sessionSwitchingRef.current = loading;
      if (loading) {
        clearApprovalSessionGrants();
        closeComposerHistory(false);
      }
      setSwitchingSession(loading);
    };
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
    return () => window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
  }, [closeComposerHistory]);

  useEffect(() => {
    pickerOpenRef.current = pickerOpen;
    if (pickerOpen && !skillsLoadedRef.current) loadAvailableSkills();
  }, [loadAvailableSkills, pickerOpen]);

  useEffect(() => {
    if (!selectedSkill) return;
    if (skillsStatus === "idle") {
      loadAvailableSkills();
      return;
    }
    if (
      skillsStatus === "ready"
      && !availableSkills.some((skill) => skill.id === selectedSkill.id)
    ) {
      setSelectedSkill(null);
    }
  }, [availableSkills, loadAvailableSkills, selectedSkill, skillsStatus]);

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
      const nextQuestion = String(event.detail?.question || "");
      const nextSkillId = event.detail?.skillId ?? null;
      const stashed = promptStashRef.current;
      if (pendingStashRestoreRef.current && !nextQuestion && stashed) {
        pendingStashRestoreRef.current = false;
        updatePromptStash(null);
        questionRef.current = stashed.question;
        selectedSkillRef.current = stashed.skill || null;
        setQuestion(stashed.question);
        setSelectedSkill(stashed.skill || null);
        closeSkillPicker();
        closeMentionPicker();
        window.setTimeout(() => {
          window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
            detail: { attachments: stashed.attachments || [] },
          }));
          window.dispatchEvent(new CustomEvent("knowflow:react-toast", {
            detail: { message: "已自动恢复暂存草稿" },
          }));
        }, 0);
        window.requestAnimationFrame(() => {
          const textarea = textareaRef.current;
          if (!textarea) return;
          textarea.focus();
          textarea.setSelectionRange(stashed.question.length, stashed.question.length);
          resizeTextarea(textarea);
        });
        return;
      }
      const nextSkill = nextSkillId === null
        ? null
        : availableSkills.find((skill) => String(skill.id) === String(nextSkillId)) || null;
      questionRef.current = nextQuestion;
      selectedSkillRef.current = nextSkill;
      if (!nextQuestion && !nextSkill) {
        transientDraftsRef.current.delete(draftContextRef.current.sessionId);
        writeComposerDraft(
          { id: draftContextRef.current.userId },
          draftContextRef.current.sessionId,
          null,
        );
      }
      setQuestion(nextQuestion);
      setSelectedSkill(nextSkill);
      closeSkillPicker();
      closeMentionPicker();
      closeComposerHistory(false);
      window.requestAnimationFrame(() => {
        resizeTextarea();
        if (shouldFocus) textareaRef.current?.focus();
      });
    };
    window.addEventListener("knowflow:react-composer-reset", handleComposerReset);
    return () => window.removeEventListener("knowflow:react-composer-reset", handleComposerReset);
  }, [availableSkills, closeComposerHistory, closeMentionPicker, closeSkillPicker, updatePromptStash]);

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
        runId: String(detail.runId || ""),
        messageId: String(detail.messageId || ""),
        recoveryActions: Array.isArray(detail.recoveryActions)
          ? detail.recoveryActions.filter((action) => ["continue", "retry", "fix"].includes(action))
          : [],
        failureCode: String(detail.failureCode || ""),
        failedStepTitle: String(detail.failedStepTitle || ""),
        suggestedPrompt: String(detail.suggestedPrompt || ""),
      };
      setContextStatus(
        detail.context && Number(detail.context.maxTokens) > 0
          ? detail.context
          : null,
      );
      setAgentState((current) => (
        current.mode === next.mode
        && current.label === next.label
        && current.detail === next.detail
        && current.actionable === next.actionable
        && current.runId === next.runId
        && current.messageId === next.messageId
        && current.recoveryActions.join(",") === next.recoveryActions.join(",")
        && current.failureCode === next.failureCode
        && current.failedStepTitle === next.failedStepTitle
        && current.suggestedPrompt === next.suggestedPrompt
          ? current
          : next
      ));
      if (["completed", "cancelled"].includes(next.mode)) {
        agentStateResetRef.current = window.setTimeout(() => {
          agentStateResetRef.current = null;
          setAgentState((current) => ({
            ...idleAgentState,
            runId: current.runId,
            suggestedPrompt: current.suggestedPrompt,
          }));
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
      setQueueDurable(Boolean(event.detail?.durable));
    };
    window.addEventListener("knowflow:react-chat-queue-updated", handleQueueUpdated);
    return () => window.removeEventListener("knowflow:react-chat-queue-updated", handleQueueUpdated);
  }, []);

  const followUpSuggestionKey = `${agentState.runId}:${agentState.suggestedPrompt}`;
  const followUpSuggestion = !sending
    && !switchingSession
    && !question
    && agentState.suggestedPrompt
    && dismissedFollowUpKey !== followUpSuggestionKey
      ? agentState.suggestedPrompt
      : "";

  const dismissFollowUpSuggestion = () => {
    if (!followUpSuggestion) return;
    setDismissedFollowUpKey(followUpSuggestionKey);
  };

  const acceptFollowUpSuggestion = () => {
    if (!followUpSuggestion) return;
    setDismissedFollowUpKey(followUpSuggestionKey);
    setQuestion(followUpSuggestion);
    closeSkillPicker();
    closeMentionPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(followUpSuggestion.length, followUpSuggestion.length);
      resizeTextarea(textarea);
    });
  };

  const handleComposerMenuToggle = (event) => {
    event.stopPropagation();
    setMenuOpen((current) => !current);
  };
  const handleComposerMenuClick = (event) => event.stopPropagation();
  const handleComposerMenuKeyDown = (event) => {
    if (event.key !== "Escape" || !menuOpen || event.defaultPrevented) return;
    event.preventDefault();
    event.stopPropagation();
    setMenuOpen(false);
    document.getElementById("composer-plus-btn")?.focus();
  };

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
    const parsedCommand = parseComposerCommand(question);
    if (parsedCommand) {
      rememberComposerInput(question);
      setQuestion("");
      closeSkillPicker();
      runComposerCommand(parsedCommand.command, parsedCommand.args);
      window.requestAnimationFrame(() => resizeTextarea());
      return;
    }
    rememberComposerInput(question);
    const submitEvent = new CustomEvent("knowflow:react-chat-submit", {
      detail: { question: question.trim() },
    });
    submitEvent.detail.skillId = selectedSkill?.id ?? null;
    pendingStashRestoreRef.current = Boolean(promptStashRef.current);
    window.dispatchEvent(submitEvent);
    if (pendingStashRestoreRef.current) pendingStashRestoreRef.current = false;
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

  const notifyCommandUnavailable = (message) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-toast", {
      detail: { message, duration: 2600, tone: "neutral" },
    }));
  };

  const rememberComposerInput = useCallback((value) => {
    const ownerId = draftContextRef.current.userId;
    if (!ownerId) return;
    const current = composerHistoryRef.current;
    const next = appendComposerHistory(current, value);
    if (next.length === current.length && next.at(-1) === current.at(-1)) return;
    composerHistoryRef.current = next;
    setComposerHistory(next);
    writeComposerHistory({ id: ownerId }, next);
  }, []);

  const openComposerHistory = () => {
    if (!composerHistoryRef.current.length) {
      notifyCommandUnavailable("还没有可搜索的输入历史");
      return;
    }
    const textarea = textareaRef.current;
    historySearchDraftRef.current = {
      question: questionRef.current,
      selectionStart: textarea?.selectionStart ?? questionRef.current.length,
      selectionEnd: textarea?.selectionEnd ?? questionRef.current.length,
    };
    closeCommandHelp(false);
    closeSkillPicker();
    closeMentionPicker();
    setMenuOpen(false);
    setHistorySearchOpen(true);
  };

  const takeComposerHistory = (value) => {
    const nextQuestion = String(value || "");
    historySearchDraftRef.current = null;
    questionRef.current = nextQuestion;
    setQuestion(nextQuestion);
    setHistorySearchOpen(false);
    closeSkillPicker();
    closeMentionPicker();
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(nextQuestion.length, nextQuestion.length);
      resizeTextarea(textarea);
    });
  };

  const clearComposerInputHistory = () => {
    const ownerId = draftContextRef.current.userId;
    if (!ownerId || !writeComposerHistory({ id: ownerId }, [])) {
      notifyCommandUnavailable("无法清空输入历史，请检查浏览器存储权限");
      return;
    }
    composerHistoryRef.current = [];
    setComposerHistory([]);
    closeComposerHistory();
    notifyCommandUnavailable("已清空此浏览器的输入历史");
  };

  const runMessageCommand = (action, unavailableMessage, args = "") => {
    const detail = { action, args: String(args || "").trim(), handled: false };
    window.dispatchEvent(new CustomEvent("knowflow:react-message-command", { detail }));
    if (!detail.handled) notifyCommandUnavailable(unavailableMessage);
  };

  const handleQuickRewindEscape = () => {
    const now = Date.now();
    if (now - lastEmptyEscapeAtRef.current <= doubleEscapeWindowMs) {
      lastEmptyEscapeAtRef.current = 0;
      runMessageCommand("rewind", "当前会话还没有可回到的历史问题");
      return;
    }
    lastEmptyEscapeAtRef.current = now;
    notifyCommandUnavailable("再按一次Esc，从最近问题创建新分支");
  };

  const openArtifactCommand = () => {
    const detail = { handled: false };
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-artifacts-open", { detail }));
    if (!detail.handled) {
      notifyCommandUnavailable("当前会话还没有可查看的文件变更");
      return;
    }
    handleOpenAgentWorkbench();
  };

  const handleRecoveryCommand = (action) => {
    const advertised = new Set(agentState.recoveryActions);
    if (action === "continue" && !advertised.has("continue") && queuePaused) {
      handleQueueAction("resume");
      return;
    }
    if (
      !agentState.runId
      || !agentState.messageId
      || !advertised.has(action)
    ) {
      handleOpenAgentWorkbench();
      return;
    }
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-run-action", {
      detail: {
        action: action === "continue" ? "resume" : action === "fix" ? "fix" : "restart",
        failedStepTitle: agentState.failedStepTitle,
        failureCode: agentState.failureCode || "agent_run_failed",
        messageId: agentState.messageId,
        runId: agentState.runId,
      },
    }));
  };

  const runComposerCommand = (command, args = "") => {
    setCommandUsage((current) => ({
      ...current,
      [command.value]: (Number(current[command.value]) || 0) + 1,
    }));
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
    if (command.action === "help") {
      closeSkillPicker();
      closeMentionPicker();
      closeComposerHistory(false);
      setCommandHelpOpen(true);
      if (!skillsLoadedRef.current && skillsStatus !== "loading") loadAvailableSkills();
      return;
    }
    if (command.action === "transcript-search") {
      window.dispatchEvent(new CustomEvent("knowflow:react-transcript-search-open", {
        detail: { query: String(args || "").trim() },
      }));
      return;
    }
    if (command.action.startsWith("message-")) {
      const action = command.action.slice("message-".length);
      const unavailableMessages = {
        copy: "当前会话还没有可复制的完整回答",
        edit: "当前会话还没有可编辑的问题",
        rewind: "当前会话还没有可回到的历史问题",
      };
      runMessageCommand(action, unavailableMessages[action], args);
      return;
    }
    if (command.action.startsWith("artifacts-")) {
      openArtifactCommand();
      return;
    }
    if (command.action.startsWith("session-")) {
      window.dispatchEvent(new CustomEvent("knowflow:react-session-command", {
        detail: {
          action: command.action.slice("session-".length),
          args: String(args || "").trim(),
        },
      }));
      return;
    }
    if (command.action === "model") {
      window.dispatchEvent(new CustomEvent("knowflow:react-composer-model-open"));
      return;
    }
    if (["reasoning", "status"].includes(command.action)) {
      window.dispatchEvent(new CustomEvent("knowflow:react-composer-model-open", {
        detail: { focus: command.action },
      }));
      return;
    }
    if (command.action === "context") {
      window.dispatchEvent(new CustomEvent("knowflow:react-composer-model-open", {
        detail: { focus: "context" },
      }));
      return;
    }
    if (command.action === "plan") {
      setComposerPermissionMode("plan");
      const task = String(args || "").trim();
      if (task) {
        const submitEvent = new CustomEvent("knowflow:react-chat-submit", {
          detail: {
            question: task,
            skillId: selectedSkill?.id ?? null,
          },
        });
        window.dispatchEvent(submitEvent);
      }
      return;
    }
    if (command.action === "permissions") {
      window.dispatchEvent(new CustomEvent("knowflow:react-composer-permissions-open"));
      return;
    }
    if (command.action === "tasks") {
      handleOpenAgentWorkbench();
      return;
    }
    if (command.action === "feedback") {
      window.dispatchEvent(new CustomEvent("knowflow:react-diagnostic-copy-request"));
      return;
    }
    if (["continue", "retry", "fix"].includes(command.action)) {
      handleRecoveryCommand(command.action);
      return;
    }
    if (command.action === "stop") handleStopClick();
  };

  useEffect(() => {
    window.dispatchEvent(new CustomEvent("knowflow:react-command-usage-updated", {
      detail: { usage: commandUsage },
    }));
  }, [commandUsage]);

  const handlePaletteCommand = (command, args = "") => {
    if (!command?.value) return;
    closeCommandHelp(false);
    closeComposerHistory(false);
    closeSkillPicker();
    closeMentionPicker();
    setMenuOpen(false);
    if (!pageActions.has(command.action)) {
      window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page: "chat" } }));
    }
    if (command.action === "session-rename") {
      window.dispatchEvent(new CustomEvent("knowflow:react-sidebar-open"));
    }
    runComposerCommand(command, args);
    if (pageActions.has(command.action)) {
      window.requestAnimationFrame(() => document.getElementById("main-stage")?.focus());
    }
  };
  paletteCommandHandlerRef.current = handlePaletteCommand;
  useEffect(() => {
    const handlePaletteCommandEvent = (event) => {
      const command = event.detail?.command;
      if (!command?.value) return;
      paletteCommandHandlerRef.current?.(command, event.detail?.args);
    };
    window.addEventListener("knowflow:react-command-palette-command", handlePaletteCommandEvent);
    return () => window.removeEventListener("knowflow:react-command-palette-command", handlePaletteCommandEvent);
  }, []);

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
    if (event.key !== "Escape") lastEmptyEscapeAtRef.current = 0;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "r") {
      event.preventDefault();
      openComposerHistory();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (question.trim() || attachments.length || selectedSkill) {
        updatePromptStash({
          question,
          skill: selectedSkill,
          attachments: attachments.map((attachment) => ({ ...attachment })),
        });
        setQuestion("");
        setSelectedSkill(null);
        window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
          detail: { attachments: [] },
        }));
        closeSkillPicker();
        closeMentionPicker();
        window.requestAnimationFrame(() => resizeTextarea());
      } else {
        restorePromptStash();
      }
      return;
    }
    if (event.key === "Escape" && menuOpen) {
      event.preventDefault();
      setMenuOpen(false);
      return;
    }
    if (event.key === "Tab" && event.shiftKey) {
      event.preventDefault();
      closeSkillPicker();
      closeMentionPicker();
      cycleComposerPermissionMode();
      return;
    }
    if (
      event.key === "Tab"
      && !question
      && !pickerOpen
      && !mentionOpen
      && followUpSuggestion
    ) {
      event.preventDefault();
      acceptFollowUpSuggestion();
      return;
    }
    if (
      event.key === "Escape"
      && !question
      && !pickerOpen
      && !mentionOpen
      && followUpSuggestion
    ) {
      event.preventDefault();
      dismissFollowUpSuggestion();
      return;
    }
    if (
      event.key === "Escape"
      && !question
      && !pickerOpen
      && !mentionOpen
      && !menuOpen
      && !sending
      && !switchingSession
    ) {
      event.preventDefault();
      if (followUpSuggestion) setDismissedFollowUpKey(followUpSuggestionKey);
      handleQuickRewindEscape();
      return;
    }
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
    const parsedCommand = parseComposerCommand(question);
    if (parsedCommand) {
      rememberComposerInput(question);
      setQuestion("");
      closeSkillPicker();
      runComposerCommand(parsedCommand.command, parsedCommand.args);
      window.requestAnimationFrame(() => resizeTextarea());
      return;
    }
    rememberComposerInput(question);
    const submitEvent = new CustomEvent("knowflow:react-chat-enter-submit", {
      detail: { question: question.trim() },
    });
    submitEvent.detail.skillId = selectedSkill?.id ?? null;
    pendingStashRestoreRef.current = Boolean(promptStashRef.current);
    window.dispatchEvent(submitEvent);
    if (pendingStashRestoreRef.current) pendingStashRestoreRef.current = false;
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
    () => composerCommandSuggestions(pickerQuery, {
      sending,
      recoveryActions: agentState.recoveryActions,
      queuePaused,
      usage: commandUsage,
    }),
    [agentState.recoveryActions, commandUsage, pickerQuery, queuePaused, sending],
  );

  const helpCommands = useMemo(
    () => composerCommandSuggestions("", {
      sending,
      recoveryActions: agentState.recoveryActions,
      queuePaused,
      usage: commandUsage,
    }),
    [agentState.recoveryActions, commandUsage, queuePaused, sending],
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
      if (option.command.action === "help") return;
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

  const takeHelpCommand = (command) => {
    const completed = `${command.value} `;
    setQuestion(completed);
    closeCommandHelp(false);
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(completed.length, completed.length);
      resizeTextarea(textarea);
    });
  };

  const takeHelpSkill = (skill) => {
    setSelectedSkill(skill);
    closeCommandHelp();
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
    closeCommandHelp(false);
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
    ? `${queueBlockLabels[queueBlockReason] || "待发送已暂停"} · ${queuedChats.length}`
    : `接下来 ${queuedChats.length}`;
  const queueStorageLabel = queueDurable ? "已保存" : "仅本页";
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
  const directRecoveryAvailable = Boolean(visibleAgentState.mode === "failed"
    && visibleAgentState.failureCode === "reconnect_failed"
    && visibleAgentState.recoveryActions?.includes("continue")
    && visibleAgentState.runId
    && visibleAgentState.messageId);
  useEffect(() => {
    const recoveryKey = directRecoveryAvailable
      ? `${visibleAgentState.runId}:${visibleAgentState.messageId}`
      : "";
    if (!recoveryKey) {
      autoResumeKeyRef.current = "";
      return undefined;
    }
    const requestResume = () => {
      if (typeof navigator !== "undefined" && navigator.onLine === false) return;
      if (autoResumeKeyRef.current === recoveryKey) return;
      autoResumeKeyRef.current = recoveryKey;
      window.dispatchEvent(new CustomEvent("knowflow:react-agent-run-action", {
        detail: {
          action: "resume",
          messageId: visibleAgentState.messageId,
          runId: visibleAgentState.runId,
        },
      }));
    };
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") requestResume();
    };
    window.addEventListener("online", requestResume);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      window.removeEventListener("online", requestResume);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [directRecoveryAvailable, visibleAgentState.messageId, visibleAgentState.runId]);
  return (
    <form className={"composer"} id={"chat-form"} onSubmit={handleChatSubmit}>
      {commandHelpOpen ? (
        <ComposerCommandHelp
          commands={helpCommands}
          skills={availableSkills}
          skillsStatus={skillsStatus}
          onClose={closeCommandHelp}
          onCommand={takeHelpCommand}
          onSkill={takeHelpSkill}
          onRetrySkills={loadAvailableSkills}
          onManageSkills={handleManageSkills}
        />
      ) : null}
      {historySearchOpen ? (
        <ComposerHistorySearch
          entries={composerHistory}
          onClear={clearComposerInputHistory}
          onClose={closeComposerHistory}
          onSelect={takeComposerHistory}
        />
      ) : null}
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
              <span className={"composer-queue-storage"}>{queueStorageLabel}</span>
              {canResumeQueue ? (
                <button type={"button"} onClick={() => handleQueueAction("resume")}>{"继续发送"}</button>
              ) : null}
              <button type={"button"} onClick={() => handleQueueAction("clear")}>{"清空"}</button>
            </span>
          </div>
          <div className={"composer-queue-list"} ref={queueListRef} role={"list"} aria-label={"待发送任务"}>
          {queuedChats.slice(0, 3).map((item, index) => {
            const priority = Object.prototype.hasOwnProperty.call(queuePriorityLabels, item.priority)
              ? item.priority
              : "next";
            return (
            <div className={"composer-queue-row"} key={item.id} role={"listitem"}>
              <span className={"composer-queue-index"} aria-hidden={"true"}>{index + 1}</span>
              <p title={item.question}>{item.question}</p>
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
              <button
                type={"button"}
                className={"composer-queue-action"}
                aria-label={`取回编辑待发送任务：${item.question}`}
                disabled={Boolean(question.trim() || attachments.length)}
                title={question.trim() || attachments.length ? "先处理当前输入，再取回编辑" : "取回输入框继续编辑"}
                onClick={() => handleQueueAction("retrieve", item.id)}
              >
                {"编辑"}
              </button>
              <button
                type={"button"}
                className={"composer-queue-action"}
                aria-label={`移除待发送任务：${item.question}`}
                onClick={() => handleQueueAction("remove", item.id)}
              >
                {"移除"}
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
                <X size={16} strokeWidth={1.9} aria-hidden={"true"} />
              </button>
            </span>
          );
        })}
      </div>
      {promptStash ? (
        <div className={"composer-stash-notice"} role={"status"} aria-live={"polite"}>
          <span>{"草稿已暂存，发送当前输入后自动恢复"}</span>
          <button type={"button"} title={"Ctrl+S恢复"} onClick={() => restorePromptStash()}>{"立即恢复"}</button>
        </div>
      ) : null}
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
            <button
              type={"button"}
              onClick={directRecoveryAvailable
                ? () => handleRecoveryCommand("continue")
                : handleOpenAgentWorkbench}
            >
              {directRecoveryAvailable
                ? "继续恢复"
                : visibleAgentState.mode === "failed" ? "查看恢复操作" : "查看并处理"}
            </button>
          ) : null}
        </div>
      ) : null}
      {followUpSuggestion ? (
        <div className={"composer-follow-up"} role={"status"} aria-live={"polite"}>
          <button
            className={"composer-follow-up-accept"}
            type={"button"}
            title={"放入输入框继续编辑"}
            onClick={acceptFollowUpSuggestion}
          >
            <span className={"composer-follow-up-label"}>{"下一步"}</span>
            <span className={"composer-follow-up-text"}>{followUpSuggestion}</span>
            <kbd>{"Tab"}</kbd>
          </button>
          <button
            className={"composer-follow-up-dismiss"}
            type={"button"}
            aria-label={"忽略下一步建议"}
            title={"忽略建议（Esc）"}
            onClick={dismissFollowUpSuggestion}
          >
            <X size={16} strokeWidth={1.9} aria-hidden={"true"} />
          </button>
        </div>
      ) : null}
      <div className={"composer-shell"} onKeyDown={handleComposerMenuKeyDown}>
        <Tooltip content={"添加文件或工具"} disabled={menuOpen || sending || switchingSession}>
          <button className={composerPlusClassName} id={"composer-plus-btn"} type={"button"} aria-label={"添加文件或工具"} onClick={handleComposerMenuToggle} disabled={sending || switchingSession}>
            <Plus size={20} strokeWidth={1.9} aria-hidden={"true"} />
          </button>
        </Tooltip>
          <div className={composerMenuClassName} id={"composer-menu"} aria-label={"文件与工具菜单"} onClick={handleComposerMenuClick}>
            <section>
              <label className={"menu-card upload-item"}>
              <input id={"chat-file-input"} type={"file"} multiple accept={".txt,.md,.markdown,.pdf,.docx,.xlsx,.xlsm,.pptx,.html,.htm,.json,.csv,.tsv,.yaml,.yml,.xml,.log,.rtf,.png,.jpg,.jpeg,.webp,.gif,.bmp"} onChange={handleChatFileChange} />
              <span className={"menu-icon"} aria-hidden={"true"}>
                <Upload size={18} strokeWidth={1.8} />
              </span>
              <strong className={"menu-item-label"}>{"上传文件"}</strong>
            </label>
          </section>
          <section className={"composer-settings-panel"} id={"composer-settings-panel"}>
            <label className={"menu-select-card knowledge-select-card"}>
              <span className={"menu-icon"} aria-hidden={"true"}>
                <Database size={18} strokeWidth={1.8} />
              </span>
              <strong className={"menu-item-label"}>{"知识库"}</strong>
              <span className={"menu-item-current"}>{selectedKnowledgeBaseName}</span>
              <span className={"menu-select-chevron"} aria-hidden={"true"}>
                <ChevronDown size={16} strokeWidth={1.8} />
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
                <X size={15} strokeWidth={1.9} aria-hidden={"true"} />
              </button>
            </span>
          ) : null}
          <textarea
            ref={textareaRef}
            name={"question"}
            rows={"1"}
            placeholder={switchingSession
              ? "正在打开任务…"
              : sending
                ? "继续输入，Enter加入待发送"
                : followUpSuggestion
                  ? `${followUpSuggestion} · Tab采纳`
                  : "输入任务，/选择命令或Skill，@引用文件"}
            value={question}
            disabled={switchingSession}
            aria-controls={historySearchOpen
              ? "composer-history-listbox"
              : mentionOpen
                ? "workspace-mention-listbox"
                : pickerOpen
                  ? "composer-slash-listbox"
                  : undefined}
            aria-expanded={historySearchOpen || mentionOpen || pickerOpen}
            aria-haspopup={"listbox"}
            aria-label={"消息"}
            aria-keyshortcuts={"Control+R Meta+R"}
            aria-activedescendant={activeOptionId}
            onInput={handleChatInput}
            onPaste={handleChatPaste}
            onKeyDown={handleChatKeyDown}
          />
          <div className={"composer-control-strip"}>
            <ComposerPermissionPicker disabled={switchingSession} inputRef={textareaRef} />
            <ComposerModelPicker
              contextOperation={contextOperation}
              contextStatus={contextStatus}
              disabled={sending || switchingSession}
              inputRef={textareaRef}
              onCompactContext={() => {
                window.dispatchEvent(new CustomEvent("knowflow:react-session-command", {
                  detail: { action: "compact", args: "" },
                }));
              }}
            />
          </div>
        </div>
        <Tooltip content={sending ? "停止生成" : "发送消息"} shortcut={sending ? undefined : "Enter"} disabled={switchingSession}>
          <button
            className={"composer-send-button"}
            id={"chat-submit-btn"}
            type={"submit"}
            disabled={switchingSession}
            aria-label={sending ? "停止生成" : "发送消息"}
            onClick={sending ? handleStopClick : undefined}
          >
            {sending ? (
              <span className={"stop-square"} aria-hidden={"true"}></span>
            ) : (
              <ArrowUp className={"send-arrow"} size={20} strokeWidth={2.2} aria-hidden={"true"} />
            )}
          </button>
        </Tooltip>
      </div>
    </form>
  );
}
