from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def main() -> None:
    composer = (FRONTEND / "react/src/components/ChatComposerForm.jsx").read_text(encoding="utf-8")
    picker = (FRONTEND / "react/src/components/WorkspaceMentionPicker.jsx").read_text(encoding="utf-8")
    client = (FRONTEND / "react/src/api/client.js").read_text(encoding="utf-8")
    router = (ROOT / "backend/knowflow/routers/workspaces.py").read_text(encoding="utf-8")
    assert "collectWorkspaceMentionPaths" in composer
    assert "workspaceApi.mentions()" in composer
    assert "workspaceApi.list(current)" not in composer
    assert "workspaceMentionCommonPrefix" in composer
    assert "mentionsLoadedAtRef" in composer
    assert 'apiRequest("/api/workspace/mentions")' in client
    assert '@router.get("/api/workspace/mentions"' in router
    assert "workspace-mention-listbox" in composer
    assert "@引用文件" in composer
    assert 'aria-label={"工作区文件"}' in picker

    script = r'''
import assert from "node:assert/strict";
import {
  applyWorkspaceMention,
  workspaceMentionAtCursor,
  workspaceMentionCommonPrefix,
  workspaceMentionSuggestions,
} from "./react/src/components/composerMentions.js";

const mention = workspaceMentionAtCursor("ask @app", 8);
assert.deepEqual(mention, {start: 4, end: 8, query: "app"});
const suggestions = workspaceMentionSuggestions([
  "src/",
  "src/app.jsx",
  "docs/guide.md",
], mention.query);
assert.equal(suggestions[0], "src/app.jsx");
assert.equal(
  workspaceMentionCommonPrefix(["src/app.jsx", "src/api.js"]),
  "src/ap",
);
assert.deepEqual(
  applyWorkspaceMention("ask @app", mention, "src/app.jsx"),
  {value: "ask @src/app.jsx ", cursor: 17},
);
assert.deepEqual(
  applyWorkspaceMention("read @doc", {start: 5, end: 9}, "docs/my guide.md"),
  {value: "read @\"docs/my guide.md\" ", cursor: 25},
);
assert.deepEqual(
  applyWorkspaceMention("read @doc", {start: 5, end: 9}, "docs/my guide", {complete: false}),
  {value: "read @\"docs/my guide", cursor: 20},
);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        cwd=FRONTEND,
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    print("frontend composer workspace mention checks passed")


if __name__ == "__main__":
    main()
