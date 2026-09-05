import { useAutoAnimate } from "@formkit/auto-animate/react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  Archive,
  Bell,
  BrainCircuit,
  Boxes,
  Check,
  Code2,
  ChevronDown,
  ClipboardCopy,
  Command,
  Database,
  Download,
  GitBranch,
  LogOut,
  Menu,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  RefreshCw,
  Search,
  SquarePen,
  Settings2,
  Trash2,
  Workflow,
  X,
} from "lucide-react";
import { forwardRef, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Virtuoso } from "react-virtuoso";
import { approvalApi, runtimeApi, sessionApi } from "../api/client.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { sidebarTools } from "../data/navigation.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { AgentLensLogo } from "./AgentLensLogo.jsx";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { Tooltip } from "./Tooltip.jsx";

const sessionGroupLabels = [
  ["pinned", "已置顶"],
  ["active", "进行中"],
  ["failed", "需要处理"],
  ["today", "今天"],
  ["recent", "最近 7 天"],
  ["earlier", "更早"],
];

const activeRunStatuses = new Set([
  "planning",
  "running",
  "waiting_approval",
  "waiting_input",
]);
const failedRunStatuses = new Set(["failed", "interrupted"]);
const runStatusLabels = {
  planning: "正在规划",
  running: "执行中",
  waiting_approval: "等待确认",
  waiting_input: "等待回答",
  failed: "失败，可恢复",
  interrupted: "已中断，可恢复",
  cancelled: "已取消",
  completed: "已完成",
};

const mobileHistoryFocusableSelector =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function mobileHistoryFocusable(container) {
  return Array.from(
    container?.querySelectorAll(mobileHistoryFocusableSelector) || [],
  ).filter(
    (element) =>
      !element.hidden &&
      element.getAttribute("aria-hidden") !== "true",
  );
}

const sessionMenuItems = (pinned, archived) => [
  { action: "continue", icon: "message", label: "继续" },
  ...(archived
    ? [{ action: "archive", icon: "archive", label: "恢复到任务" }]
    : [{ action: "pin", icon: "pin", label: pinned ? "取消置顶" : "置顶" }]),
  { action: "branch", icon: "branch", label: "创建分支" },
  { action: "export", icon: "download", label: "导出对话" },
  { action: "rename", icon: "pencil", label: "重命名" },
  ...(!archived ? [{ action: "archive", icon: "archive", label: "归档" }] : []),
  { action: "delete", icon: "trash", label: "删除", danger: true, divider: true },
];

function SessionMenuIcon({ type }) {
  const icons = {
    pin: Pin,
    branch: GitBranch,
    download: Download,
    pencil: Pencil,
    trash: Trash2,
    archive: Archive,
    message: MessageSquare,
  };
  const Icon = icons[type] || MessageSquare;
  return <Icon aria-hidden={"true"} focusable={"false"} size={16} strokeWidth={1.8} />;
}

function SidebarToolIcon({ type }) {
  const icons = {
    database: Database,
    skills: Boxes,
    code: Code2,
    memory: BrainCircuit,
    tools: Workflow,
    settings: Settings2,
  };
  const Icon = icons[type] || Database;
  return <Icon aria-hidden={"true"} focusable={"false"} size={18} strokeWidth={1.7} />;
}

function MobileNavigationMenu({ activePage, onPageIntent, onPageChange }) {
  const { loading, logout, user } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const activeTool = sidebarTools.find((tool) => tool.page === activePage);
  const currentLabel = activePage === "chat"
    ? "对话"
    : activePage === "tools"
      ? "工具"
      : (activeTool?.label || "功能");
  const displayName = user?.displayName || user?.username || (loading ? "正在连接" : "账户");

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logout();
      window.dispatchEvent(new CustomEvent("knowflow:react-auth-logout", {
        detail: { message: "已退出登录" },
      }));
    } catch (error) {
      notifyError(error, "退出登录失败");
    } finally {
      setLoggingOut(false);
    }
  };

  const selectPage = (page) => {
    onPageIntent?.(page);
    onPageChange(page);
  };

  return (
    <div className={"mobile-navigation"}>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button
            className={"mobile-navigation-trigger"}
            id={"mobile-navigation-trigger"}
            type={"button"}
            aria-label={`打开功能菜单，当前：${currentLabel}`}
          >
            <Menu size={18} strokeWidth={1.8} aria-hidden={"true"} />
            <span className={"mobile-navigation-trigger-label"}>{currentLabel}</span>
            <ChevronDown className={"mobile-navigation-chevron"} size={15} strokeWidth={1.8} aria-hidden={"true"} />
          </button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Portal>
          <DropdownMenu.Content
            align={"end"}
            aria-label={"功能导航"}
            aria-labelledby={"mobile-navigation-trigger"}
            className={"mobile-navigation-content"}
            collisionPadding={8}
            sideOffset={8}
          >
            <DropdownMenu.Label className={"mobile-navigation-label"}>
              <span>{"AgentLens"}</span>
              <strong>{displayName}</strong>
            </DropdownMenu.Label>
            <DropdownMenu.Item
              aria-current={activePage === "chat" ? "page" : undefined}
              className={"mobile-navigation-item"}
              onSelect={() => selectPage("chat")}
            >
              <span className={"mobile-navigation-item-icon"}><MessageSquare size={18} aria-hidden={"true"} /></span>
              <span>{"对话"}</span>
              {activePage === "chat" ? <Check className={"mobile-navigation-check"} size={16} aria-hidden={"true"} /> : null}
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className={"mobile-navigation-item"}
              onSelect={() => window.dispatchEvent(new CustomEvent("knowflow:react-command-palette-open"))}
            >
              <span className={"mobile-navigation-item-icon"}><Command size={18} aria-hidden={"true"} /></span>
              <span>{"命令面板"}</span>
              <kbd>{"Ctrl K"}</kbd>
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className={"mobile-navigation-item"}
              onSelect={() => window.dispatchEvent(new CustomEvent("knowflow:react-pending-approvals-open"))}
            >
              <span className={"mobile-navigation-item-icon"}><Bell size={18} aria-hidden={"true"} /></span>
              <span>{"待处理审批"}</span>
            </DropdownMenu.Item>
            <DropdownMenu.Separator className={"mobile-navigation-separator"} />
            {sidebarTools.map((tool) => (
              <DropdownMenu.Item
                aria-current={activePage === tool.page ? "page" : undefined}
                className={"mobile-navigation-item"}
                data-page={tool.page}
                key={tool.key}
                onFocus={() => onPageIntent?.(tool.page)}
                onSelect={() => {
                  if (tool.href) {
                    window.open(tool.href, "_blank", "noopener,noreferrer");
                    return;
                  }
                  selectPage(tool.page);
                }}
              >
                <span className={"mobile-navigation-item-icon"}><SidebarToolIcon type={tool.icon} /></span>
                <span>{tool.label}</span>
                {activePage === tool.page ? <Check className={"mobile-navigation-check"} size={16} aria-hidden={"true"} /> : null}
              </DropdownMenu.Item>
            ))}
            <DropdownMenu.Separator className={"mobile-navigation-separator"} />
            <DropdownMenu.Item
              className={"mobile-navigation-item"}
              onSelect={() => window.dispatchEvent(new CustomEvent("knowflow:react-diagnostic-copy-request"))}
            >
              <span className={"mobile-navigation-item-icon"}><ClipboardCopy size={18} aria-hidden={"true"} /></span>
              <span>{"复制脱敏诊断"}</span>
            </DropdownMenu.Item>
            <DropdownMenu.Item
              className={"mobile-navigation-item danger"}
              disabled={loggingOut}
              onSelect={() => void handleLogout()}
            >
              <span className={"mobile-navigation-item-icon"}><LogOut size={18} aria-hidden={"true"} /></span>
              <span>{loggingOut ? "正在退出…" : "退出登录"}</span>
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </div>
  );
}

