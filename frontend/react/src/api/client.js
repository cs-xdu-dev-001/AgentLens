import { BACKEND_UNAVAILABLE_MESSAGE, normalizeErrorMessage } from "./errors.js";

export class ApiError extends Error {
  constructor(message, { status = 0, code = null, data = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function notifyAuthRequired(detail = {}) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("knowflow:react-auth-required", { detail }));
}

async function parseResponse(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new ApiError(normalizeErrorMessage(text, response.statusText || "请求失败"), { status: response.status });
  }
}

export async function apiRequest(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = new Headers(options.headers || {});
  let body = options.body;

  if (body && !isFormData && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(path, {
      ...options,
      body,
      headers,
      credentials: "include",
    });
  } catch (error) {
    if (path.startsWith("/api")) {
      throw new ApiError(BACKEND_UNAVAILABLE_MESSAGE, { status: 0, code: "BACKEND_UNAVAILABLE", data: { cause: error?.message || "fetch failed" } });
    }
    throw error;
  }

  let payload;
  try {
    payload = await parseResponse(response);
  } catch (error) {
    if (error instanceof ApiError && path.startsWith("/api") && response.status >= 500) {
      throw new ApiError(normalizeErrorMessage(error, BACKEND_UNAVAILABLE_MESSAGE), { status: response.status, data: error.data });
    }
    throw error;
  }

  if (!response.ok) {
    const detail =
      payload?.detail && typeof payload?.detail === "object"
        ? payload.detail
        : null;
    const messageSource =
      detail?.message ??
      (typeof payload?.detail === "string"
        ? payload.detail
        : payload?.message ?? response.statusText);
    const message = normalizeErrorMessage(messageSource, "请求失败");
    if (response.status === 401) {
      notifyAuthRequired({ path, status: response.status, message });
    }
    throw new ApiError(message, {
      status: response.status,
      code: detail?.code ?? payload?.code ?? null,
      data: detail?.data ?? payload?.data ?? payload,
    });
  }
  if (payload && payload.code !== 0) {
    throw new ApiError(normalizeErrorMessage(payload.message, "请求失败"), {
      status: response.status,
      code: payload.code,
      data: payload.data,
    });
  }
  return payload?.data ?? payload;
}

export const authApi = {
  getCurrentUser: () => apiRequest("/api/auth/me"),
  login: (account, password) => apiRequest("/api/auth/login", { method: "POST", body: { account, password } }),
  register: ({ username, email, password, displayName }) =>
    apiRequest("/api/auth/register", { method: "POST", body: { username, email, password, displayName } }),
  logout: () => apiRequest("/api/auth/logout", { method: "POST" }),
  decideCliDevice: (userCode, decision) =>
    apiRequest("/api/auth/cli/device/decision", { method: "POST", body: { userCode, decision } }),
};

export const modelConfigApi = {
  list: () => apiRequest("/api/model-configs"),
  get: (id) => apiRequest(`/api/model-configs/${id}`),
  create: (payload) => apiRequest("/api/model-configs", { method: "POST", body: payload }),
  update: (id, payload) => apiRequest(`/api/model-configs/${id}`, { method: "PUT", body: payload }),
  test: (id) => apiRequest(`/api/model-configs/${id}/test`, { method: "POST" }),
  setDefault: (id) => apiRequest(`/api/model-configs/${id}/default`, { method: "POST" }),
  delete: (id) => apiRequest(`/api/model-configs/${id}`, { method: "DELETE" }),
};

export const toolConfigApi = {
  list: () => apiRequest("/api/tool-configs"),
  save: (toolName, payload) => apiRequest(`/api/tool-configs/${toolName}`, { method: "PUT", body: payload }),
  test: (toolName) => apiRequest(`/api/tool-configs/${toolName}/test`, { method: "POST" }),
  delete: (toolName) => apiRequest(`/api/tool-configs/${toolName}`, { method: "DELETE" }),
};

export const mcpApi = {
  list: () => apiRequest("/api/mcp/servers"),
  create: (payload) => apiRequest("/api/mcp/servers", { method: "POST", body: payload }),
  update: (id, payload) => apiRequest(`/api/mcp/servers/${id}`, { method: "PATCH", body: payload }),
  delete: (id) => apiRequest(`/api/mcp/servers/${id}`, { method: "DELETE" }),
  test: (id) => apiRequest(`/api/mcp/servers/${id}/test`, { method: "POST" }),
  refreshTools: (id) => apiRequest(`/api/mcp/servers/${id}/refresh-tools`, { method: "POST" }),
  disconnect: (id) => apiRequest(`/api/mcp/servers/${id}/disconnect`, { method: "POST" }),
  startOAuth: (id, returnTo) =>
    apiRequest(`/api/mcp/servers/${id}/oauth/start`, {
      method: "POST",
      body: { returnTo },
    }),
};

export const approvalApi = {
  resolve: (approvalId, decision) =>
    apiRequest(`/api/agent/approvals/${approvalId}`, {
      method: "POST",
      body: { decision },
    }),
};

