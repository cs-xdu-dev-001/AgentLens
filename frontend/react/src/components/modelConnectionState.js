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