function SessionMenuPopover({ anchor, onAction, onClose, portalTarget, session }) {
  const menuRef = useRef(null);
  const sessionId = session?.id;

  useEffect(() => {
    if (!anchor || !sessionId || typeof window === "undefined") return undefined;
    const focusFrame = window.requestAnimationFrame(() => {
      menuRef.current?.querySelector('[role="menuitem"]')?.focus();
    });
    return () => window.cancelAnimationFrame(focusFrame);
  }, [anchor, sessionId]);

  if (!anchor || !sessionId || typeof document === "undefined") return null;

  const handleMenuKeyDown = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose?.();
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const items = Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') || []);
    if (!items.length) return;
    event.preventDefault();
    const currentIndex = Math.max(0, items.indexOf(document.activeElement));
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : event.key === "ArrowUp"
          ? (currentIndex - 1 + items.length) % items.length
          : (currentIndex + 1) % items.length;
    items[nextIndex]?.focus();
  };

  return createPortal(
    <div
      ref={menuRef}
      id={"session-action-menu"}
      className={"session-popover session-popover-floating"}
      role={"menu"}
      aria-label={`会话操作：${sessionTitle(session)}`}
      style={{ left: `${anchor.left}px`, top: `${anchor.top}px` }}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={handleMenuKeyDown}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {sessionMenuItems(Boolean(session.is_pinned), Boolean(session.is_archived)).map((item) => (
        <div className={item.divider ? "session-menu-group danger-group" : "session-menu-group"} key={item.action}>
          {item.divider ? <div className={"session-menu-divider"} /> : null}
          <button className={item.danger ? "session-menu-item danger" : "session-menu-item"} role={"menuitem"} type={"button"} onClick={() => onAction(item.action, sessionId)}>
            <span className={"session-menu-icon"}>
              <SessionMenuIcon type={item.icon} />
            </span>
            <span>{item.label}</span>
          </button>
        </div>
      ))}
    </div>,
    portalTarget || document.body,
  );
}

function SessionDeleteDialog({ session, deleting, onCancel, onConfirm }) {
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const returnFocusRef = useRef(null);
  const sessionId = session?.id;
  const title = sessionTitle(session || {});
  const runStatus = String(session?.latest_run?.status || "");
  const active = activeRunStatuses.has(runStatus);

  useEffect(() => {
    if (!sessionId || typeof document === "undefined") return undefined;
    returnFocusRef.current = document.activeElement;
    const frame = window.requestAnimationFrame(() => cancelRef.current?.focus());
    return () => {
      window.cancelAnimationFrame(frame);
      const previous = returnFocusRef.current;
      window.requestAnimationFrame(() => {
        const trigger = [...document.querySelectorAll(".session-menu-button")]
          .find((button) => button.dataset.sessionId === sessionId);
        const previousIsUsable = previous instanceof HTMLElement
          && previous !== document.body
          && previous !== document.documentElement
          && previous.offsetParent !== null
          && document.contains(previous);
        if (previousIsUsable) previous.focus();
        else if (trigger instanceof HTMLElement && trigger.offsetParent !== null) trigger.focus();
        else if (document.getElementById("new-chat-btn") instanceof HTMLElement) {
          document.getElementById("new-chat-btn").focus();
        } else document.getElementById("sidebar-session-search")?.focus();
      });
    };
  }, [sessionId]);

  if (!sessionId || typeof document === "undefined") return null;

  const handleDialogKeyDown = (event) => {
    if (event.key === "Escape" && !deleting) {
      event.preventDefault();
      event.stopPropagation();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...(dialogRef.current?.querySelectorAll("button:not([disabled])") || [])];
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className={"modal-backdrop session-delete-backdrop"}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deleting) onCancel();
      }}
    >
      <section
        className={"modal-panel session-delete-dialog"}
        role={"alertdialog"}
        aria-modal={"true"}
        aria-labelledby={"session-delete-title"}
        aria-describedby={"session-delete-description"}
        ref={dialogRef}
        onKeyDown={handleDialogKeyDown}
      >
        <div className={"session-delete-body"}>
          <span className={"session-delete-mark"} aria-hidden={"true"}>×</span>
          <div>
            <h2 id={"session-delete-title"}>{"永久删除会话？"}</h2>
            <p id={"session-delete-description"}>
              {`“${title}”的消息、运行记录和检查点都会被删除，且无法恢复。只想隐藏时，请改用归档。`}
            </p>
            {active ? <p className={"session-delete-active"}>{"当前任务会先停止，再执行删除。"}</p> : null}
          </div>
        </div>
        <div className={"modal-actions session-delete-actions"}>
          <button ref={cancelRef} type={"button"} disabled={deleting} onClick={onCancel}>{"取消"}</button>
          <button className={"session-delete-confirm"} type={"button"} disabled={deleting} onClick={onConfirm}>
            {deleting ? "正在删除" : active ? "停止并永久删除" : "永久删除"}
          </button>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function groupSessions(sessions) {
  const groups = { pinned: [], active: [], failed: [], today: [], recent: [], earlier: [] };
  const now = new Date();
  sessions.forEach((session) => {
    if (Boolean(session.is_pinned)) {
      groups.pinned.push(session);
      return;
    }
    const runStatus = String(session.latest_run?.status || "");
    if (activeRunStatuses.has(runStatus)) {
      groups.active.push(session);
      return;
    }
    if (failedRunStatuses.has(runStatus)) {
      groups.failed.push(session);
      return;
    }
    const time = new Date(String(session.updated_at || session.created_at || "").replace(" ", "T"));
    if (Number.isNaN(time.getTime())) {
      groups.earlier.push(session);
      return;
    }
    const days = Math.floor((now - time) / 86400000);
    if (days <= 0) groups.today.push(session);
    else if (days <= 7) groups.recent.push(session);
    else groups.earlier.push(session);
  });
  return groups;
}

function formatRunDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value || 0) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

