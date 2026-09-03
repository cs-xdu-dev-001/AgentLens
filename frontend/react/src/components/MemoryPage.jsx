import { Pencil, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { memoryApi } from "../api/client.js";
import { notifyError, notifyToast } from "./errorFeedback.js";


function memoryTime(memory, timeZone = "") {
  const values = [
    memory?.updated_at,
    memory?.updatedAt,
    memory?.created_at,
    memory?.createdAt,
  ];
  for (const value of values) {
    if (!value) continue;
    const parsed = new Date(String(value));
    if (!Number.isFinite(parsed.getTime())) continue;
    try {
      const options = {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
        ...(timeZone ? { timeZone } : {}),
      };
      const parts = Object.fromEntries(
        new Intl.DateTimeFormat("zh-CN", options)
          .formatToParts(parsed)
          .map((part) => [part.type, part.value]),
      );
      return (
        `${parts.year}年${parts.month}月${parts.day}日 `
        + `${parts.hour}:${parts.minute}`
      );
    } catch {
      continue;
    }
  }
  return "";
}


export function MemoryPage({ active = false }) {
  const [settings, setSettings] = useState(null);
  const [memories, setMemories] = useState([]);
  const [loading, setLoading] = useState(false);
  const [memoriesLoading, setMemoriesLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState("");
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const mountedRef = useRef(false);
  const interactionLocked = loading || memoriesLoading || Boolean(busy);
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const visibleMemories = useMemo(() => {
    if (!normalizedQuery) return memories;
    return memories.filter((memory) =>
      String(memory?.memory || "")
        .toLocaleLowerCase("zh-CN")
        .includes(normalizedQuery),
    );
  }, [memories, normalizedQuery]);
  const statusLabel = busy === "settings"
    ? "更新中..."
    : loading && !settings
      ? "正在连接"
      : loadError && !settings
        ? "连接失败"
        : !settings?.configured
          ? "未配置"
          : settings.enabled
            ? "已启用"
            : "已停用";

  const load = useCallback(async () => {
    if (!active) return;
    setLoading(true);
    setLoadError("");
    try {
      const nextSettings = await memoryApi.settings();
      if (!mountedRef.current) return;
      setSettings(nextSettings);
      setLoading(false);
      if (!nextSettings?.configured) {
        setMemories([]);
        return;
      }
      setMemoriesLoading(true);
      const nextMemories = await memoryApi.list();
      if (!mountedRef.current) return;
      setMemories(Array.isArray(nextMemories) ? nextMemories : []);
    } catch (error) {
      if (mountedRef.current) {
        setLoadError(error?.message || "无法连接记忆服务");
        notifyError(error, "无法加载长期记忆");
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        setMemoriesLoading(false);
      }
    }
  }, [active]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (active) load();
  }, [active, load]);

  const handleToggle = async () => {
    if (!settings?.configured || busy) return;
    setBusy("settings");
    try {
      const next = await memoryApi.setEnabled(!settings.enabled);
      setSettings(next);
      setLoadError("");
      notifyToast(next.enabled ? "长期记忆已启用" : "长期记忆已停用");
    } catch (error) {
      notifyError(error, "更新记忆状态失败");
    } finally {
      setBusy("");
    }
  };

  const beginEdit = (memory) => {
    setEditingId(String(memory.id));
    setDraft(memory.memory || "");
  };

  const handleSave = async (memoryId) => {
    const content = draft.trim();
    if (!content || busy) return;
    setBusy(String(memoryId));
    try {
      const updated = await memoryApi.update(memoryId, content);
      setMemories((current) =>
        current.map((item) =>
          String(item.id) === String(memoryId) ? updated : item,
        ),
      );
      setEditingId("");
      setDraft("");
      notifyToast("记忆已更新");
    } catch (error) {
      notifyError(error, "更新记忆失败");
    } finally {
      setBusy("");
    }
  };

  const handleDelete = async (memoryId) => {
    if (busy) return;
    if (!window.confirm("删除这条长期记忆？此操作无法撤销。")) return;
    setBusy(String(memoryId));
    try {
      await memoryApi.delete(memoryId);
      setMemories((current) =>
        current.filter((item) => String(item.id) !== String(memoryId)),
      );
      notifyToast("记忆已删除");
    } catch (error) {
      notifyError(error, "删除记忆失败");
    } finally {
      setBusy("");
    }
  };

  const handleClear = async () => {
    if (!memories.length || busy) return;
    if (!window.confirm("清空全部长期记忆？此操作无法撤销。")) return;
    setBusy("clear");
    try {
      await memoryApi.clear();
      setMemories([]);
      setEditingId("");
      setQuery("");
      notifyToast("长期记忆已清空");
    } catch (error) {
      notifyError(error, "清空记忆失败");
    } finally {
      setBusy("");
    }
  };

  return (
    <section className={active ? "page active" : "page"} id={"page-memory"}>
      <div
        className={"workspace-page memory-workspace"}
        aria-busy={interactionLocked}
      >
        <header className={"memory-header"}>
          <div className={"memory-title"}>
            <h1>{"记忆"}</h1>
            <span className={"memory-engine"}>
              {settings?.version ? `Mem0 ${settings.version}` : "Mem0"}
            </span>
          </div>
          <div className={"memory-enable"}>
            <strong
              className={"memory-status"}
              data-state={settings?.configured && settings?.enabled ? "enabled" : "disabled"}
              role={"status"}
            >
              {statusLabel}
            </strong>
            <button
              className={"memory-switch"}
              type={"button"}
              role={"switch"}
              aria-checked={Boolean(settings?.configured && settings?.enabled)}
              aria-label={
                busy === "settings"
                  ? "正在更新长期记忆状态"
                  : !settings?.configured
                    ? "长期记忆尚未配置"
                    : settings.enabled
                      ? "停用长期记忆"
                      : "启用长期记忆"
              }
              disabled={!settings?.configured || interactionLocked}
              onClick={handleToggle}
            >
              <span aria-hidden={"true"} />
            </button>
          </div>
        </header>

        <div className={"memory-content"}>
          {loading && !settings ? (
            <div className={"memory-loading"} role={"status"}>
              <strong>{"正在读取配置..."}</strong>
              <div aria-hidden={"true"}>
                <span />
                <span />
                <span />
              </div>
            </div>
          ) : null}

          {loadError ? (
            <div className={"memory-state memory-error"} role={"alert"}>
              <div>
                <strong>{"无法读取长期记忆"}</strong>
                <p>{loadError}</p>
              </div>
              <button type={"button"} disabled={interactionLocked} onClick={load}>
                <RefreshCw size={16} aria-hidden={"true"} />
                <span>{"重试"}</span>
              </button>
            </div>
          ) : null}

          {!loading && settings && !settings.configured && !loadError ? (
            <div className={"memory-state memory-unavailable"} role={"status"}>
              <div>
                <strong>{"长期记忆尚不可用"}</strong>
                <p>{"需要管理员配置记忆模型Key。配置完成后，你可以在这里检查、修改和删除Agent保留的信息。"}</p>
              </div>
              <button type={"button"} disabled={interactionLocked} onClick={load}>
                <RefreshCw size={16} aria-hidden={"true"} />
                <span>{"重新检查"}</span>
              </button>
            </div>
          ) : null}

          {settings?.configured ? (
            <>
              <div className={"memory-toolbar"}>
                <strong>
                  {memoriesLoading
                    ? "正在读取记忆..."
                    : normalizedQuery
                      ? `${visibleMemories.length}/${memories.length}条长期记忆`
                      : `${memories.length}条长期记忆`}
                </strong>
                <div className={"memory-toolbar-actions"}>
                  <div className={"memory-search"} role={"search"}>
                    <Search size={16} aria-hidden={"true"} />
                    <input
                      type={"search"}
                      value={query}
                      placeholder={"搜索记忆"}
                      aria-label={"搜索长期记忆"}
                      onChange={(event) => setQuery(event.target.value)}
                    />
                    {query ? (
                      <button
                        type={"button"}
                        aria-label={"清除记忆搜索"}
                        onClick={() => setQuery("")}
                      >
                        <X size={15} aria-hidden={"true"} />
                      </button>
                    ) : null}
                  </div>
                  <button
                    className={"memory-refresh"}
                    type={"button"}
                    aria-label={"刷新长期记忆"}
                    disabled={interactionLocked}
                    onClick={load}
                  >
                    <RefreshCw
                      className={loading || memoriesLoading ? "is-spinning" : ""}
                      size={17}
                      aria-hidden={"true"}
                    />
                  </button>
                  <button
                    className={"danger memory-clear"}
                    type={"button"}
                    aria-label={busy === "clear" ? "正在清空全部长期记忆" : "清空全部长期记忆"}
                    disabled={!memories.length || interactionLocked}
                    onClick={handleClear}
                  >
                    <Trash2 size={16} aria-hidden={"true"} />
                    <span>{busy === "clear" ? "清空中..." : "清空全部"}</span>
                  </button>
                </div>
              </div>

              <div className={"memory-list"} aria-live={"polite"}>
                {!memoriesLoading && !memories.length ? (
                  <div className={"memory-empty"}>
                    <strong>
                      {settings.enabled ? "还没有长期记忆" : "长期记忆当前已停用"}
                    </strong>
                    <p>
                      {settings.enabled
                        ? "后续对话中形成的稳定偏好和决定会出现在这里。"
                        : "启用后，AgentLens会在回答完成后提取值得长期保留的信息。"}
                    </p>
                    {!settings.enabled ? (
                      <button type={"button"} disabled={interactionLocked} onClick={handleToggle}>
                        {"启用长期记忆"}
                      </button>
                    ) : null}
                  </div>
                ) : null}
                {!memoriesLoading && memories.length && !visibleMemories.length ? (
                  <div className={"memory-empty memory-search-empty"}>
                    <strong>{"没有匹配的记忆"}</strong>
                    <p>{`没有找到包含“${query.trim()}”的内容。`}</p>
                    <button type={"button"} onClick={() => setQuery("")}>
                      {"清除搜索"}
                    </button>
                  </div>
                ) : null}
                {visibleMemories.map((memory) => {
                  const memoryId = String(memory.id);
                  const editing = editingId === memoryId;
                  return (
                    <article
                      className={"memory-item"}
                      data-busy={busy === memoryId ? "true" : "false"}
                      key={memoryId}
                    >
                      {editing ? (
                        <div className={"memory-editor"}>
                          <div className={"memory-editor-heading"}>
                            <strong>{"编辑记忆"}</strong>
                            <span>{`${draft.length}/12000`}</span>
                          </div>
                          <textarea
                            aria-label={"编辑记忆内容"}
                            autoFocus
                            disabled={interactionLocked}
                            maxLength={12000}
                            rows={4}
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                          />
                          <div>
                            <button
                              className={"primary"}
                              type={"button"}
                              disabled={!draft.trim() || interactionLocked}
                              onClick={() => handleSave(memoryId)}
                            >
                              {busy === memoryId ? "保存中..." : "保存"}
                            </button>
                            <button
                              type={"button"}
                              disabled={interactionLocked}
                              onClick={() => {
                                setEditingId("");
                                setDraft("");
                              }}
                            >
                              {"取消"}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <p className={"memory-item-content"}>
                            {memory.memory || "空记忆"}
                          </p>
                          <div className={"memory-item-meta"}>
                            <span>{memoryTime(memory) || "时间未知"}</span>
                            <div className={"memory-item-actions"}>
                              <button
                                type={"button"}
                                disabled={interactionLocked}
                                onClick={() => beginEdit(memory)}
                              >
                                <Pencil size={15} aria-hidden={"true"} />
                                <span>{"编辑"}</span>
                              </button>
                              <button
                                className={"danger"}
                                type={"button"}
                                disabled={interactionLocked}
                                onClick={() => handleDelete(memoryId)}
                              >
                                <Trash2 size={15} aria-hidden={"true"} />
                                <span>{busy === memoryId ? "删除中..." : "删除"}</span>
                              </button>
                            </div>
                          </div>
                        </>
                      )}
                    </article>
                  );
                })}
              </div>
            </>
          ) : null}
        </div>
      </div>
    </section>
  );
}
