function operations(activity) {
  return Array.isArray(activity?.operations)
    ? activity.operations
    : [];
}

function operationTraceStep(operation) {
  const status = {
    queued: "waiting",
    running: "running",
    succeeded: "success",
    failed: "failed",
  }[operation?.status] || "waiting";
  const items = (Array.isArray(operation?.items)
    ? operation.items
    : [])
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      action: String(item.action || ""),
      content: String(item.content || ""),
    }));
  const isRecall = operation?.kind === "recall";
  return {
    stepId: String(operation?.id || ""),
    parentId: null,
    kind: "memory",
    name: isRecall ? "memory_recall" : "memory_write",
    status,
    title: isRecall
      ? "长期记忆召回"
      : status === "failed"
        ? "长期记忆写入失败"
        : status === "success"
          ? "长期记忆整理完成"
          : "正在整理长期记忆",
    errorCode: operation?.errorCode || null,
    details: {
      operationId: String(operation?.id || ""),
      items,
      attemptCount: Number(operation?.attemptCount || 0),
    },
    outputSummary: `${items.length}条`,
  };
}

export function memoryActivityTrace(activity) {
  return operations(activity).map(operationTraceStep);
}

export function mergeMemoryActivityTrace(trace, activity) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const operationSteps = new Map(
    memoryActivityTrace(activity).map((step) => [
      step.details.operationId,
      step,
    ]),
  );
  return safeTrace.map((step) => {
    const operationId = step?.details?.operationId;
    const update = operationSteps.get(operationId);
    if (!update) return step;
    return {
      ...step,
      ...update,
      stepId: step.stepId,
      parentId: step.parentId ?? null,
      details: {
        ...(step.details || {}),
        ...update.details,
      },
    };
  });
}
