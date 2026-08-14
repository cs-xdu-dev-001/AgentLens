import { notifyError, notifyToast } from "./errorFeedback.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { runtimeApi, sessionApi } from "../api/client.js";
import { useAuth } from "../auth/AuthProvider.jsx";
import { sidebarTools } from "../data/navigation.js";
import { KnowFlowLogo } from "./KnowFlowLogo.jsx";

const sessionGroupLabels = [
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

const sessionMenuItems = [
  { action: "continue", icon: "message", label: "继续" },
  { action: "rename", icon: "pencil", label: "重命名" },
  { action: "delete", icon: "trash", label: "删除", danger: true, divider: true },
];

function SessionMenuIcon({ type }) {
  if (type === "pencil") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"M4 20h4.4L19.2 9.2a2.1 2.1 0 0 0 0-3L17.8 4.8a2.1 2.1 0 0 0-3 0L4 15.6V20Z"} />
        <path d={"M13.7 5.9l4.4 4.4"} />
      </svg>
    );
  }

  if (type === "trash") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"M4.5 7h15"} />
        <path d={"M9.5 7V5.5A1.5 1.5 0 0 1 11 4h2a1.5 1.5 0 0 1 1.5 1.5V7"} />
        <path d={"M7 7l.8 12.1A2 2 0 0 0 9.8 21h4.4a2 2 0 0 0 2-1.9L17 7"} />
        <path d={"M10 11v6M14 11v6"} />
      </svg>
    );
  }

  return (
    <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
      <path d={"M5 6.8A3.8 3.8 0 0 1 8.8 3h6.4A3.8 3.8 0 0 1 19 6.8v4.4a3.8 3.8 0 0 1-3.8 3.8H10l-5 4V6.8Z"} />
      <path d={"M9 8h6M9 11.5h4"} />
    </svg>
  );
}

function SidebarToolIcon({ type }) {
  if (type === "memory") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"M9 5.5A3.5 3.5 0 0 0 5.5 9v1.2A3.8 3.8 0 0 0 4 13.3 3.7 3.7 0 0 0 7.7 17H9"} />
        <path d={"M15 5.5A3.5 3.5 0 0 1 18.5 9v1.2a3.8 3.8 0 0 1 1.5 3.1 3.7 3.7 0 0 1-3.7 3.7H15"} />
        <path d={"M9 4v16M15 4v16M9 8h2M13 12h2M9 16h2"} />
      </svg>
    );
  }

  if (type === "skills") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"m12 3 7 4v10l-7 4-7-4V7l7-4Z"} />
        <path d={"m5.5 7.3 6.5 3.8 6.5-3.8M12 11.1V21"} />
        <path d={"M18.8 2.8v3M17.3 4.3h3"} />
      </svg>
    );
  }

  if (type === "tools") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <circle cx={"6"} cy={"6"} r={"2"} />
        <circle cx={"18"} cy={"6"} r={"2"} />
        <circle cx={"12"} cy={"18"} r={"2"} />
        <path d={"M8 6h8M7.4 7.5l3.6 8.7M16.6 7.5 13 16.2"} />
      </svg>
    );
  }

  if (type === "settings") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"M12 8.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6Z"} />
        <path d={"M19.4 13.7a7.8 7.8 0 0 0 .1-1.7l2-1.5-2-3.5-2.4 1a7.4 7.4 0 0 0-1.5-.9L15.2 4H8.8l-.4 3.1c-.5.2-1 .5-1.5.9l-2.4-1-2 3.5 2 1.5a7.8 7.8 0 0 0 0 1.8l-2 1.5 2 3.5 2.4-1c.5.4 1 .7 1.5.9l.4 3.1h6.4l.4-3.1c.5-.2 1-.5 1.5-.9l2.4 1 2-3.5-2.1-1.6Z"} />
      </svg>
    );
  }

  if (type === "code") {
    return (
      <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
        <path d={"M8.2 8 4.4 12l3.8 4"} />
        <path d={"M15.8 8 19.6 12l-3.8 4"} />
        <path d={"M13.4 5.5 10.6 18.5"} />
      </svg>
    );
  }

  return (
    <svg aria-hidden={"true"} viewBox={"0 0 24 24"} focusable={"false"}>
      <path d={"M5 7c0-1.7 3.1-3 7-3s7 1.3 7 3-3.1 3-7 3-7-1.3-7-3Z"} />
      <path d={"M5 7v5c0 1.7 3.1 3 7 3s7-1.3 7-3V7"} />
      <path d={"M5 12v5c0 1.7 3.1 3 7 3s7-1.3 7-3v-5"} />
    </svg>
  );
}

