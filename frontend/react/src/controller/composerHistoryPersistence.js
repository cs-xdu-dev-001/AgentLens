const composerHistoryStoragePrefix = "agentlens.composerHistory.v1";
const maximumHistoryEntries = 100;
const maximumEntryLength = 10_000;
const maximumStoredLength = maximumHistoryEntries * maximumEntryLength * 6 + 10_000;

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

function normalizeEntry(value) {
  if (typeof value !== "string") return "";
  return value.trim().slice(0, maximumEntryLength);
}

export function normalizeComposerHistory(value) {
  const source = Array.isArray(value) ? value : value?.entries;
  if (!Array.isArray(source)) return [];
  const entries = [];
  for (const item of source.slice(-maximumHistoryEntries)) {
    const entry = normalizeEntry(item);
    if (!entry || entries.at(-1) === entry) continue;
    entries.push(entry);
  }
  return entries;
}

export function appendComposerHistory(entries, value) {
  const current = normalizeComposerHistory(entries);
  const entry = normalizeEntry(value);
  if (!entry || current.at(-1) === entry) return current;
  return [...current, entry].slice(-maximumHistoryEntries);
}

export function composerHistoryStorageKey(user) {
  const userId = normalizeUserId(user?.id);
  return userId ? `${composerHistoryStoragePrefix}:${userId}` : "";
}

export function readComposerHistory(user, storage) {
  const key = composerHistoryStorageKey(user);
  const target = resolveStorage(storage);
  if (!key || !target) return { kind: "unavailable", entries: [] };
  try {
    const raw = target.getItem(key);
    if (raw === null) return { kind: "missing", entries: [] };
    if (raw.length > maximumStoredLength) {
      target.removeItem(key);
      return { kind: "missing", entries: [] };
    }
    let parsed;
    try {
      parsed = JSON.parse(raw);
    } catch {
      target.removeItem(key);
      return { kind: "missing", entries: [] };
    }
    const entries = normalizeComposerHistory(parsed);
    if (!entries.length) {
      target.removeItem(key);
      return { kind: "missing", entries: [] };
    }
    return { kind: "history", entries };
  } catch {
    return { kind: "unavailable", entries: [] };
  }
}

export function writeComposerHistory(user, entries, storage) {
  const key = composerHistoryStorageKey(user);
  const target = resolveStorage(storage);
  if (!key || !target) return false;
  try {
    const normalized = normalizeComposerHistory(entries);
    if (!normalized.length) {
      target.removeItem(key);
      return true;
    }
    const serialized = JSON.stringify({ version: 1, entries: normalized });
    if (serialized.length > maximumStoredLength) return false;
    target.setItem(key, serialized);
    return true;
  } catch {
    return false;
  }
}
