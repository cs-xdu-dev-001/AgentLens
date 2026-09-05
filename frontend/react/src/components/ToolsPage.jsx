import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { toolConfigApi } from "../api/client.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { McpServerPanel } from "./McpServerPanel.jsx";
import { ToolConfigPanel } from "./ToolConfigPanel.jsx";

export function ToolsPage({ active = false }) {
  const [toolBusy, setToolBusy] = useState(false);
  const [toolValues, setToolValues] = useState({
    enabled: false,
    apiKey: "",
  });
  const [webSearchConfig, setWebSearchConfig] = useState(null);
  const [mcpServerCount, setMcpServerCount] = useState(0);

  const loadToolConfigs = useCallback(async () => {
    try {
      const configs = await toolConfigApi.list();
      const webSearch = (Array.isArray(configs) ? configs : []).find(
        (item) => item.toolName === "web_search",
      ) || null;
      setWebSearchConfig(webSearch);
      setToolValues({
        enabled: Boolean(webSearch?.enabled),
        apiKey: "",
      });
    } catch (error) {
      notifyError(error, "加载工具配置失败");
    }
  }, []);

  useEffect(() => {
    if (active) loadToolConfigs();
  }, [active, loadToolConfigs]);

  useEffect(() => {
    if (!active || typeof window === "undefined") return;
    const url = new URL(window.location.href);
    const mcpResult = url.searchParams.get("mcpResult");
    const mcpError = url.searchParams.get("mcpError");
    if (!mcpResult && !mcpError) return;
    if (mcpResult) {
      notifyToast("MCP授权已完成");
    } else {
      notifyToast(`MCP授权失败：${mcpError}`, {
        duration: 4200,
        tone: "error",
      });
    }
    url.searchParams.delete("mcpResult");
    url.searchParams.delete("mcpError");
    window.history.replaceState(
      window.history.state,
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  }, [active]);

  const handleServersChange = useCallback((servers) => {
    setMcpServerCount(Array.isArray(servers) ? servers.length : 0);
  }, []);

  const handleToolChange = (event) => {
    const { checked, name, type, value } = event.target;
    setToolValues((currentValues) => ({
      ...currentValues,
      [name]: type === "checkbox" ? checked : value,
    }));
  };

  const handleToolSubmit = async (event) => {
    event.preventDefault();
    setToolBusy(true);
    try {
      const apiKey = toolValues.apiKey.trim();
      const payload = { enabled: toolValues.enabled };
      if (apiKey) payload.apiKey = apiKey;
      const saved = await toolConfigApi.save("web_search", payload);
      setWebSearchConfig(saved);
      setToolValues({
        enabled: Boolean(saved?.enabled),
        apiKey: "",
      });
      notifyToast("联网搜索配置已保存");
    } catch (error) {
      notifyError(error, "保存工具配置失败");
    } finally {
      setToolBusy(false);
    }
  };

  const handleToolTest = async () => {
    setToolBusy(true);
    try {
      const result = await toolConfigApi.test("web_search");
      notifyToast(result?.message || "Tavily连接检查完成");
    } catch (error) {
      notifyError(error, "检查Tavily连接失败");
    } finally {
      setToolBusy(false);
    }
  };

  const handleToolDelete = async () => {
    setToolBusy(true);
    try {
      await toolConfigApi.delete("web_search");
      setWebSearchConfig(null);
      setToolValues({ enabled: false, apiKey: "" });
      notifyToast("联网搜索配置已清除");
    } catch (error) {
      notifyError(error, "清除工具配置失败");
    } finally {
      setToolBusy(false);
    }
  };

  const toolStatus = webSearchConfig?.configured
    ? webSearchConfig.enabled
      ? "已启用"
      : "已停用"
    : "待配置";

  return (
    <section className={active ? "page active" : "page"} id={"page-tools"}>
      <div className={"workspace-page tools-workspace"}>
        <header className={"settings-header tools-header"}>
          <h1>{"工具与MCP"}</h1>
        </header>
        <div className={"tools-content"}>
          <section className={"tools-overview"} aria-label={"接入概览"}>
            <div>
              <span>{"原生工具"}</span>
              <strong>{"1"}</strong>
            </div>
            <div>
              <span>{"MCP连接"}</span>
              <strong>{mcpServerCount}</strong>
            </div>
          </section>
          <section className={"tool-inventory panel"} aria-label={"可用工具"}>
            <div className={"panel-title"}>
              <h2>{"可用工具"}</h2>
            </div>
            <div className={"tool-inventory-row"}>
              <span className={"tool-inventory-icon"} aria-hidden={"true"}>
                <Search size={19} strokeWidth={1.8} />
              </span>
              <div>
                <strong>{"web_search"}</strong>
                <span>{"联网搜索 · Tavily"}</span>
              </div>
              <span className={`tool-state ${webSearchConfig?.enabled ? "enabled" : ""}`}>
                {toolStatus}
              </span>
            </div>
          </section>
          <ToolConfigPanel
            busy={toolBusy}
            config={webSearchConfig}
            values={toolValues}
            onChange={handleToolChange}
            onDelete={handleToolDelete}
            onSubmit={handleToolSubmit}
            onTest={handleToolTest}
          />
          <McpServerPanel
            active={active}
            onServersChange={handleServersChange}
          />
        </div>
      </div>
    </section>
  );
}
