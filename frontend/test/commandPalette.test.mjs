import assert from "node:assert/strict";
import test from "node:test";
import { composerCommandSuggestions, searchComposerCommands, WEB_COMPOSER_COMMANDS } from "../react/src/components/composerCommands.js";

test("global command search shares slash names, aliases, Chinese labels and fuzzy ranking", () => {
  for (const query of ["model", "/model", " MODEL ", "切换模型", "modle"]) {
    assert.equal(searchComposerCommands(WEB_COMPOSER_COMMANDS, query)[0].value, "/model");
  }
  assert.equal(searchComposerCommands(WEB_COMPOSER_COMMANDS, "/fork")[0].value, "/branch");
  assert.deepEqual(searchComposerCommands(WEB_COMPOSER_COMMANDS, "zzzz-no-such-command"), []);
});

test("palette ranking cannot reintroduce unavailable runtime recovery actions", () => {
  const idle = composerCommandSuggestions("");
  for (const name of ["/stop", "/retry", "/continue", "/fix"]) {
    assert.equal(searchComposerCommands(idle, name).some(item => item.value === name), false);
  }
  const running = composerCommandSuggestions("", { sending: true });
  assert.equal(searchComposerCommands(running, "stop")[0].value, "/stop");
  const failed = composerCommandSuggestions("", { recoveryActions: ["retry", "fix"], queuePaused: true });
  for (const name of ["/retry", "/continue", "/fix"]) {
    assert.equal(searchComposerCommands(failed, name)[0].value, name);
  }
});

test("empty palette preserves recent command ordering without mutating the shared catalog", () => {
  const original = WEB_COMPOSER_COMMANDS.map(item => item.value);
  const commands = composerCommandSuggestions("", { usage: { "/model": 8 } });
  assert.equal(searchComposerCommands(commands, "")[0].value, "/model");
  assert.deepEqual(WEB_COMPOSER_COMMANDS.map(item => item.value), original);
});
