const connectionFailurePattern = /(?:\bHTTP\s*[45]\d{2}\b|\b(?:error|failed|failure|invalid|unavailable)\b|失败|错误|不可用)/i;

const successStatuses = new Set(["available", "success"]);
const failureStatuses = new Set(["unavailable", "error", "failed", "failure"]);

export function connectionResultStatus(result) {
  const status = String(result?.status || "").trim().toLowerCase();
  if (status === "checking") return "checking";

  const message = String(result?.message || "");
  if (failureStatuses.has(status) || connectionFailurePattern.test(message)) {
    return "error";
  }
  if (successStatuses.has(status)) return "success";

  // 未知状态不能冒充连接成功。
  return "error";
}

const presentations = {
  authentication_failed: {
    title: "API Key无效",
    summary: "模型服务拒绝了当前凭据。",
    action: "检查Key是否有效，并确认它属于当前API地址。",
  },
  access_denied: {
    title: "当前Key无访问权限",
    summary: "服务可达，但当前分组不能调用这个模型或接口。",
    action: "检查Key分组、模型映射和接口协议权限。",
  },
  not_found: {
    title: "接口或模型不存在",
    summary: "API地址、模型名称或接口路由没有匹配成功。",
    action: "确认地址以/v1结尾，并使用/models实际公开的模型名。",
  },
  rate_limited: {
    title: "请求过于频繁",
    summary: "模型服务已触发额度或速率限制。",
    action: "稍后重试，或检查当前Key的RPM和并发额度。",
  },
  protocol_unsupported: {
    title: "接口协议不兼容",
    summary: "当前渠道不支持所选调用协议。",
    action: "在Responses API与Chat Completions之间切换后重试。",
  },
  upstream_unavailable: {
    title: "当前渠道不可用",
    summary: "中转站没有为这个模型提供可用上游。",
    action: "检查模型名称、渠道状态和Key所属分组权限。",
  },
  network_error: {
    title: "无法连接模型服务",
    summary: "请求超时或网络连接失败。",
    action: "检查API地址、代理、防火墙和服务状态后重试。",
  },
  incompatible_parameters: {
    title: "模型参数不兼容",
    summary: "当前模型拒绝已有采样参数。",
    action: "清空旧temperature、top_p和max_tokens后重试。",
  },
  invalid_request: {
    title: "请求配置不兼容",
    summary: "模型服务拒绝了当前请求格式。",
    action: "检查模型名称、接口协议和渠道参数映射。",
  },
  connection_failed: {
    title: "连接检查失败",
    summary: "模型没有返回有效响应。",
    action: "检查配置后重试；技术详情可用于排查上游错误。",
  },
};

function inferredCode(result) {
  const message = String(result?.message || "").toLowerCase();
  if (/http\s*401|authentication|unauthorized/.test(message)) return "authentication_failed";
  if (/http\s*403|forbidden/.test(message)) return "access_denied";
  if (/http\s*404|model_not_found|not found/.test(message)) return "not_found";
  if (/http\s*429|rate_limit/.test(message)) return "rate_limited";
  if (/invalid temperature|unsupported parameter/.test(message)) return "incompatible_parameters";
  if (/(?:not support|unsupported).*(?:chat completion|responses|protocol)/.test(message)) return "protocol_unsupported";
  if (/http\s*503|no available channel|unavailable channel|无可用渠道/.test(message)) return "upstream_unavailable";
  if (/timeout|timed out|connection error/.test(message)) return "network_error";
  if (/http\s*400|invalid_request/.test(message)) return "invalid_request";
  return "connection_failed";
}

export function connectionResultPresentation(result) {
  const status = connectionResultStatus(result);
  if (status === "checking") {
    return {status, code: "checking", title: "正在检查连接", summary: "正在请求模型服务。", action: ""};
  }
  if (status === "success") {
    return {status, code: "available", title: "连接可用", summary: "模型已返回有效响应。", action: ""};
  }
  if (["responses", "chat_completions"].includes(result?.recommendedApiMode)) {
    const current = result?.apiMode === "responses"
      ? "Responses API"
      : "Chat Completions";
    const recommended = result.recommendedApiMode === "responses"
      ? "Responses API"
      : "Chat Completions";
    return {
      status,
      code: "protocol_fallback_available",
      title: "检测到可用协议",
      summary: `${current}连接失败，但${recommended}已返回有效响应。`,
      action: `改用${recommended}并重新检查。`,
    };
  }
  const code = presentations[result?.code] ? result.code : inferredCode(result);
  return {status, code, ...presentations[code]};
}
