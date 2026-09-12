import { useCallback, useEffect, useMemo, useState } from "react";
import { mcpApi } from "../api/client.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { ConfirmDialog } from "./ConfirmDialog.jsx";
import { McpServerDialog } from "./McpServerDialog.jsx";
import { McpToolDrawer } from "./McpToolDrawer.jsx";

const statusCopy = {
  connected: "已连接",
  disconnected: "未连接",
  connecting: "连接中",
  reauthorize: "需重新授权",
  error: "连接异常",
};

function oauthReturnUrl() {
  const url = new URL(window.location.href);
  url.searchParams.set("page", "tools");
  url.searchParams.delete("mcpResult");
  url.searchParams.delete("mcpError");
  return url.toString();
}

export function McpServerPanel({ active = false, onServersChange }) {
  const [servers, setServers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState(null);
  const [selectedServer, setSelectedServer] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const loadMcpServers = useCallback(async () => {
    setLoading(true);
    try {
      const items = await mcpApi.list();
      const next = Array.isArray(items) ? items : [];
      setServers(next);
      onServersChange?.(next);
      setSelectedServer((current) =>
        current
          ? next.find((item) => item.id === current.id) || null
          : null,
      );
    } catch (error) {
      notifyError(error, "加载MCP服务器失败");
    } finally {
      setLoading(false);
    }
  }, [onServersChange]);

  useEffect(() => {
    if (active) loadMcpServers();
  }, [active, loadMcpServers]);

  const notionServer = useMemo(
    () =>
      servers.find(
        (server) =>
          server.slug === "notion" ||
          server.url === "https://mcp.notion.com/mcp",
      ) || null,
    [servers],
  );

  const startOAuth = async (server) => {
    let current = server;
    if (!server.enabled) {
      current = await mcpApi.update(server.id, { enabled: true });
    }
    const result = await mcpApi.startOAuth(current.id, oauthReturnUrl());
    if (!result?.authorizationUrl) {
      throw new Error("授权地址不可用");
    }
    window.location.assign(result.authorizationUrl);
  };

  const handleNotionConnect = async () => {
    setBusyId("notion");
    try {
      const server =
        notionServer || (await mcpApi.create({ preset: "notion" }));
      await startOAuth(server);
    } catch (error) {
      notifyError(error, "连接Notion失败");
      setBusyId("");
    }
  };

  const handleCreate = async (payload) => {
    setBusyId("create");
    try {
      const server = await mcpApi.create(payload);
      if (payload.authType === "oauth") {
        await startOAuth(server);
        return;
      }
      await mcpApi.test(server.id);
      notifyToast("MCP服务器已连接");
      setDialogOpen(false);
      await loadMcpServers();
    } catch (error) {
      notifyError(error, "添加MCP服务器失败");
    } finally {
      setBusyId("");
    }
  };

  const handleUpdate = async (payload) => {
    const server = editingServer;
    if (!server) return;
    setBusyId(String(server.id));
    try {
      let updated = await mcpApi.update(server.id, payload);
      if (updated.authType !== "oauth") {
        if (!updated.enabled) {
          updated = await mcpApi.update(server.id, { enabled: true });
        }
        await mcpApi.test(server.id);
      } else if (updated.status !== "connected") {
        await startOAuth(updated);
        return;
      }
      notifyToast("MCP连接已更新");
      setDialogOpen(false);
      setEditingServer(null);
      await loadMcpServers();
    } catch (error) {
      notifyError(error, "更新MCP服务器失败");
    } finally {
      setBusyId("");
    }
  };

  const handleDialogClose = () => {
    setDialogOpen(false);
    setEditingServer(null);
  };

  const runServerAction = async (server, action, successMessage) => {
    setBusyId(String(server.id));
    try {
      await action();
      if (successMessage) notifyToast(successMessage);
      await loadMcpServers();
    } catch (error) {
      notifyError(error, "MCP操作失败");
    } finally {
      setBusyId("");
    }
  };

  const handleDelete = async (server) => {
    await runServerAction(
      server,
      () => mcpApi.delete(server.id),
      "MCP连接已删除",
    );
  };

  const connectServer = async (server) => {
    if (server.authType === "headers" && !server.configured) {
      setEditingServer(server);
      setDialogOpen(true);
      return;
    }
    await runServerAction(
      server,
      async () => {
        await mcpApi.update(server.id, { enabled: true });
        await mcpApi.test(server.id);
      },
      server.status === "error" ? "连接已恢复" : "MCP服务器已连接",
    );
  };

  const renderActions = (server) => {
    const busy = busyId === String(server.id);
    const oauth = server.authType === "oauth";
    if (server.status !== "connected") {
      return (
        <button
          aria-label={`${server.status === "reauthorize" ? "重新授权" : server.status === "error" ? "重试" : "连接"}${server.name}`}
          className={"primary"}
          type={"button"}
          disabled={busy}
          onClick={() =>
            oauth
              ? runServerAction(server, () => startOAuth(server), "")
              : connectServer(server)
          }
        >
          {server.status === "reauthorize"
            ? "重新授权"
            : server.status === "error"
              ? "重试"
              : "连接"}
        </button>
      );
    }
    return (
      <>
        <button
          aria-label={`测试${server.name}连接`}
          type={"button"}
          disabled={busy}
          onClick={() =>
            runServerAction(
              server,
              () => mcpApi.test(server.id),
              "连接检查完成",
            )
          }
        >
          {"测试"}
        </button>
        {server.status === "connected" ? (
          <>
            <button
              aria-label={`刷新${server.name}的工具列表`}
              type={"button"}
              disabled={busy}
              onClick={() =>
                runServerAction(
                  server,
                  () => mcpApi.refreshTools(server.id),
                  "工具列表已刷新",
                )
              }
            >
              {"刷新工具"}
            </button>
            <button
              aria-label={`停用${server.name}连接`}
              type={"button"}
              disabled={busy}
              onClick={() =>
                runServerAction(
                  server,
                  () => mcpApi.disconnect(server.id),
                  "MCP连接已停用",
                )
              }
            >
              {"停用"}
            </button>
          </>
        ) : null}
      </>
    );
  };

  return (
    <section className={"mcp-panel panel"} aria-label={"MCP服务器"}>
      <div className={"mcp-panel-heading"}>
        <div>
          <h2>{"MCP服务器"}</h2>
          <span>{loading ? "正在读取连接" : `${servers.length}个连接`}</span>
        </div>
        <button
          className={"primary"}
          type={"button"}
          onClick={() => {
            setEditingServer(null);
            setDialogOpen(true);
          }}
        >
          {"添加服务器"}
        </button>
      </div>

      {!notionServer ? (
        <div className={"mcp-notion-preset"}>
          <div className={"mcp-server-mark"} aria-hidden={"true"}>
            {"N"}
          </div>
          <div>
            <strong>{"Notion"}</strong>
            <span>{"通过OAuth连接你的工作区"}</span>
          </div>
          <button
            className={"primary"}
            type={"button"}
            disabled={busyId === "notion"}
            onClick={handleNotionConnect}
          >
            {busyId === "notion" ? "正在连接..." : "连接Notion"}
          </button>
        </div>
      ) : null}

      <div className={"mcp-server-grid"}>
        {servers.map((server) => {
          const enabledCount = server.enabledTools?.length || 0;
          const toolCount = server.tools?.length || 0;
          const isNotion =
            server.slug === "notion" ||
            server.url === "https://mcp.notion.com/mcp";
          return (
            <article className={"mcp-server-card"} key={server.id}>
              <div className={"mcp-server-card-head"}>
                <div className={"mcp-server-mark"} aria-hidden={"true"}>
                  {isNotion ? "N" : server.name.slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <strong>{server.name}</strong>
                  <span className={`mcp-status ${server.status}`}>
                    <i aria-hidden={"true"} />
                    {statusCopy[server.status] || "状态未知"}
                  </span>
                </div>
                <button
                  aria-label={`查看${server.name}的工具`}
                  className={"secondary-button"}
                  type={"button"}
                  onClick={() => setSelectedServer(server)}
                >
                  {"查看工具"}
                </button>
              </div>
              <div className={"mcp-server-metrics"}>
                <span>{`${toolCount}个工具`}</span>
                <strong>{`已启用 ${enabledCount}/${toolCount}`}</strong>
              </div>
              {server.lastErrorCode ? (
                <div className={"mcp-server-error"}>
                  {`错误码：${server.lastErrorCode}`}
                </div>
              ) : null}
              <div className={"mcp-server-actions"}>
                {renderActions(server)}
                {!isNotion ? (
                  <>
                    <button
                      aria-label={`编辑${server.name}连接`}
                      type={"button"}
                      disabled={busyId === String(server.id)}
                      onClick={() => {
                        setEditingServer(server);
                        setDialogOpen(true);
                      }}
                    >
                      {"编辑"}
                    </button>
                    <button
                      aria-label={`删除${server.name}连接`}
                      className={"danger"}
                      type={"button"}
                      disabled={busyId === String(server.id)}
                      onClick={() => setDeleteTarget(server)}
                    >
                      {"删除"}
                    </button>
                  </>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>

      <McpServerDialog
        open={dialogOpen}
        busy={
          busyId === "create" ||
          (editingServer && busyId === String(editingServer.id))
        }
        server={editingServer}
        onClose={handleDialogClose}
        onSubmit={editingServer ? handleUpdate : handleCreate}
      />
      <McpToolDrawer
        server={selectedServer}
        onClose={() => setSelectedServer(null)}
        onUpdated={(updated) => {
          setSelectedServer(updated);
          loadMcpServers();
        }}
      />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        danger={true}
        title={`删除“${deleteTarget?.name || "MCP连接"}”？`}
        description={"删除后将移除该连接配置和已保存的工具授权。"}
        confirmLabel={"删除连接"}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          const target = deleteTarget;
          setDeleteTarget(null);
          if (target) await handleDelete(target);
        }}
      />
    </section>
  );
}
