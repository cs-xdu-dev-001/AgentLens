const activeSessionStoragePrefix = "agentlens.activeSessionId.v1";

function resolveStorage(storage) {
  if (storage !== undefined) return storage;
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

function normalizeSessionId(value) {
  const sessionId = String(value ?? "").trim();
  return sessionId.length <= 200 ? sessionId : "";
}

function normalizeUserId(value) {
  const userId = String(value ?? "").trim();
  return /^[1-9]\d{0,18}$/.test(userId) ? userId : "";
}

export function activeSessionStorageKey(user) {
  const userId = normalizeUserId(user?.id);
  return userId
    ? `${activeSessionStoragePrefix}:${encodeURIComponent(userId)}`
    : "";
}

export function readActiveSessionPreference(user, storage) {
  const key = activeSessionStorageKey(user);
  const target = resolveStorage(storage);
  if (!key || !target) return { kind: "unavailable", sessionId: "" };
  try {
    const value = target.getItem(key);
    if (value === null) return { kind: "missing", sessionId: "" };
    const sessionId = normalizeSessionId(value);
    if (String(value).trim() && !sessionId) {
      return { kind: "missing", sessionId: "" };
    }
    return sessionId
      ? { kind: "session", sessionId }
      : { kind: "new", sessionId: "" };
  } catch {
    return { kind: "unavailable", sessionId: "" };
  }
}

export function writeActiveSessionPreference(user, sessionId, storage) {
  const key = activeSessionStorageKey(user);
  const target = resolveStorage(storage);
  if (!key || !target) return false;
  try {
    const normalizedSessionId = normalizeSessionId(sessionId);
    if (String(sessionId ?? "").trim() && !normalizedSessionId) return false;
    target.setItem(key, normalizedSessionId);
    return true;
  } catch {
    return false;
  }
}

export function clearActiveSessionPreference(user, storage) {
  const key = activeSessionStorageKey(user);
  const target = resolveStorage(storage);
  if (!key || !target) return false;
  try {
    target.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export function selectSessionToRestore(sessions, preference) {
  if (["new", "unavailable"].includes(preference?.kind)) return null;
  const candidates = (Array.isArray(sessions) ? sessions : [])
    .filter((session) => normalizeSessionId(session?.id));
  if (preference?.kind === "session") {
    const remembered = candidates.find(
      (session) => normalizeSessionId(session.id) === preference.sessionId,
    );
    if (remembered) return remembered;
  }
  return candidates[0] || null;
}
