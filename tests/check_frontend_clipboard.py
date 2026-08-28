from __future__ import annotations

import json
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    utility = read("frontend/react/src/controller/clipboard.js")
    assert "export async function copyTextToClipboard" in utility
    assert "copyWithLegacyCommand" in utility
    assert "restoreSelection" in utility

    for path in (
        "frontend/react/src/controller/bridgeBindings.js",
        "frontend/react/src/components/AgentArtifactList.jsx",
        "frontend/react/src/components/AgentTraceStepDetail.jsx",
        "frontend/react/src/components/AuthScreen.jsx",
        "frontend/react/src/components/AgentWindowFeedback.jsx",
    ):
        source = read(path)
        assert "copyTextToClipboard" in source, f"missing shared clipboard helper: {path}"
        assert "navigator.clipboard.writeText" not in source, f"direct clipboard write remains: {path}"

    script = textwrap.dedent(
        """
        import assert from "node:assert/strict";
        import { copyTextToClipboard } from "./frontend/react/src/controller/clipboard.js";

        const originalNavigator = globalThis.navigator;
        const originalDocument = globalThis.document;

        let writes = [];
        Object.defineProperty(globalThis, "navigator", {
          configurable: true,
          value: { clipboard: { writeText: async (value) => writes.push(value) } },
        });
        await copyTextToClipboard("primary path");
        assert.deepEqual(writes, ["primary path"]);

        let fallbackCalls = 0;
        const selection = {
          rangeCount: 0,
          removeAllRanges() {},
          addRange() {},
        };
        const textarea = {
          style: {},
          value: "",
          setAttribute() {},
          focus() {},
          select() {},
          setSelectionRange() {},
          remove() {},
        };
        const document = {
          body: { appendChild(node) { textarea.value = node.value; } },
          createElement(name) {
            assert.equal(name, "textarea");
            return textarea;
          },
          getSelection() { return selection; },
          execCommand(command) {
            assert.equal(command, "copy");
            fallbackCalls += 1;
            return true;
          },
        };
        Object.defineProperty(globalThis, "document", { configurable: true, value: document });
        Object.defineProperty(globalThis, "navigator", {
          configurable: true,
          value: { clipboard: { writeText: async () => { throw new Error("denied"); } } },
        });
        await copyTextToClipboard("fallback path");
        assert.equal(fallbackCalls, 1);
        assert.equal(textarea.value, "fallback path");

        document.execCommand = () => false;
        await assert.rejects(() => copyTextToClipboard("unavailable"), /Clipboard API unavailable/);

        if (originalNavigator === undefined) delete globalThis.navigator;
        else Object.defineProperty(globalThis, "navigator", { configurable: true, value: originalNavigator });
        if (originalDocument === undefined) delete globalThis.document;
        else Object.defineProperty(globalThis, "document", { configurable: true, value: originalDocument });
        console.log(JSON.stringify({ primary: writes.length, fallback: fallbackCalls }));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"primary": 1, "fallback": 1}
    print("frontend clipboard fallback and selection-preserving copy checks passed")


if __name__ == "__main__":
    main()
