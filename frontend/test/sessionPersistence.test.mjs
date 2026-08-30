import assert from "node:assert/strict";
import test from "node:test";

import {
  activeSessionStorageKey,
  clearActiveSessionPreference,
  readActiveSessionPreference,
  selectSessionToRestore,
  writeActiveSessionPreference,
} from "../react/src/controller/sessionPersistence.js";

function createStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

test("active session preferences are isolated by stable user id", () => {
  const storage = createStorage();
  const firstUser = { id: 7, email: "first@example.com" };
  const secondUser = { id: 8, email: "second@example.com" };

  assert.equal(activeSessionStorageKey(firstUser), "agentlens.activeSessionId.v1:7");
  assert.deepEqual(readActiveSessionPreference(firstUser, storage), {
    kind: "missing",
    sessionId: "",
  });
  assert.equal(writeActiveSessionPreference(firstUser, "session-a", storage), true);
  assert.deepEqual(readActiveSessionPreference(firstUser, storage), {
    kind: "session",
    sessionId: "session-a",
  });
  assert.deepEqual(readActiveSessionPreference(secondUser, storage), {
    kind: "missing",
    sessionId: "",
  });
  assert.equal(clearActiveSessionPreference(firstUser, storage), true);
  assert.equal(readActiveSessionPreference(firstUser, storage).kind, "missing");
});

test("an explicit new chat survives reload without reopening history", () => {
  const storage = createStorage();
  const user = { id: 9 };
  writeActiveSessionPreference(user, "", storage);
  const preference = readActiveSessionPreference(user, storage);

  assert.deepEqual(preference, { kind: "new", sessionId: "" });
  assert.equal(selectSessionToRestore([{ id: "latest" }], preference), null);
});

test("restore selection prefers the remembered session and falls back to newest", () => {
  const sessions = [{ id: "newest" }, { id: "remembered" }];

  assert.equal(
    selectSessionToRestore(sessions, { kind: "session", sessionId: "remembered" }).id,
    "remembered",
  );
  assert.equal(
    selectSessionToRestore(sessions, { kind: "session", sessionId: "deleted" }).id,
    "newest",
  );
  assert.equal(
    selectSessionToRestore(sessions, { kind: "missing", sessionId: "" }).id,
    "newest",
  );
});

test("storage failures degrade without exposing or blocking the workspace", () => {
  const blockedStorage = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
  };

  assert.deepEqual(readActiveSessionPreference({ id: 10 }, blockedStorage), {
    kind: "unavailable",
    sessionId: "",
  });
  assert.equal(writeActiveSessionPreference({ id: 10 }, "session", blockedStorage), false);
  assert.equal(activeSessionStorageKey({}), "");
  assert.equal(activeSessionStorageKey({ id: "not-a-number" }), "");
  assert.equal(
    writeActiveSessionPreference({ id: 10 }, "x".repeat(201), createStorage()),
    false,
  );
});
