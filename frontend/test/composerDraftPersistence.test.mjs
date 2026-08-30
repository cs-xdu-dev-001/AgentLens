import assert from "node:assert/strict";
import test from "node:test";

import {
  clearComposerDraft,
  composerDraftStorageKey,
  readComposerDraft,
  writeComposerDraft,
} from "../react/src/controller/composerDraftPersistence.js";

function createStorage() {
  const values = new Map();
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
}

test("composer drafts are isolated by stable user and session identities", () => {
  const storage = createStorage();
  const alice = { id: 7 };
  const bob = { id: 8 };

  assert.equal(composerDraftStorageKey(alice, ""), "agentlens.composerDraft.v1:7:new");
  assert.equal(
    composerDraftStorageKey(alice, "session/a"),
    "agentlens.composerDraft.v1:7:session:session%2Fa",
  );
  assert.equal(writeComposerDraft(alice, "session-a", { question: "Alice A" }, storage), true);
  assert.equal(writeComposerDraft(alice, "session-b", { question: "Alice B" }, storage), true);
  assert.equal(writeComposerDraft(bob, "session-a", { question: "Bob A" }, storage), true);
  assert.equal(readComposerDraft(alice, "session-a", storage).draft.question, "Alice A");
  assert.equal(readComposerDraft(alice, "session-b", storage).draft.question, "Alice B");
  assert.equal(readComposerDraft(bob, "session-a", storage).draft.question, "Bob A");
});

test("composer drafts preserve exact text and a bounded Skill selection", () => {
  const storage = createStorage();
  const user = { id: 9 };
  const draft = {
    question: "  保留换行\n和结尾空格  ",
    skill: { id: 42, name: "检查代码", slug: "check", secret: "drop-me" },
  };

  assert.equal(writeComposerDraft(user, "work", draft, storage), true);
  assert.deepEqual(readComposerDraft(user, "work", storage), {
    kind: "draft",
    draft: {
      question: draft.question,
      skill: { id: 42, name: "检查代码", slug: "check" },
    },
  });
  assert.equal(clearComposerDraft(user, "work", storage), true);
  assert.equal(readComposerDraft(user, "work", storage).kind, "missing");
});

test("empty and invalid drafts are removed while storage failures stay non-blocking", () => {
  const storage = createStorage();
  const user = { id: 10 };
  writeComposerDraft(user, "session", { question: "old" }, storage);
  assert.equal(writeComposerDraft(user, "session", { question: "", skill: null }, storage), true);
  assert.equal(readComposerDraft(user, "session", storage).kind, "missing");
  storage.setItem(composerDraftStorageKey(user, "session"), "{broken-json");
  assert.equal(readComposerDraft(user, "session", storage).kind, "missing");
  assert.equal(
    writeComposerDraft(user, "session", { question: "x".repeat(1_000_001) }, storage),
    false,
  );

  const blocked = {
    getItem: () => { throw new Error("blocked"); },
    setItem: () => { throw new Error("blocked"); },
    removeItem: () => { throw new Error("blocked"); },
  };
  assert.equal(readComposerDraft(user, "session", blocked).kind, "unavailable");
  assert.equal(writeComposerDraft(user, "session", { question: "still editable" }, blocked), false);
  assert.equal(clearComposerDraft(user, "session", blocked), false);
  assert.equal(composerDraftStorageKey({}, "session"), "");
  assert.equal(composerDraftStorageKey(user, "x".repeat(201)), "");
});
