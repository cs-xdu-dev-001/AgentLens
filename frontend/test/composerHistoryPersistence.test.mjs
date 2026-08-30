import assert from "node:assert/strict";
import test from "node:test";

import {
  appendComposerHistory,
  composerHistoryStorageKey,
  normalizeComposerHistory,
  readComposerHistory,
  writeComposerHistory,
} from "../react/src/controller/composerHistoryPersistence.js";

function createStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}

test("composer history is isolated by stable user identity", () => {
  const storage = createStorage();
  const alice = { id: 7 };
  const bob = { id: 8 };

  assert.equal(composerHistoryStorageKey(alice), "agentlens.composerHistory.v1:7");
  assert.equal(composerHistoryStorageKey({}), "");
  assert.equal(writeComposerHistory(alice, ["Alice prompt"], storage), true);
  assert.equal(writeComposerHistory(bob, ["Bob prompt"], storage), true);
  assert.deepEqual(readComposerHistory(alice, storage).entries, ["Alice prompt"]);
  assert.deepEqual(readComposerHistory(bob, storage).entries, ["Bob prompt"]);
  assert.equal(writeComposerHistory(alice, [], storage), true);
  assert.equal(readComposerHistory(alice, storage).kind, "missing");
  assert.deepEqual(readComposerHistory(bob, storage).entries, ["Bob prompt"]);
});

test("composer history trims input, skips consecutive duplicates and keeps the newest 100 entries", () => {
  let entries = [];
  entries = appendComposerHistory(entries, "  first prompt  ");
  entries = appendComposerHistory(entries, "first prompt");
  assert.deepEqual(entries, ["first prompt"]);

  for (let index = 0; index < 102; index += 1) {
    entries = appendComposerHistory(entries, `prompt ${index}`);
  }
  assert.equal(entries.length, 100);
  assert.equal(entries[0], "prompt 2");
  assert.equal(entries.at(-1), "prompt 101");
  assert.equal(appendComposerHistory(entries, "   ").length, 100);
  assert.equal(appendComposerHistory([], "x".repeat(10_001))[0].length, 10_000);
});

test("invalid history is removed and storage failures stay non-blocking", () => {
  const storage = createStorage();
  const user = { id: 9 };
  const key = composerHistoryStorageKey(user);
  storage.setItem(key, JSON.stringify({ version: 1, entries: ["one", 2, "two", "two", ""] }));
  assert.deepEqual(normalizeComposerHistory(JSON.parse(storage.getItem(key))), ["one", "two"]);
  assert.deepEqual(readComposerHistory(user, storage), {
    kind: "history",
    entries: ["one", "two"],
  });
  storage.setItem(key, "{broken-json");
  assert.equal(readComposerHistory(user, storage).kind, "missing");
  assert.equal(storage.getItem(key), null);

  const blocked = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  assert.equal(readComposerHistory(user, blocked).kind, "unavailable");
  assert.equal(writeComposerHistory(user, ["still usable in memory"], blocked), false);
});