function formatSessionAge(value) {
  const timestamp = new Date(String(value || "").replace(" ", "T")).getTime();
  if (!Number.isFinite(timestamp)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d` : "";
}

function sessionRunView(session) {
  const run = session.latest_run;
  if (!run) return null;
  const completed = Math.max(0, Number(run.progress?.completed || 0));
  const total = Math.max(completed, Number(run.progress?.total || 0));
  const status = String(run.status || "planning");
  return {
    completed,
    total,
    status,
    label: runStatusLabels[status] || "状态未知",
    duration: formatRunDuration(run.durationMs),
    recoverable: failedRunStatuses.has(status),
  };
}

function sessionTitle(session) {
  const title = safeAgentText(session.title, 160);
  if (title && title !== "新会话") return title;
  return safeAgentText(session.latest_run?.goalSummary || title || "新任务", 160);
}

const SessionHistoryScroller = forwardRef(function SessionHistoryScroller(
  { children, style, ...props },
  ref,
) {
  return (
    <div ref={ref} {...props} style={style}>
      {children}
    </div>
  );
});

function SessionHistoryRow({
  session,
  sessionIndex = null,
  currentSessionId,
  switchingSessionId,
  editingSessionId,
  isOpen = false,
  renameDraft,
  savingRename,
  onRenameCancel,
  onRenameDraftChange,
  onRenameKeyDown,
  onSessionAction,
  onSessionMenuToggle,
}) {
  const isActive = session.id === currentSessionId;
  const isSwitching = session.id === switchingSessionId;
  const isEditing = session.id === editingSessionId;
  const run = sessionRunView(session);
  const age = formatSessionAge(session.updated_at || session.created_at);
  const showRunSummary = run && (activeRunStatuses.has(run.status) || run.recoverable);
  const showIndeterminateProgress = run && activeRunStatuses.has(run.status) && !run.total;
  return (
    <div
      className={["session-row", isActive ? "active" : "", isSwitching ? "switching" : "", isOpen ? "menu-open" : "", run?.status || "chat"].filter(Boolean).join(" ")}
      data-session-row={"true"}
      data-session-id={session.id}
      data-session-index={sessionIndex == null ? undefined : sessionIndex}
    >
      {isEditing ? (
        <input
          autoFocus
          className={"session-rename-input"}
          value={renameDraft}
          disabled={savingRename}
          onBlur={onRenameCancel}
          onChange={(event) => onRenameDraftChange(event.target.value)}
          onKeyDown={(event) => onRenameKeyDown(event, session.id)}
        />
      ) : (
        <>
          <button
            className={"sidebar-list-item"}
            type={"button"}
            data-session-item={"true"}
            data-session-index={sessionIndex == null ? undefined : sessionIndex}
            aria-label={`${sessionTitle(session)}${run ? `，${run.label}` : ""}`}
            title={sessionTitle(session)}
            aria-busy={isSwitching}
            aria-current={isActive ? "page" : undefined}
            disabled={isSwitching}
            onClick={() => onSessionAction("continue", session.id)}
          >
            <span className={"session-title-row"}>
              <span className={"session-title"}>
                {session.is_pinned ? (
                  <span className={"session-pin-mark"} aria-label={"已置顶"}>
                    <SessionMenuIcon type={"pin"} />
                  </span>
                ) : null}
                <span className={"session-title-text"}>{sessionTitle(session)}</span>
              </span>
              {age ? <time>{age}</time> : null}
            </span>
            {showRunSummary ? (
              <span className={"session-run-summary"}>
                <span className={"session-run-status"}>
                  <i aria-hidden={"true"} />
                  {run.label}
                </span>
                <span className={"session-run-meta"}>
                  {run.total ? `${run.completed}/${run.total}` : "Agent"}
                  {run.duration ? ` · ${run.duration}` : ""}
                </span>
                {run.total || showIndeterminateProgress ? (
                  <span className={showIndeterminateProgress ? "session-run-progress indeterminate" : "session-run-progress"} aria-label={run.total ? `任务进度 ${run.completed}/${run.total}` : "任务正在启动"}>
                    <span style={run.total ? { width: `${Math.min(100, (run.completed / run.total) * 100)}%` } : undefined} />
                  </span>
                ) : null}
              </span>
            ) : null}
          </button>
          <button
            className={"session-menu-button"}
            type={"button"}
            data-session-id={session.id}
            aria-label={`会话操作：${sessionTitle(session)}`}
            aria-controls={isOpen ? "session-action-menu" : undefined}
            aria-expanded={isOpen}
            aria-haspopup={"menu"}
            title={`会话操作：${sessionTitle(session)}`}
            onClick={(event) => onSessionMenuToggle(event, session.id)}
          >
            <MoreHorizontal size={17} strokeWidth={1.8} aria-hidden={"true"} />
          </button>
        </>
      )}
    </div>
  );
}


function SessionHistory({ mobileOpen = false, onMobileClose = null, onSessionIndexChange = null }) {
  const { authenticated, user } = useAuth();
  const userId = String(user?.id ?? "");
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [sessionLoadFailed, setSessionLoadFailed] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [switchingSessionId, setSwitchingSessionId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [sessionScope, setSessionScope] = useState("active");
  const [openMenuSessionId, setOpenMenuSessionId] = useState(null);
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [savingRename, setSavingRename] = useState(false);
  const [deleteTargetSessionId, setDeleteTargetSessionId] = useState(null);
  const [deletingSessionId, setDeletingSessionId] = useState(null);
  const [sessionListRef] = useAutoAnimate({
    duration: 180,
    easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  });
  const historyRef = useRef(null);
  const searchInputRef = useRef(null);
  const switchingSessionRef = useRef(null);
  const sessionLoadSequenceRef = useRef(0);
  const sessionOwnerRef = useRef(userId);
  sessionOwnerRef.current = userId;
  const sessionScopeRef = useRef("active");
  const sessionRequestRef = useRef(0);
  const mobileCloseRef = useRef(onMobileClose);
  const mobileRestoreFocusRef = useRef(null);
  const menuTriggerRef = useRef(null);
  const sessionVirtuosoRef = useRef(null);
  const sessionVirtualScrollerRef = useRef(null);
  const sessionFocusFrameRef = useRef(null);
  mobileCloseRef.current = onMobileClose;

  useEffect(() => () => {
    if (sessionFocusFrameRef.current) window.cancelAnimationFrame(sessionFocusFrameRef.current);
  }, []);

  useEffect(() => {
    if (!mobileOpen || typeof document === "undefined") return undefined;
    mobileRestoreFocusRef.current = document.activeElement;
    const focusFrame = window.requestAnimationFrame(() => {
      searchInputRef.current?.focus();
    });
    const handleMobileHistoryKeyDown = (event) => {
      const history = historyRef.current;
      if (!history) return;
      const outsideModal = event.target?.closest?.(
        '[role="dialog"]:not(#session-history), [role="alertdialog"]',
      );
      if (outsideModal) return;
      const sessionMenu = event.target?.closest?.('[role="menu"].session-popover');
      if (event.key === "Escape" && sessionMenu) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        mobileCloseRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !history.contains(document.activeElement)) return;
      const focusable = mobileHistoryFocusable(history);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleMobileHistoryKeyDown, true);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", handleMobileHistoryKeyDown, true);
      const previous = mobileRestoreFocusRef.current;
      mobileRestoreFocusRef.current = null;
      window.requestAnimationFrame(() => {
        if (
          previous &&
          previous.isConnected &&
          typeof previous.focus === "function" &&
          previous !== document.body
        ) {
          previous.focus();
        }
      });
    };
  }, [mobileOpen]);

  const loadSessions = useCallback(async () => {
    const sequence = sessionLoadSequenceRef.current + 1;
    sessionLoadSequenceRef.current = sequence;
    if (!authenticated) {
      sessionRequestRef.current += 1;
      setSessions([]);
      setCurrentSessionId(null);
      setLoadingSessions(false);
      setSessionLoadFailed(false);
      return [];
    }
    const requestId = ++sessionRequestRef.current;
    const scope = sessionScopeRef.current;
    setLoadingSessions(true);
    try {
      const nextSessions = await sessionApi.list({ archived: scope === "archived" });
      const sessionList = Array.isArray(nextSessions) ? nextSessions : [];
      if (
        sequence !== sessionLoadSequenceRef.current
        || userId !== sessionOwnerRef.current
        || requestId !== sessionRequestRef.current
        || scope !== sessionScopeRef.current
      ) return [];
      setSessions(sessionList);
      setSessionLoadFailed(false);
      return sessionList;
    } catch (error) {
      if (
        sequence !== sessionLoadSequenceRef.current
        || userId !== sessionOwnerRef.current
        || requestId !== sessionRequestRef.current
        || scope !== sessionScopeRef.current
      ) return [];
      setSessionLoadFailed(true);
      notifyError(error, "刷新会话失败");
      return [];
    } finally {
      if (
        sequence === sessionLoadSequenceRef.current
        && userId === sessionOwnerRef.current
        && requestId === sessionRequestRef.current
        && scope === sessionScopeRef.current
      ) {
        setLoadingSessions(false);
      }
    }
  }, [authenticated, userId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions, sessionScope]);

  useEffect(() => {
    const handleSessionReloadRequest = (event) => {
      if (Object.prototype.hasOwnProperty.call(event.detail || {}, "currentSessionId")) {
        setCurrentSessionId(event.detail?.currentSessionId || null);
      }
      loadSessions();
    };
    window.addEventListener("knowflow:react-sessions-refresh-request", handleSessionReloadRequest);
    return () => window.removeEventListener("knowflow:react-sessions-refresh-request", handleSessionReloadRequest);
  }, [loadSessions]);

  useEffect(() => {
    const handleActiveSessionUpdated = (event) => {
      setCurrentSessionId(event.detail?.sessionId || null);
    };
    window.addEventListener("knowflow:react-active-session-updated", handleActiveSessionUpdated);
    return () => window.removeEventListener("knowflow:react-active-session-updated", handleActiveSessionUpdated);
  }, []);

  useEffect(() => {
    const handleSessionSwitchState = (event) => {
      const detail = event.detail || {};
      if (detail.status === "loading") {
        switchingSessionRef.current = detail.sessionId || null;
        setSwitchingSessionId(detail.sessionId || null);
        return;
      }
      if (!detail.sessionId || switchingSessionRef.current === detail.sessionId) {
        switchingSessionRef.current = null;
      }
      setSwitchingSessionId((current) => (
        !detail.sessionId || current === detail.sessionId ? null : current
      ));
    };
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
    return () => window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
  }, []);

  useEffect(() => {
    const handleAgentRunUpdated = (event) => {
      const run = event.detail?.run;
      const sessionId = String(run?.sessionId || "");
      if (!sessionId || !run) return;
      setSessions((current) => current.map((session) => (
        String(session.id) === sessionId
          ? { ...session, latest_run: { ...(session.latest_run || {}), ...run } }
          : session
      )));
    };
    window.addEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
    return () => window.removeEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
  }, []);

  useEffect(() => {
    onSessionIndexChange?.(sessions);
    // The shell palette reuses the same index instead of issuing a second session query.
    window.dispatchEvent(new CustomEvent("knowflow:react-session-index-updated", {
      detail: { sessions, scope: sessionScope },
    }));
  }, [onSessionIndexChange, sessionScope, sessions]);

  useEffect(() => {
    if (!currentSessionId) return;
    const currentSession = sessions.find(
      (session) => String(session.id) === String(currentSessionId),
    );
    if (!currentSession) return;
    window.dispatchEvent(new CustomEvent("knowflow:react-active-session-updated", {
      detail: {
        sessionId: currentSessionId,
        title: sessionTitle(currentSession),
      },
    }));
  }, [currentSessionId, sessions]);

  useEffect(() => {
    let cancelled = false;
    window.dispatchEvent(new CustomEvent("knowflow:react-context-compact-state", {
      detail: { status: "idle", message: "" },
    }));
    if (!currentSessionId) {
      window.dispatchEvent(new CustomEvent("knowflow:react-context-status-updated", {
        detail: { status: null },
      }));
      return undefined;
    }
    sessionApi.context(currentSessionId).then((status) => {
      if (cancelled) return;
      window.dispatchEvent(new CustomEvent("knowflow:react-context-status-updated", {
        detail: { status },
      }));
    }).catch(() => {
      if (cancelled) return;
      window.dispatchEvent(new CustomEvent("knowflow:react-context-status-updated", {
        detail: { status: null },
      }));
    });
    return () => {
      cancelled = true;
    };
  }, [currentSessionId]);

  useEffect(() => {
    const closeMenu = (event) => {
      if (!historyRef.current?.contains(event.target)) {
        setOpenMenuSessionId(null);
        setMenuAnchor(null);
      }
    };
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, []);

  const handleSessionSearch = (event) => {
    const query = event.target.value || "";
    setSearchQuery(query);
  };

  const queueSessionFocus = useCallback((sessionId) => {
    if (sessionFocusFrameRef.current) window.cancelAnimationFrame(sessionFocusFrameRef.current);
    let attempts = 0;
    const focusRenderedSession = () => {
      sessionFocusFrameRef.current = null;
      const target = Array.from(
        sessionVirtualScrollerRef.current?.querySelectorAll('button[data-session-item="true"]') || [],
      ).find((item) => item.closest("[data-session-row]")?.getAttribute("data-session-id") === sessionId
        || item.getAttribute("data-session-id") === sessionId);
      if (target) {
        target.focus();
        return;
      }
      attempts += 1;
      if (attempts < 6) {
        sessionFocusFrameRef.current = window.requestAnimationFrame(focusRenderedSession);
      }
    };
    sessionFocusFrameRef.current = window.requestAnimationFrame(focusRenderedSession);
  }, []);

  const handleSessionListKeyDown = (event) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target?.closest?.('button[data-session-item="true"]');
    const history = historyRef.current;
    if (!target || !history?.contains(target)) return;
    if (virtualizeSessionHistory) {
      const currentIndex = Number(target.getAttribute("data-session-index"));
      if (!Number.isInteger(currentIndex) || currentIndex < 0 || !filteredSessions.length) return;
      const nextIndex = event.key === "Home"
        ? 0
        : event.key === "End"
          ? filteredSessions.length - 1
          : (currentIndex + (event.key === "ArrowUp" ? -1 : 1) + filteredSessions.length) % filteredSessions.length;
      const nextItem = historyItems.find((item) => item.type === "session" && item.sessionIndex === nextIndex);
      const nextItemIndex = nextItem ? historyItems.indexOf(nextItem) : -1;
      if (nextItemIndex < 0) return;
      event.preventDefault();
      sessionVirtuosoRef.current?.scrollToIndex({
        index: nextItemIndex,
        align: nextIndex === 0
          ? "start"
          : nextIndex === filteredSessions.length - 1
            ? "end"
            : "center",
        behavior: "auto",
      });
      queueSessionFocus(String(nextItem.session.id));
      return;
    }
    const items = Array.from(
      history.querySelectorAll('button[data-session-item="true"]:not([disabled])'),
    );
    const currentIndex = items.indexOf(target);
    if (currentIndex < 0 || !items.length) return;
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? items.length - 1
        : (currentIndex + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
    event.preventDefault();
    items[nextIndex]?.focus();
  };

  const handleSessionScopeChange = (scope) => {
    if (scope === sessionScope) return;
    sessionScopeRef.current = scope;
    sessionRequestRef.current += 1;
    setOpenMenuSessionId(null);
    setMenuAnchor(null);
    setSessions([]);
    setLoadingSessions(true);
    setSessionScope(scope);
  };

  const handleSessionContinue = (sessionId) => {
    if (editingSessionId === sessionId || switchingSessionRef.current === sessionId) return;
    if (sessionId === currentSessionId) {
      window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", {
        detail: { status: "success", sessionId },
      }));
      onMobileClose?.();
      return;
    }
    const session = sessions.find((item) => item.id === sessionId);
    switchingSessionRef.current = sessionId;
    setSwitchingSessionId(sessionId);
    window.dispatchEvent(new CustomEvent("knowflow:react-session-continue", {
      detail: {
        sessionId,
        title: sessionTitle(session),
        chatModelConfigId: session?.chat_model_config_id ?? null,
      },
    }));
    onMobileClose?.();
  };

  const startSessionRename = (sessionId) => {
    const session = sessions.find((item) => item.id === sessionId);
    setEditingSessionId(sessionId);
    setRenameDraft(session?.title || "新会话");
  };

  const cancelSessionRename = () => {
    if (savingRename) return;
    setEditingSessionId(null);
    setRenameDraft("");
  };

  const handleSessionRename = async (sessionId, requestedTitle = renameDraft) => {
    const title = String(requestedTitle || "").trim();
    if (!title) {
      cancelSessionRename();
      return;
    }
    try {
      setSavingRename(true);
      await sessionApi.update(sessionId, { title });
      notifyToast("会话已重命名");
      if (sessionId === currentSessionId) {
        window.dispatchEvent(new CustomEvent("knowflow:react-active-session-updated", {
          detail: { sessionId, title },
        }));
      }
      setEditingSessionId(null);
      setRenameDraft("");
      await loadSessions();
    } catch (error) {
      notifyError(error, "重命名失败");
    } finally {
      setSavingRename(false);
    }
  };

  const handleSessionRenameKeyDown = (event, sessionId) => {
    if (event.key === "Enter") {
      event.preventDefault();
      handleSessionRename(sessionId);
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancelSessionRename();
    }
  };

  const handleSessionDelete = async (sessionId) => {
    if (!sessionId || deletingSessionId) return;
    try {
      setDeletingSessionId(sessionId);
      await sessionApi.delete(sessionId);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
      }
      setDeleteTargetSessionId(null);
      notifyToast("会话已删除");
      await loadSessions();
    } catch (error) {
      notifyError(error, "删除失败");
    } finally {
      setDeletingSessionId(null);
    }
  };

  const handleSessionPin = async (sessionId) => {
    const session = sessions.find((item) => item.id === sessionId);
    const pinned = !Boolean(session?.is_pinned);
    try {
      await sessionApi.setPinned(sessionId, pinned);
      notifyToast(pinned ? "会话已置顶" : "已取消置顶");
      await loadSessions();
    } catch (error) {
      notifyError(error, pinned ? "置顶失败" : "取消置顶失败");
    }
  };

  const handleSessionArchive = async (sessionId) => {
    const restoring = sessionScope === "archived";
    try {
      await sessionApi.setArchived(sessionId, !restoring);
      if (!restoring && currentSessionId === sessionId) {
        setCurrentSessionId(null);
        window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
      }
      notifyToast(restoring ? "会话已恢复" : "会话已归档");
      await loadSessions();
    } catch (error) {
      notifyError(error, restoring ? "恢复失败" : "归档失败");
    }
  };

  const handleSessionBranch = async (sessionId, title = "") => {
    try {
      const branch = await sessionApi.branch(sessionId, { title: String(title || "").trim() || null });
      notifyToast("已创建独立会话分支");
      await loadSessions();
      const branchId = String(branch?.id || "");
      if (branchId) {
        switchingSessionRef.current = branchId;
        setSwitchingSessionId(branchId);
        window.dispatchEvent(new CustomEvent("knowflow:react-session-continue", {
          detail: {
            sessionId: branchId,
            title: branch?.title || "新会话（分支）",
            chatModelConfigId: branch?.chat_model_config_id ?? null,
          },
        }));
      }
    } catch (error) {
      notifyError(error, "创建分支失败");
    }
  };

  const handleSessionExport = async (sessionId) => {
    try {
      const exported = await sessionApi.export(sessionId);
      const blob = new Blob([String(exported?.content || "")], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = String(exported?.filename || "agentlens-session.md");
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      notifyToast(`已导出${Number(exported?.messageCount || 0)}条消息`);
    } catch (error) {
      notifyError(error, "导出对话失败");
    }
  };

  const handleSessionCompact = async (sessionId, instructions = "") => {
    window.dispatchEvent(new CustomEvent("knowflow:react-context-compact-state", {
      detail: { status: "running", message: "正在整理早期对话，完整记录不会删除" },
    }));
    try {
      const result = await sessionApi.compactContext(sessionId, instructions);
      const compacted = Boolean(result?.compacted);
      const message = compacted
        ? `上下文已压缩：${Number(result?.metadata?.originalTokens || 0).toLocaleString()} → ${Number(result?.metadata?.compactedTokens || 0).toLocaleString()} tokens`
        : "当前会话还没有足够的早期对话可压缩";
      window.dispatchEvent(new CustomEvent("knowflow:react-context-status-updated", {
        detail: { status: result?.status || null },
      }));
      window.dispatchEvent(new CustomEvent("knowflow:react-context-compact-state", {
        detail: { status: compacted ? "success" : "idle", message },
      }));
      notifyToast(message);
    } catch (error) {
      window.dispatchEvent(new CustomEvent("knowflow:react-context-compact-state", {
        detail: { status: "error", message: error?.message || "上下文压缩失败，原对话保持不变" },
      }));
      notifyError(error, "上下文压缩失败，原对话保持不变");
    }
  };

  const handleSessionAction = (action, sessionId) => {
    setOpenMenuSessionId(null);
    setMenuAnchor(null);
    if (action === "continue") {
      handleSessionContinue(sessionId);
      return;
    }
    if (action === "rename") {
      startSessionRename(sessionId);
      return;
    }
    if (action === "pin") {
      handleSessionPin(sessionId);
      return;
    }
    if (action === "branch") {
      handleSessionBranch(sessionId);
      return;
    }
    if (action === "export") {
      handleSessionExport(sessionId);
      return;
    }
    if (action === "archive") {
      handleSessionArchive(sessionId);
      return;
    }
    if (action === "delete") {
      setDeleteTargetSessionId(sessionId);
    }
  };

  useEffect(() => {
    const handleSessionCommand = (event) => {
      const action = String(event.detail?.action || "");
      const args = String(event.detail?.args || "").trim();
      if (action === "resume") {
        window.dispatchEvent(new CustomEvent("knowflow:react-sidebar-open"));
        setSearchQuery(args);
        window.requestAnimationFrame(() => {
          window.requestAnimationFrame(() => searchInputRef.current?.focus());
        });
        return;
      }
      if (!currentSessionId) {
        notifyToast("请先打开一个会话");
        return;
      }
      if (action === "rename") {
        if (args) handleSessionRename(currentSessionId, args);
        else startSessionRename(currentSessionId);
        return;
      }
      if (action === "branch") {
        handleSessionBranch(currentSessionId, args);
        return;
      }
      if (action === "export") handleSessionExport(currentSessionId);
      if (action === "compact") handleSessionCompact(currentSessionId, args);
    };
    window.addEventListener("knowflow:react-session-command", handleSessionCommand);
    return () => window.removeEventListener("knowflow:react-session-command", handleSessionCommand);
  }, [currentSessionId, renameDraft, sessions]);

  const handleSessionMenuToggle = (event, sessionId) => {
    event.stopPropagation();
    const nextOpen = openMenuSessionId === sessionId ? null : sessionId;
    if (!nextOpen) {
      setOpenMenuSessionId(null);
      setMenuAnchor(null);
      return;
    }

    const rect = event.currentTarget.getBoundingClientRect();
    const menuWidth = 214;
    const menuHeight = 330;
    const left = Math.max(12, Math.min(rect.right + 8, window.innerWidth - menuWidth - 12));
    const top = Math.max(8, Math.min(rect.top - 10, window.innerHeight - menuHeight - 12));
    menuTriggerRef.current = event.currentTarget;
    setOpenMenuSessionId(sessionId);
    setMenuAnchor({ left, top });
  };

  const handleSessionMenuClose = () => {
    const trigger = menuTriggerRef.current;
    setOpenMenuSessionId(null);
    setMenuAnchor(null);
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected && typeof trigger.focus === "function") trigger.focus();
    });
  };

  useEffect(() => {
    if (!openMenuSessionId) return undefined;
    const closeFloatingMenu = () => {
      setOpenMenuSessionId(null);
      setMenuAnchor(null);
    };
    window.addEventListener("resize", closeFloatingMenu);
    window.addEventListener("scroll", closeFloatingMenu, true);
    return () => {
      window.removeEventListener("resize", closeFloatingMenu);
      window.removeEventListener("scroll", closeFloatingMenu, true);
    };
  }, [openMenuSessionId]);

  const keyword = searchQuery.trim().toLowerCase();
  const filteredSessions = useMemo(() => (
    keyword
      ? sessions.filter((session) => `${session.title || ""} ${session.latest_run?.goalSummary || ""} ${session.id || ""} ${session.updated_at || ""}`.toLowerCase().includes(keyword))
      : sessions
  ), [keyword, sessions]);
  const groups = useMemo(() => groupSessions(filteredSessions), [filteredSessions]);
  const historyItems = useMemo(() => {
    const items = [];
    let sessionIndex = 0;
    sessionGroupLabels.forEach(([key, label]) => {
      if (!groups[key]?.length) return;
      // Active/recoverable rows already name their status. Avoid repeating it
      // in a second heading, particularly in short desktop windows.
      if (key !== "active" && key !== "failed") {
        items.push({ type: "heading", key: `heading:${key}`, label });
      }
      groups[key].forEach((session) => {
        items.push({
          type: "session",
          key: `session:${session.id}`,
          session,
          sessionIndex: sessionIndex++,
        });
      });
    });
    return items;
  }, [groups]);
  const virtualizeSessionHistory = filteredSessions.length > 80;
  const initialSessionItemIndex = Math.max(
    0,
    historyItems.findIndex((item) => item.type === "session" && item.session.id === currentSessionId),
  );

  const historyContent = (
    <section
      className={mobileOpen ? "chat-history-shell mobile-history-open" : "chat-history-shell"}
      id={"session-history"}
      ref={historyRef}
      role={mobileOpen ? "dialog" : undefined}
      aria-modal={mobileOpen ? "true" : undefined}
      aria-labelledby={mobileOpen ? "mobile-session-history-title" : undefined}
    >
      {mobileOpen ? (
        <div className={"mobile-history-head"}>
          <strong id={"mobile-session-history-title"}>{"会话历史"}</strong>
          <button
            className={"icon-button"}
            type={"button"}
            aria-label={"关闭会话历史"}
            onClick={() => onMobileClose?.()}
          >
            <X size={17} strokeWidth={1.8} aria-hidden={"true"} />
          </button>
        </div>
      ) : null}
      <div className={"session-scope-tabs"} role={"tablist"} aria-label={"任务范围"} onKeyDown={(event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const nextScope = event.key === "Home" ? "active" : event.key === "End" ? "archived" : sessionScope === "active" ? "archived" : "active";
        handleSessionScopeChange(nextScope);
        event.currentTarget.querySelectorAll('[role="tab"]')[nextScope === "active" ? 0 : 1]?.focus();
      }}>
        <button type={"button"} role={"tab"} tabIndex={sessionScope === "active" ? 0 : -1} aria-controls={"session-list"} aria-selected={sessionScope === "active"} className={sessionScope === "active" ? "active" : ""} onClick={() => handleSessionScopeChange("active")}>{"任务"}</button>
        <button type={"button"} role={"tab"} tabIndex={sessionScope === "archived" ? 0 : -1} aria-controls={"session-list"} aria-selected={sessionScope === "archived"} className={sessionScope === "archived" ? "active" : ""} onClick={() => handleSessionScopeChange("archived")}>{"已归档"}</button>
      </div>
      <div className={"sidebar-search-row"}>
        <label className={"sidebar-search"}>
          <Search size={15} strokeWidth={1.8} aria-hidden={"true"} />
          <span>{"搜索任务"}</span>
          <input ref={searchInputRef} id={"sidebar-session-search"} placeholder={"搜索任务"} value={searchQuery} onChange={handleSessionSearch} />
        </label>
        <Tooltip content={"刷新任务"} disabled={loadingSessions}>
          <button className={loadingSessions ? "sidebar-refresh-button loading" : "sidebar-refresh-button"} id={"history-refresh-btn"} type={"button"} aria-label={"刷新任务"} aria-busy={loadingSessions} disabled={loadingSessions} onClick={loadSessions}>
            <RefreshCw size={16} strokeWidth={1.7} aria-hidden={"true"} />
          </button>
        </Tooltip>
      </div>
      <div
        className={"sidebar-list chat-history-list"}
        id={"session-list"}
        ref={virtualizeSessionHistory ? undefined : sessionListRef}
        data-session-count={filteredSessions.length}
        data-virtualized={virtualizeSessionHistory ? "true" : "false"}
        role={"group"}
        aria-label={"会话列表，使用上下箭头切换任务"}
        aria-keyshortcuts={"ArrowDown ArrowUp Home End"}
        onKeyDown={handleSessionListKeyDown}
      >
        {loadingSessions && !sessions.length ? (
          <div className={"session-list-feedback session-list-loading"} role={"status"} aria-label={"正在加载任务"}>
            <RefreshCw size={14} strokeWidth={1.8} aria-hidden={"true"} />
            <span>{"同步任务…"}</span>
          </div>
        ) : sessionLoadFailed && !sessions.length ? (
          <div className={"session-list-feedback"}>
            <span>{"任务加载失败"}</span>
            <button type={"button"} onClick={loadSessions}>{"重试"}</button>
          </div>
        ) : sessionGroupLabels.some(([key]) => groups[key].length) ? (
          virtualizeSessionHistory ? (
            <Virtuoso
              ref={sessionVirtuosoRef}
              className={"session-history-virtual-list"}
              data={historyItems}
              components={{ Scroller: SessionHistoryScroller }}
              computeItemKey={(_index, item) => item.key}
              defaultItemHeight={52}
              initialItemCount={Math.min(historyItems.length, 12)}
              initialTopMostItemIndex={initialSessionItemIndex}
              increaseViewportBy={{ top: 240, bottom: 240 }}
              minOverscanItemCount={4}
              scrollerRef={(node) => {
                sessionVirtualScrollerRef.current = node;
              }}
              skipAnimationFrameInResizeObserver={true}
              style={{ height: "100%" }}
              itemContent={(_index, item) => item.type === "heading" ? (
                <div className={"history-group-title session-history-virtual-heading"} role={"heading"} aria-level={"3"}>{item.label}</div>
              ) : (
                <SessionHistoryRow
                  session={item.session}
                  sessionIndex={item.sessionIndex}
                  currentSessionId={currentSessionId}
                  switchingSessionId={switchingSessionId}
                  editingSessionId={editingSessionId}
                  isOpen={openMenuSessionId === item.session.id}
                  renameDraft={renameDraft}
                  savingRename={savingRename}
                  onRenameCancel={cancelSessionRename}
                  onRenameDraftChange={setRenameDraft}
                  onRenameKeyDown={handleSessionRenameKeyDown}
                  onSessionAction={handleSessionAction}
                  onSessionMenuToggle={handleSessionMenuToggle}
                />
              )}
            />
          ) : sessionGroupLabels
            .filter(([key]) => groups[key].length)
            .map(([key, label]) => (
              <section className={"history-group"} key={key}>
                {key !== "active" && key !== "failed" ? (
                  <div className={"history-group-title"} role={"heading"} aria-level={"3"}>{label}</div>
                ) : null}
                {groups[key].map((session) => (
                  <SessionHistoryRow
                    key={session.id}
                    session={session}
                    currentSessionId={currentSessionId}
                    switchingSessionId={switchingSessionId}
                    editingSessionId={editingSessionId}
                    isOpen={openMenuSessionId === session.id}
                    renameDraft={renameDraft}
                    savingRename={savingRename}
                    onRenameCancel={cancelSessionRename}
                    onRenameDraftChange={setRenameDraft}
                    onRenameKeyDown={handleSessionRenameKeyDown}
                    onSessionAction={handleSessionAction}
                    onSessionMenuToggle={handleSessionMenuToggle}
                  />
                ))}
              </section>
            ))
        ) : (
          <p className={"empty-state"}>{keyword ? "没有匹配的任务" : sessionScope === "archived" ? "归档的任务会显示在这里" : "新任务会显示在这里"}</p>
        )}
      </div>
      <SessionMenuPopover
        anchor={menuAnchor}
        session={sessions.find((item) => item.id === openMenuSessionId)}
        onAction={handleSessionAction}
        onClose={handleSessionMenuClose}
        portalTarget={mobileOpen ? historyRef.current : null}
      />
      <SessionDeleteDialog
        session={sessions.find((item) => item.id === deleteTargetSessionId)}
        deleting={Boolean(deletingSessionId)}
        onCancel={() => {
          if (!deletingSessionId) setDeleteTargetSessionId(null);
        }}
        onConfirm={() => handleSessionDelete(deleteTargetSessionId)}
      />
    </section>
  );
  if (mobileOpen && typeof document !== "undefined") {
    return createPortal(
      <div className={"mobile-session-history-layer"}>
        <button
          className={"mobile-session-history-backdrop"}
          type={"button"}
          aria-label={"关闭会话历史"}
          onClick={() => onMobileClose?.()}
        />
        {historyContent}
      </div>,
      document.body,
    );
  }
  return historyContent;
}

function UserMenu() {
  const { loading, logout, user } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const displayName = user?.displayName || user?.username || (loading ? "正在连接" : "未登录");
  const email = user?.email || user?.username || (loading ? "请稍候" : "请先登录");
  const avatarText = displayName.slice(0, 1).toUpperCase() || "K";
  const avatarStyle = user?.avatarUrl ? { backgroundImage: `url("${user.avatarUrl}")` } : undefined;

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await logout();
      window.dispatchEvent(new CustomEvent("knowflow:react-auth-logout", { detail: { message: "已退出登录" } }));
    } catch (error) {
      notifyError(error, "退出登录失败");
    } finally {
      setLoggingOut(false);
    }
  };

  const handleDiagnosticCopy = () => {
    setMenuOpen(false);
    window.dispatchEvent(new CustomEvent("knowflow:react-diagnostic-copy-request"));
  };

  return (
    <DropdownMenu.Root open={menuOpen} onOpenChange={setMenuOpen}>
    <div className={menuOpen ? "user-menu open" : "user-menu"} id={"user-menu"}>
      <DropdownMenu.Trigger asChild>
      <button
        className={"user-menu-button"}
        id={"user-menu-btn"}
        type={"button"}
        aria-label={`账户菜单：${displayName}`}
      >
        <span className={user?.avatarUrl ? "user-avatar with-image" : "user-avatar"} id={"user-avatar"} style={avatarStyle}>
          {user?.avatarUrl ? "" : avatarText}
        </span>
        <span>
          <strong id={"user-display-name"}>{displayName}</strong>
        </span>
        <ChevronDown className={"user-menu-chevron"} size={15} strokeWidth={1.8} aria-hidden={"true"} />
      </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className={"mobile-navigation-content sidebar-account-menu"} id={"user-popover"} side={"top"} align={"start"} sideOffset={8} collisionPadding={12} aria-label={"账户操作"}>
          <DropdownMenu.Label className={"sidebar-account-label"}>
            <strong>{displayName}</strong>
            <span id={"user-email"}>{email}</span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator className={"mobile-navigation-separator"} />
          <DropdownMenu.Item className={"mobile-navigation-item"} id={"diagnostic-copy-btn"} onSelect={handleDiagnosticCopy}>
            <ClipboardCopy size={17} aria-hidden={"true"} />
            <span>{"复制脱敏诊断"}</span>
          </DropdownMenu.Item>
          <DropdownMenu.Item className={"mobile-navigation-item danger"} id={"logout-btn"} onSelect={() => void handleLogout()} disabled={loggingOut}>
            <LogOut size={17} aria-hidden={"true"} />
            <span>{loggingOut ? "正在退出…" : "退出登录"}</span>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </div>
    </DropdownMenu.Root>
  );
}

function RuntimeStatus() {
  const [runtime, setRuntime] = useState(null);
  const [failed, setFailed] = useState(false);
  const [checking, setChecking] = useState(true);
  const requestRef = useRef(0);

  const loadRuntime = useCallback(async ({ silent = false } = {}) => {
    const requestId = requestRef.current + 1;
    requestRef.current = requestId;
    if (!silent) setChecking(true);
    try {
      const nextRuntime = await runtimeApi.get();
      if (requestId !== requestRef.current) return;
      setRuntime(nextRuntime || null);
      setFailed(false);
    } catch (error) {
      if (requestId !== requestRef.current) return;
      setRuntime(null);
      setFailed(true);
    } finally {
      if (requestId === requestRef.current) setChecking(false);
    }
  }, []);

  useEffect(() => {
    const browserOffline = typeof navigator !== "undefined" && navigator.onLine === false;
    if (browserOffline) {
      setFailed(true);
      setChecking(false);
      return;
    }
    void loadRuntime();
  }, [loadRuntime]);

  useEffect(() => {
    const handleRuntimeEvent = () => {
      void loadRuntime();
    };
    const handleOnline = () => {
      void loadRuntime();
    };
    const handleOffline = () => {
      requestRef.current += 1;
      setRuntime(null);
      setFailed(true);
      setChecking(false);
    };
    const handleVisibilityChange = () => {
      if (!document.hidden) void loadRuntime({ silent: true });
    };
    const poll = window.setInterval(() => {
      const browserOffline = typeof navigator !== "undefined" && navigator.onLine === false;
      if (!document.hidden && !browserOffline) void loadRuntime({ silent: true });
    }, 30_000);
    window.addEventListener("knowflow:react-refresh", handleRuntimeEvent);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      requestRef.current += 1;
      window.clearInterval(poll);
      window.removeEventListener("knowflow:react-refresh", handleRuntimeEvent);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [loadRuntime]);

  if (failed) {
    return (
      <div className={"runtime-card runtime-card-offline"} id={"runtime-box"} aria-live={"polite"}>
        <strong>{"离线"}</strong>
        <button
          className={"runtime-retry-button"}
          type={"button"}
          onClick={() => loadRuntime()}
          disabled={checking}
        >
          {checking ? "检查中..." : "重试"}
        </button>
      </div>
    );
  }

  if (!runtime) {
    return (
      <div className={"runtime-card"} id={"runtime-box"} aria-live={"polite"}>
        <strong>{"连接中..."}</strong>
      </div>
    );
  }

  return (
    <div className={"runtime-card"} id={"runtime-box"} aria-label={`AgentLens ${runtime.version || ""} 在线`}>
      <strong>{"在线"}</strong>
      <span>{runtime.version ? `v${runtime.version}` : "AgentLens"}</span>
    </div>
  );
}

function PendingApprovals({ collapsed = false }) {
  const { authenticated } = useAuth();
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const requestRef = useRef(0);
  const load = useCallback(async ({ silent = false } = {}) => {
    const requestId = ++requestRef.current;
    if (!authenticated) {
      setItems([]);
      setLoading(false);
      setError(false);
      return;
    }
    if (!silent) setLoading(true);
    try {
      const result = await approvalApi.listPending({ limit: 50 });
      if (requestId !== requestRef.current) return;
      const list = Array.isArray(result)
        ? result
        : (Array.isArray(result?.items) ? result.items : []);
      setItems(list.filter((item) => (
        item
        && !item.decision
        && String(item.status || "waiting") === "waiting"
      )));
      setError(false);
    } catch {
      if (requestId === requestRef.current) setError(true);
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [authenticated]);
  useEffect(() => {
    load();
    const poll = window.setInterval(() => {
      if (!document.hidden) void load({ silent: true });
    }, 15_000);
    const refresh = () => void load({ silent: true });
    const handleVisibility = () => {
      if (!document.hidden) refresh();
    };
    window.addEventListener("knowflow:react-agent-approvals-updated", refresh);
    window.addEventListener("knowflow:react-agent-approval-resume", refresh);
    window.addEventListener("knowflow:react-refresh", refresh);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      requestRef.current += 1;
      window.clearInterval(poll);
      window.removeEventListener("knowflow:react-agent-approvals-updated", refresh);
      window.removeEventListener("knowflow:react-agent-approval-resume", refresh);
      window.removeEventListener("knowflow:react-refresh", refresh);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [load]);
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open]);
  useEffect(() => {
    const handleOpenRequest = () => {
      setOpen(true);
      void load({ silent: true });
    };
    window.addEventListener("knowflow:react-pending-approvals-open", handleOpenRequest);
    return () => window.removeEventListener("knowflow:react-pending-approvals-open", handleOpenRequest);
  }, [load]);
  const openApproval = (approval) => {
    const sessionId = approval?.sessionId || approval?.session_id;
    setOpen(false);
    if (sessionId) {
      window.dispatchEvent(new CustomEvent("knowflow:react-session-continue", {
        detail: {
          sessionId,
          title: approval?.sessionTitle || approval?.goalSummary || "任务",
          chatModelConfigId: approval?.chatModelConfigId ?? null,
          approvalId: approval?.approvalId || "",
          messageId: approval?.messageId ?? null,
        },
      }));
      return;
    }
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-interaction-focus", {
      detail: { approvalId: approval?.approvalId || "" },
    }));
  };
  const countLabel = items.length > 99 ? "99+" : String(items.length);
  const triggerLabel = items.length
    ? `待处理审批，${countLabel}项`
    : "待处理审批";
  return (
    <div className={["pending-approvals", collapsed ? "collapsed" : ""].filter(Boolean).join(" ")}>
      <button
        className={"sidebar-tool pending-approvals-trigger"}
        type={"button"}
        title={triggerLabel}
        aria-label={triggerLabel}
        aria-expanded={open}
        aria-controls={"pending-approvals-list"}
        onClick={() => {
          setOpen((value) => !value);
          void load({ silent: true });
        }}
      >
        <span className={"nav-icon"} aria-hidden={"true"}>
          <Bell size={17} strokeWidth={1.7} aria-hidden={"true"} />
        </span>
        <span className={"pending-approvals-label"}>{"待处理审批"}</span>
        {items.length ? <span className={"pending-approvals-badge"}>{countLabel}</span> : null}
      </button>
        {open ? (
          <>
            <button
              aria-label={"关闭待处理审批"}
              className={"pending-approvals-backdrop"}
              type={"button"}
              onClick={() => setOpen(false)}
            />
            <div className={"pending-approvals-list"} id={"pending-approvals-list"} role={"region"} aria-label={"待处理审批列表"} aria-live={"polite"}>
              <div className={"pending-approvals-list-heading"}>
                <strong>{"需要你的确认"}</strong>
                <span>
                  {loading ? "同步中" : null}
                  <button type={"button"} aria-label={"关闭待处理审批"} onClick={() => setOpen(false)}>
                    {"关闭"}
                  </button>
                </span>
              </div>
              {error ? (
                <button className={"pending-approvals-retry"} type={"button"} onClick={() => load()}>
                  {"加载失败 · 重试"}
                </button>
              ) : items.length ? (
                <>
                  {items.slice(0, 6).map((item) => (
                    <button type={"button"} className={"pending-approval-item"} key={item.approvalId} onClick={() => openApproval(item)}>
                      <strong>{item.toolName || "工具操作"}</strong>
                      <span>{item.sessionTitle || item.goalSummary || item.serverName || "等待确认"}</span>
                    </button>
                  ))}
                  {items.length > 6 ? <span className={"pending-approvals-more"}>{`还有${items.length - 6}项`}</span> : null}
                </>
              ) : (
                <span className={"pending-approvals-empty"}>{"暂无待处理审批"}</span>
              )}
            </div>
          </>
        ) : null}
    </div>
  );
}

export function Sidebar({
  activePage = "chat",
  collapsed = false,
  onPageIntent = null,
  mobileHistoryOpen = false,
  onMobileHistoryToggle = null,
  onMobileHistoryClose = null,
  onSessionIndexChange = null,
}) {
  const sidebarClassName = [
    "sidebar sidebar-workbench",
    collapsed ? "collapsed" : "",
    mobileHistoryOpen ? "mobile-history-open" : "",
  ].filter(Boolean).join(" ");
  const sidebarToggleLabel = collapsed ? "展开侧边栏" : "收起侧边栏";
  const handlePageChange = (page) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page } }));
  };
  const handleNewChat = () => {
    onMobileHistoryClose?.();
    window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
  };
  const handleSidebarToggle = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-sidebar-toggle"));
  };
  return (
    <aside className={sidebarClassName} id={"sidebar"}>
      <div className={"sidebar-brand"}>
        <div className={"brand-mark"}>
          <AgentLensLogo />
        </div>
        <div className={"brand-copy"}>
          <strong>
            {"AgentLens"}
          </strong>
        </div>
        <Tooltip content={sidebarToggleLabel} side={"right"}>
          <button
            className={"icon-button"}
            id={"sidebar-toggle"}
            type={"button"}
            aria-label={sidebarToggleLabel}
            onClick={handleSidebarToggle}
          >
            {collapsed
              ? <PanelLeftOpen size={17} strokeWidth={1.7} aria-hidden={"true"} />
              : <PanelLeftClose size={17} strokeWidth={1.7} aria-hidden={"true"} />}
          </button>
        </Tooltip>
      </div>
      <Tooltip content={"新对话"} side={"right"}>
        <button className={"new-chat-button"} id={"new-chat-btn"} type={"button"} aria-label={"新对话"} onClick={handleNewChat}>
          <span aria-hidden={"true"}>
            <SquarePen size={17} strokeWidth={1.7} aria-hidden={"true"} />
          </span>
          <strong>
            {"新对话"}
          </strong>
        </button>
      </Tooltip>
      <Tooltip content={"打开会话历史"} side={"bottom"} disabled={mobileHistoryOpen}>
        <button
          className={"mobile-history-trigger"}
          id={"mobile-history-btn"}
          type={"button"}
          aria-label={"打开会话历史"}
          aria-controls={"session-history"}
          aria-expanded={Boolean(mobileHistoryOpen)}
          onClick={() => onMobileHistoryToggle?.()}
        >
          <MessageSquare size={17} strokeWidth={1.7} aria-hidden={"true"} />
        </button>
      </Tooltip>
      <MobileNavigationMenu
        activePage={activePage}
        onPageChange={handlePageChange}
        onPageIntent={onPageIntent}
      />
      <div className={"sidebar-utility-tools"}>
        <div className={"sidebar-section-label sidebar-quick-label"} role={"heading"} aria-level={"2"} aria-hidden={collapsed ? "true" : undefined}>{"快捷操作"}</div>
        <Tooltip content={"命令面板"} shortcut={"Ctrl/⌘+K"} side={"right"}>
          <button
            className={"sidebar-tool command-palette-trigger"}
            type={"button"}
            aria-label={"打开命令面板"}
            aria-keyshortcuts={"Control+k Meta+k"}
            aria-haspopup={"dialog"}
            onClick={() => window.dispatchEvent(new CustomEvent("knowflow:react-command-palette-open"))}
          >
            <span className={"nav-icon"}>
              <Command size={17} strokeWidth={1.7} aria-hidden={"true"} />
            </span>
            <span>{"命令面板"}</span>
            <kbd>{"Ctrl/⌘ K"}</kbd>
          </button>
        </Tooltip>
        <PendingApprovals collapsed={collapsed} />
      </div>
      <SessionHistory
        mobileOpen={mobileHistoryOpen}
        onMobileClose={onMobileHistoryClose}
        onSessionIndexChange={onSessionIndexChange}
      />
      <div className={"sidebar-bottom-tools"} id={"sidebar-bottom-tools"}>
        <div className={"sidebar-section-label"} role={"heading"} aria-level={"2"} aria-hidden={collapsed ? "true" : undefined}>{"工作台"}</div>
        {sidebarTools.map((tool) => (
          <Tooltip key={tool.key} content={tool.label} side={"right"}>
            {tool.href ? (
              <a className={"sidebar-tool"} href={tool.href} target={"_blank"} rel={"noreferrer"} aria-label={tool.label}>
                <span className={"nav-icon"}><SidebarToolIcon type={tool.icon} /></span>
                <span>{tool.label}</span>
              </a>
            ) : (
              <button
                  className={activePage === tool.page ? "sidebar-tool active" : "sidebar-tool"}
                  data-page={tool.page}
                  aria-current={activePage === tool.page ? "page" : undefined}
                  type={"button"}
                aria-label={tool.label}
                onMouseEnter={() => onPageIntent?.(tool.page)}
                onFocus={() => onPageIntent?.(tool.page)}
                onClick={() => handlePageChange(tool.page)}
              >
                <span className={"nav-icon"}><SidebarToolIcon type={tool.icon} /></span>
                <span>{tool.label}</span>
              </button>
            )}
          </Tooltip>
        ))}
      </div>
      <UserMenu />
      <RuntimeStatus />
    </aside>
  );
}