function SessionMenuPopover({ anchor, onAction, sessionId }) {
  if (!anchor || !sessionId || typeof document === "undefined") return null;

  return createPortal(
    <div
      className={"session-popover session-popover-floating"}
      role={"menu"}
      style={{ left: `${anchor.left}px`, top: `${anchor.top}px` }}
      onClick={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {sessionMenuItems.map((item) => (
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
    document.body,
  );
}

function groupSessions(sessions) {
  const groups = { active: [], failed: [], today: [], recent: [], earlier: [] };
  const now = new Date();
  sessions.forEach((session) => {
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
  const title = String(session.title || "").trim();
  if (title && title !== "新会话") return title;
  return String(session.latest_run?.goalSummary || title || "新任务");
}


function SessionHistory() {
  const { authenticated } = useAuth();
  const [sessions, setSessions] = useState([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [sessionLoadFailed, setSessionLoadFailed] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [switchingSessionId, setSwitchingSessionId] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [openMenuSessionId, setOpenMenuSessionId] = useState(null);
  const [menuAnchor, setMenuAnchor] = useState(null);
  const [editingSessionId, setEditingSessionId] = useState(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [savingRename, setSavingRename] = useState(false);
  const historyRef = useRef(null);
  const switchingSessionRef = useRef(null);

  const loadSessions = useCallback(async () => {
    if (!authenticated) {
      setSessions([]);
      setCurrentSessionId(null);
      setLoadingSessions(false);
      setSessionLoadFailed(false);
      return [];
    }
    setLoadingSessions(true);
    try {
      const nextSessions = await sessionApi.list();
      const sessionList = Array.isArray(nextSessions) ? nextSessions : [];
      setSessions(sessionList);
      setSessionLoadFailed(false);
      return sessionList;
    } catch (error) {
      setSessionLoadFailed(true);
      notifyError(error, "刷新会话失败");
      return [];
    } finally {
      setLoadingSessions(false);
    }
  }, [authenticated]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

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

  const handleSessionContinue = (sessionId) => {
    if (editingSessionId === sessionId || switchingSessionRef.current === sessionId) return;
    if (sessionId === currentSessionId) {
      window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", {
        detail: { status: "success", sessionId },
      }));
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

  const handleSessionRename = async (sessionId) => {
    const title = renameDraft.trim();
    if (!title) {
      cancelSessionRename();
      return;
    }
    try {
      setSavingRename(true);
      await sessionApi.update(sessionId, { title });
      notifyToast("会话已重命名");
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
    try {
      await sessionApi.delete(sessionId);
      if (currentSessionId === sessionId) {
        setCurrentSessionId(null);
        window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
      }
      notifyToast("会话已删除");
      await loadSessions();
    } catch (error) {
      notifyError(error, "删除失败");
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
    if (action === "delete") {
      handleSessionDelete(sessionId);
    }
  };

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
    const menuHeight = 142;
    const left = Math.max(12, Math.min(rect.right + 8, window.innerWidth - menuWidth - 12));
    const top = Math.max(8, Math.min(rect.top - 10, window.innerHeight - menuHeight - 12));
    setOpenMenuSessionId(sessionId);
    setMenuAnchor({ left, top });
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
  const filteredSessions = keyword
    ? sessions.filter((session) => `${session.title || ""} ${session.latest_run?.goalSummary || ""} ${session.id || ""} ${session.updated_at || ""}`.toLowerCase().includes(keyword))
    : sessions;
  const groups = groupSessions(filteredSessions);

  return (
    <section className={"chat-history-shell"} ref={historyRef}>
      <div className={"sidebar-search-row"}>
        <label className={"sidebar-search"}>
          <span>{"搜索任务"}</span>
          <input id={"sidebar-session-search"} placeholder={"搜索任务"} value={searchQuery} onChange={handleSessionSearch} />
        </label>
        <button className={loadingSessions ? "sidebar-refresh-button loading" : "sidebar-refresh-button"} id={"history-refresh-btn"} type={"button"} aria-label={"刷新任务"} title={"刷新任务"} aria-busy={loadingSessions} disabled={loadingSessions} onClick={loadSessions}>
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M20 11a8 8 0 1 0-2.34 5.66"} />
            <path d={"M20 5v6h-6"} />
          </svg>
        </button>
      </div>
      <div className={"sidebar-list chat-history-list"} id={"session-list"}>
        {loadingSessions && !sessions.length ? (
          <div className={"session-list-skeleton"} aria-label={"正在加载任务"}>
            {[0, 1, 2].map((item) => <span key={item} />)}
          </div>
        ) : sessionLoadFailed && !sessions.length ? (
          <div className={"session-list-feedback"}>
            <span>{"任务加载失败"}</span>
            <button type={"button"} onClick={loadSessions}>{"重试"}</button>
          </div>
        ) : sessionGroupLabels.some(([key]) => groups[key].length) ? (
          sessionGroupLabels
            .filter(([key]) => groups[key].length)
            .map(([key, label]) => (
              <section className={"history-group"} key={key}>
                <div className={"history-group-title"}>{label}</div>
                {groups[key].map((session) => {
                  const isActive = session.id === currentSessionId;
                  const isSwitching = session.id === switchingSessionId;
                  const isOpen = openMenuSessionId === session.id;
                  const isEditing = editingSessionId === session.id;
                  const run = sessionRunView(session);
                  const age = formatSessionAge(session.updated_at || session.created_at);
                  const showIndeterminateProgress = run && activeRunStatuses.has(run.status) && !run.total;
                  return (
                    <div className={["session-row", isActive ? "active" : "", isSwitching ? "switching" : "", isOpen ? "menu-open" : "", run?.status || "chat"].filter(Boolean).join(" ")} key={session.id}>
                      {isEditing ? (
                        <input
                          autoFocus
                          className={"session-rename-input"}
                          value={renameDraft}
                          disabled={savingRename}
                          onBlur={cancelSessionRename}
                          onChange={(event) => setRenameDraft(event.target.value)}
                          onKeyDown={(event) => handleSessionRenameKeyDown(event, session.id)}
                        />
                      ) : (
                        <>
                          <button
                            className={"sidebar-list-item"}
                            type={"button"}
                            aria-busy={isSwitching}
                            aria-current={isActive ? "page" : undefined}
                            disabled={isSwitching}
                            onClick={() => handleSessionAction("continue", session.id)}
                          >
                            <span className={"session-title-row"}>
                              <span className={"session-title"}>{sessionTitle(session)}</span>
                              {age ? <time>{age}</time> : null}
                            </span>
                            {run ? (
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
                          <button className={"session-menu-button"} type={"button"} title={"会话操作"} onClick={(event) => handleSessionMenuToggle(event, session.id)}>
                            <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
                              <circle cx={"6"} cy={"12"} r={"1.7"} />
                              <circle cx={"12"} cy={"12"} r={"1.7"} />
                              <circle cx={"18"} cy={"12"} r={"1.7"} />
                            </svg>
                          </button>
                        </>
                      )}
                    </div>
                  );
                })}
              </section>
            ))
        ) : (
          <p className={"empty-state"}>{keyword ? "没有匹配的任务" : "新任务会显示在这里"}</p>
        )}
      </div>
      <SessionMenuPopover anchor={menuAnchor} sessionId={openMenuSessionId} onAction={handleSessionAction} />
    </section>
  );
}

function UserMenu() {
  const { loading, logout, user } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);
  const displayName = user?.displayName || user?.username || (loading ? "正在连接" : "未登录");
  const email = user?.email || user?.username || (loading ? "请稍候" : "请先登录");
  const avatarText = displayName.slice(0, 1).toUpperCase() || "K";
  const avatarStyle = user?.avatarUrl ? { backgroundImage: `url("${user.avatarUrl}")` } : undefined;

  useEffect(() => {
    const closeMenu = (event) => {
      if (!menuRef.current?.contains(event.target)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("click", closeMenu);
    return () => document.removeEventListener("click", closeMenu);
  }, []);

  const handleUserMenuToggle = (event) => {
    event.stopPropagation();
    setMenuOpen((current) => !current);
  };

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

  return (
    <div className={menuOpen ? "user-menu open" : "user-menu"} id={"user-menu"} ref={menuRef}>
      <button className={"user-menu-button"} id={"user-menu-btn"} type={"button"} onClick={handleUserMenuToggle}>
        <span className={user?.avatarUrl ? "user-avatar with-image" : "user-avatar"} id={"user-avatar"} style={avatarStyle}>
          {user?.avatarUrl ? "" : avatarText}
        </span>
        <span>
          <strong id={"user-display-name"}>{displayName}</strong>
          <small id={"user-email"}>{email}</small>
        </span>
      </button>
      <div className={"user-popover"} id={"user-popover"}>
        <button id={"logout-btn"} type={"button"} onClick={handleLogout} disabled={loggingOut}>
          {loggingOut ? "正在退出..." : "退出登录"}
        </button>
      </div>
    </div>
  );
}

function RuntimeStatus() {
  const [runtime, setRuntime] = useState(null);
  const [failed, setFailed] = useState(false);

  const loadRuntime = useCallback(async () => {
    try {
      const nextRuntime = await runtimeApi.get();
      setRuntime(nextRuntime || null);
      setFailed(false);
    } catch (error) {
      setRuntime(null);
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    loadRuntime();
  }, [loadRuntime]);

  useEffect(() => {
    window.addEventListener("knowflow:react-refresh", loadRuntime);
    return () => {
      window.removeEventListener("knowflow:react-refresh", loadRuntime);
    };
  }, [loadRuntime]);

  if (failed) {
    return (
      <div className={"runtime-card"} id={"runtime-box"}>
        {"离线"}
      </div>
    );
  }

  if (!runtime) {
    return (
      <div className={"runtime-card"} id={"runtime-box"}>
        {"连接中..."}
      </div>
    );
  }

  return (
    <div className={"runtime-card"} id={"runtime-box"}>
      <strong>{"在线"}</strong>
    </div>
  );
}

export function Sidebar({ activePage = "chat", collapsed = false }) {
  const sidebarClassName = collapsed ? "sidebar collapsed" : "sidebar";
  const sidebarToggleLabel = collapsed ? "展开侧边栏" : "收起侧边栏";
  const handlePageChange = (page) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page } }));
  };
  const handleNewChat = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-new-chat"));
  };
  const handleSidebarToggle = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-sidebar-toggle"));
  };
  return (
    <aside className={sidebarClassName} id={"sidebar"}>
      <div className={"sidebar-brand"}>
        <div className={"brand-mark"}>
          <KnowFlowLogo />
        </div>
        <div className={"brand-copy"}>
          <strong>
            {"KnowFlow AI"}
          </strong>
          <span>
            {"工作台"}
          </span>
        </div>
        <button
          className={"icon-button"}
          id={"sidebar-toggle"}
          type={"button"}
          title={sidebarToggleLabel}
          aria-label={sidebarToggleLabel}
          onClick={handleSidebarToggle}
        >
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <rect x={"3.5"} y={"4"} width={"17"} height={"16"} rx={"3"} />
            <path d={"M8.5 4v16"} />
            <path d={collapsed ? "m13 9 3 3-3 3" : "m16 9-3 3 3 3"} />
          </svg>
        </button>
      </div>
      <button className={"new-chat-button"} id={"new-chat-btn"} type={"button"} title={"新对话"} aria-label={"新对话"} onClick={handleNewChat}>
        <span aria-hidden={"true"}>
          <svg viewBox={"0 0 24 24"} focusable={"false"}>
            <path d={"M5 5h8M5 5v14h14v-8"} />
            <path d={"m12 13 6.7-6.7a1.4 1.4 0 0 0-2-2L10 11l-.8 3Z"} />
          </svg>
        </span>
        <strong>
          {"新对话"}
        </strong>
      </button>
      <SessionHistory />
      <div className={"sidebar-bottom-tools"} id={"sidebar-bottom-tools"}>
        {sidebarTools.map((tool) =>
          tool.href ? (
            <a key={tool.key} className={"sidebar-tool"} href={tool.href} target={"_blank"} rel={"noreferrer"}>
              <span className={"nav-icon"}><SidebarToolIcon type={tool.icon} /></span>
              <span>{tool.label}</span>
            </a>
          ) : (
            <button
              key={tool.key}
              className={activePage === tool.page ? "sidebar-tool active" : "sidebar-tool"}
              data-page={tool.page}
              type={"button"}
              aria-label={tool.label}
              onClick={() => handlePageChange(tool.page)}
            >
              <span className={"nav-icon"}><SidebarToolIcon type={tool.icon} /></span>
              <span>{tool.label}</span>
            </button>
          ),
        )}
      </div>
      <UserMenu />
      <RuntimeStatus />
    </aside>
  );
}
