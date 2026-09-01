from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    component = "frontend/react/src/components/ChatMessages.jsx"
    styles = "frontend/refinement.css"
    layout_styles = "frontend/styles.css"

    require(component, "followOutputRef", "pinned-output state")
    require(component, "isChatViewportPinned", "viewport distance check")
    require(component, "onScroll={handleMessagesScroll}", "reader-owned scrolling")
    require(component, "shouldFollowChatUpdate", "stream update scroll guard")
    require(component, 'from "react-virtuoso"', "virtualized message list")
    require(component, "<Virtuoso", "virtualized message renderer")
    require(component, "computeItemKey={messageItemKey}", "stable message keys")
    require(component, "atBottomStateChange={handleVirtuosoAtBottom}", "virtualized bottom state")
    require(component, 'index: "LAST"', "virtualized latest-message jump")
    require(component, "data-message-count", "message count telemetry")
    require(component, "message-list-footer", "virtualized composer-safe bottom gutter")
    require(component, "messages-virtualized", "virtualized transcript layout class")
    if "{messages.map((message) => (" in read(component):
        raise AssertionError("unbounded message DOM map remains in ChatMessages")
    require("frontend/package.json", '"react-virtuoso": "4.18.12"', "pinned virtualization dependency")
    require(component, "查看最新Agent输出", "new output accessible label")
    require(component, "prefers-reduced-motion: reduce", "reduced-motion scroll behavior")
    require(styles, ".chat-jump-to-latest", "jump-to-latest control")
    require(styles, ".chat-jump-to-latest:focus-visible", "visible keyboard focus")
    require(layout_styles, ".messages.messages-virtualized", "virtualized transcript gutter layout")
    require(layout_styles, "overflow-x: hidden !important", "virtualized transcript horizontal clipping guard")

    script = r'''import {
  CHAT_SCROLL_PIN_THRESHOLD,
  isChatViewportPinned,
  shouldFollowChatUpdate,
} from "./frontend/react/src/components/chatScrollState.js";

const viewport = (remaining) => ({
  scrollHeight: 1000,
  clientHeight: 400,
  scrollTop: 600 - remaining,
});
if (!isChatViewportPinned(viewport(0))) throw new Error("bottom is not pinned");
if (!isChatViewportPinned(viewport(CHAT_SCROLL_PIN_THRESHOLD))) {
  throw new Error("threshold boundary is not pinned");
}
if (isChatViewportPinned(viewport(CHAT_SCROLL_PIN_THRESHOLD + 1))) {
  throw new Error("reader scroll position was treated as pinned");
}
if (shouldFollowChatUpdate({pinned: false})) {
  throw new Error("stream update stole the reader viewport");
}
if (!shouldFollowChatUpdate({pinned: false, force: true})) {
  throw new Error("explicit jump did not restore following");
}
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)

    print("chat output follows only while the reader remains pinned")


if __name__ == "__main__":
    main()
