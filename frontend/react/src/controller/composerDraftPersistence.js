const composerDraftStoragePrefix = "agentlens.composerDraft.v1";
const maximumDraftLength = 1_000_000;

function resolveStorage(storage) {
  if (storage !== undefined) return storage;
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

function normalizeUserId(value) {
  const userId = String(value ?? "").trim();
  return /^[1-9]\d{0,18}$/.test(userId) ? userId : "";
}

function normalizeSessionId(value) {
  const sessionId = String(value ?? "").trim();
  return sessionId.length <= 200 ? sessionId : null;
}

function normalizeSkill(value) {
  if (!value || typeof value !== "object") return null;
  const rawId = value.id;
  let id;
  if (typeof rawId === "number" && Number.isSafeInteger(rawId) && rawId > 0) {
    id = rawId;
  } else if (typeof rawId === "string") {
    id = rawId.trim().slice(0, 200);
  } else {
    return null;
  }
  if (id === "") return null;
  return {
    id,
    name: String(value.name ?? "").trim().slice(0, 160),
    slug: String(value.slug ?? "").trim().slice(0, 160),
  };
}

export function normalizeComposerDraft(value) {
  if (!value || typeof value !== "object") return null;
  const question = String(value.question ?? "");
  if (question.length > maximumDraftLength) return null;
  const skill = normalizeSkill(value.skill);
  if (!question && !skill) return null;
  return { question, skill };
}

export function composerDraftStorageKey(user, sessionId = "") {
  const userId = normalizeUserId(user?.id);
  const normalizedSessionId = normalizeSessionId(sessionId);
  if (!userId || normalizedSessionId === null) return "";
  const scope = normalizedSessionId
    ? `session:${encodeURIComponent(normalizedSessionId)}`
    : "new";
  return `${composerDraftStoragePrefix}:${userId}:${scope}`;
}

export function readComposerDraft(user, sessionId = "", storage) {
  const key = composerDraftStorageKey(user, sessionId);
  const target = resolveStorage(storage);
  if (!key || !target) return { kind: "unavailable", draft: null };
  try {
    const raw = target.getItem(key);
    if (raw === null) return { kind: "missing", draft: null };
    if (raw.length > maximumDraftLength + 2_000) {
      target.removeItem(key);
      return { kind: "missing", draft: null };
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      target.removeItem(key);
      return { kind: "missing", draft: null };
    }
    const draft = normalizeComposerDraft(parsed);
    if (!draft) {
      target.removeItem(key);
      return { kind: "missing", draft: null };
    }
    return { kind: "draft", draft };
  } catch {
    return { kind: "unavailable", draft: null };
  }
}

export function writeComposerDraft(user, sessionId = "", draft, storage) {
  const key = composerDraftStorageKey(user, sessionId);
  const target = resolveStorage(storage);
  if (!key || !target) return false;
  try {
    if (String(draft?.question ?? "").length > maximumDraftLength) {
      target.removeItem(key);
      return false;
    }
    const normalized = normalizeComposerDraft(draft);
    if (!normalized) {
      target.removeItem(key);
      return true;
    }
    target.setItem(key, JSON.stringify({ version: 1, ...normalized }));
    return true;
  } catch {
    return false;
  }
}

export function clearComposerDraft(user, sessionId = "", storage) {
  const key = composerDraftStorageKey(user, sessionId);
  const target = resolveStorage(storage);
  if (!key || !target) return false;
  try {
    target.removeItem(key);
    return true;
  } catch {
    return false;
  }
}
