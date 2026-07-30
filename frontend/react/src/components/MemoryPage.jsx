import { useCallback, useEffect, useRef, useState } from "react";
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
  const [busy, setBusy] = useState("");
  const [editingId, setEditingId] = useState("");
  const [draft, setDraft] = useState("");
  const mountedRef = useRef(false);

  const load = useCallback(async () => {
    if (!active) return;
    setLoading(true);
    try {
      const nextSettings = await memoryApi.settings();
      if (!mountedRef.current) return;
      setSettings(nextSettings);
      const nextMemories = nextSettings?.configured
        ? await memoryApi.list()
        : [];
      if (!mountedRef.current) return;
      setMemories(Array.isArray(nextMemories) ? nextMemories : []);
    } catch (error) {
      if (mountedRef.current) notifyError(error, "无法加载长期记忆");
    } finally {
      if (mountedRef.current) setLoading(false);
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
        aria-busy={Boolean(busy)}
      >
        <header className={"memory-header"}>
          <div className={"memory-title"}>
            <h1>{"记忆"}</h1>
            <span>{settings?.version ? `Mem0 ${settings.version}` : "Mem0"}</span>
          </div>
          <div className={"memory-enable"}>
            <strong>
              {busy === "settings"
                ? "更新中..."
                : !settings?.configured
                ? "未配置"
                : settings.enabled
                  ? "已启用"
                  : "已停用"}
            </strong>
            <button
              className={"memory-switch"}
              type={"button"}
              role={"switch"}
              aria-checked={Boolean(settings?.enabled)}
              aria-label={
                busy === "settings"
                  ? "正在更新长期记忆状态"
                  : settings?.enabled
                    ? "停用长期记忆"
                    : "启用长期记忆"
              }
              disabled={!settings?.configured || Boolean(busy)}
              onClick={handleToggle}
            >
              <span aria-hidden={"true"} />
            </button>
          </div>
        </header>

        {!loading && settings && !settings.configured ? (
          <div className={"memory-unavailable"} role={"status"}>
            {"管理员需要先配置记忆模型Key，配置完成后即可启用Mem0。"}
          </div>
        ) : null}

        <div className={"memory-toolbar"}>
          <strong>
            {loading ? "正在读取..." : `${memories.length}条长期记忆`}
          </strong>
          <div>
            <button
              type={"button"}
              disabled={loading || Boolean(busy)}
              onClick={load}
            >
              {"刷新"}
            </button>
            <button
              className={"danger"}
              type={"button"}
              disabled={!memories.length || Boolean(busy)}
              onClick={handleClear}
            >
              {busy === "clear" ? "清空中..." : "清空全部"}
            </button>
          </div>
        </div>

        <div className={"memory-list"} aria-live={"polite"}>
          {!loading && settings?.configured && !memories.length ? (
            <div className={"memory-empty"}>
              {settings.enabled
                ? "还没有长期记忆。后续对话中形成的稳定偏好和决定会出现在这里。"
                : "启用后，KnowFlow会在回答完成后提取值得长期保留的信息。"}
            </div>
          ) : null}
          {memories.map((memory) => {
            const memoryId = String(memory.id);
            const editing = editingId === memoryId;
            return (
              <article className={"memory-item"} key={memoryId}>
                {editing ? (
                  <div className={"memory-editor"}>
                    <textarea
                      aria-label={"编辑记忆内容"}
                      rows={4}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    <div>
                      <button
                        type={"button"}
                        disabled={!draft.trim() || Boolean(busy)}
                        onClick={() => handleSave(memoryId)}
                      >
                        {busy === memoryId ? "保存中..." : "保存"}
                      </button>
                      <button
                        type={"button"}
                        disabled={Boolean(busy)}
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
                      <div>
                        <button
                          type={"button"}
                          disabled={Boolean(busy)}
                          onClick={() => beginEdit(memory)}
                        >
                          {"编辑"}
                        </button>
                        <button
                          className={"danger"}
                          type={"button"}
                          disabled={Boolean(busy)}
                          onClick={() => handleDelete(memoryId)}
                        >
                          {busy === memoryId ? "删除中..." : "删除"}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}