export const agentRunApi = {
  get: (runId) => apiRequest(`/api/agent/runs/${runId}`),
  start: (runId) =>
    apiRequest(`/api/agent/runs/${runId}/start`, {
      method: "POST",
    }),
  replan: (runId) =>
    apiRequest(`/api/agent/runs/${runId}/replan`, {
      method: "POST",
    }),
  resume: (runId) =>
    apiRequest(`/api/agent/runs/${runId}/resume`, {
      method: "POST",
    }),
  restart: (runId) =>
    apiRequest(`/api/agent/runs/${runId}/restart`, {
      method: "POST",
    }),
  cancel: (runId) =>
    apiRequest(`/api/agent/runs/${runId}/cancel`, {
      method: "POST",
    }),
};

export const runtimeApi = {
  get: () => apiRequest("/api/runtime"),
};

function workspacePath(path) {
  return String(path || "")
    .split("/")
    .filter(Boolean)
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export const workspaceApi = {
  status: () => apiRequest("/api/workspace"),
  list: (path = "") =>
    apiRequest(`/api/workspace/files?${new URLSearchParams({ path })}`),
  upload: (path, file, overwrite = false) => {
    const body = new FormData();
    body.append("path", path);
    body.append("overwrite", overwrite ? "true" : "false");
    body.append("file", file);
    return apiRequest("/api/workspace/files", { method: "POST", body });
  },
  downloadUrl: (path) => `/api/workspace/files/${workspacePath(path)}`,
  delete: (path) =>
    apiRequest(`/api/workspace/files/${workspacePath(path)}`, {
      method: "DELETE",
    }),
};

export const memoryApi = {
  settings: () => apiRequest("/api/memory/settings"),
  setEnabled: (enabled) =>
    apiRequest("/api/memory/settings", {
      method: "PUT",
      body: { enabled },
    }),
  list: () => apiRequest("/api/memories"),
  update: (id, content) =>
    apiRequest(`/api/memories/${id}`, {
      method: "PUT",
      body: { content },
    }),
  delete: (id) =>
    apiRequest(`/api/memories/${id}`, { method: "DELETE" }),
  clear: () => apiRequest("/api/memories", { method: "DELETE" }),
  activity: (messageId) =>
    apiRequest(`/api/messages/${messageId}/memory-activity`),
  retryOperation: (operationId) =>
    apiRequest(`/api/memory/operations/${operationId}/retry`, {
      method: "POST",
    }),
};

export const sessionApi = {
  list: () => apiRequest("/api/sessions"),
  messages: (id) => apiRequest(`/api/sessions/${id}/messages`),
  update: (id, payload) => apiRequest(`/api/sessions/${id}`, { method: "PUT", body: payload }),
  delete: (id) => apiRequest(`/api/sessions/${id}`, { method: "DELETE" }),
};

export const knowledgeApi = {
  list: () => apiRequest("/api/knowledge-bases"),
  get: (id) => apiRequest(`/api/knowledge-bases/${id}`),
  create: (payload) => apiRequest("/api/knowledge-bases", { method: "POST", body: payload }),
  update: (id, payload) => apiRequest(`/api/knowledge-bases/${id}`, { method: "PUT", body: payload }),
  delete: (id) => apiRequest(`/api/knowledge-bases/${id}`, { method: "DELETE" }),
};

export const documentApi = {
  list: (knowledgeBaseId) => apiRequest(`/api/knowledge-bases/${knowledgeBaseId}/documents`),
  upload: (knowledgeBaseId, file) => {
    const data = new FormData();
    data.append("knowledgeBaseId", knowledgeBaseId);
    data.append("file", file);
    return apiRequest(`/api/knowledge-bases/${knowledgeBaseId}/documents`, { method: "POST", body: data });
  },
  chunks: (id) => apiRequest(`/api/documents/${id}/chunks`),
  reindex: (id) => apiRequest(`/api/documents/${id}/reindex`, { method: "POST" }),
  delete: (id) => apiRequest(`/api/documents/${id}`, { method: "DELETE" }),
};

export const retrievalApi = {
  debug: (payload) => apiRequest("/api/retrieval/debug", { method: "POST", body: payload }),
};

export const skillApi = {
  list: () => apiRequest("/api/skills"),
  get: (id) => apiRequest(`/api/skills/${id}`),
  content: (id) => apiRequest(`/api/skills/${id}/content`),
  inspectGitHub: (payload) =>
    apiRequest("/api/skills/import/github/inspect", {
      method: "POST",
      body: payload,
    }),
  inspectUpload: (file) => {
    const data = new FormData();
    data.append("file", file);
    return apiRequest("/api/skills/import/upload/inspect", {
      method: "POST",
      body: data,
    });
  },
  install: (importId, enabled = false) =>
    apiRequest(`/api/skills/import/${importId}/install`, {
      method: "POST",
      body: { enabled },
    }),
  setEnabled: (id, enabled) =>
    apiRequest(`/api/skills/${id}`, {
      method: "PATCH",
      body: { enabled },
    }),
  checkUpdate: (id) =>
    apiRequest(`/api/skills/${id}/check-update`, { method: "POST" }),
  update: (id, enabled = false) =>
    apiRequest(`/api/skills/${id}/update`, {
      method: "POST",
      body: { enabled },
    }),
  delete: (id) => apiRequest(`/api/skills/${id}`, { method: "DELETE" }),
};
