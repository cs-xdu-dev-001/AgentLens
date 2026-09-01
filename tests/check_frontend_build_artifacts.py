import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_active_dist_assets(dist: Path) -> str:
    index = (dist / "index.html").read_text(encoding="utf-8")
    parts = [index]
    for asset in re.findall(r'["\'](/assets/[^"\']+)["\']', index):
        asset_path = dist / asset.lstrip("/")
        if asset_path.exists() and asset_path.is_file():
            parts.append(asset_path.read_text(encoding="utf-8"))

    return "\n".join(parts)


def read_react_shell() -> str:
    files = [
        "frontend/react/src/App.jsx",
        "frontend/react/src/components/AuthScreen.jsx",
        "frontend/react/src/components/Sidebar.jsx",
        "frontend/react/src/components/ChatPage.jsx",
        "frontend/react/src/components/KnowledgePage.jsx",
        "frontend/react/src/components/SettingsPage.jsx",
        "frontend/react/src/components/Toast.jsx",
        "frontend/react/src/components/KnowFlowController.jsx",
    ]
    return "\n".join(read(path) for path in files)


def main() -> None:
    react_css = read("frontend/react/src/styles.css")
    react_shell = read_react_shell()
    thinking_orb = read("frontend/react/src/components/AgentThinkingOrb.jsx")
    vite_config = read("frontend/vite.config.js")
    jsx_runtime = read("frontend/react/src/vendor/reactJsxRuntimeGlobal.js")
    gitignore = read(".gitignore")
    package_json = read("frontend/package.json")
    sync_assets = read("frontend/scripts/sync-assets.mjs")
    app_py = read("backend/knowflow/app.py")
    controller_js = "\n".join([read("frontend/react/src/controller/knowflowController.js"), read("frontend/react/src/controller/chatFlow.js")])

    assert "姝ｅ湪缁勭粐鍥炵瓟" not in react_css
    assert "streaming:empty" not in react_css
    assert ".agent-thinking-orb" in react_css
    assert ".thinking-indicator" not in react_css
    assert 'from "thinking-orbs"' in thinking_orb
    assert 'from "@vitejs/plugin-react"' in vite_config
    assert "plugins: [react()]" in vite_config
    assert 'minify: "esbuild"' in vite_config
    assert '"markdown-vendor": ["markdown-it"]' in vite_config
    assert "function jsxClassicPlugin" not in vite_config
    assert "transformAsync" not in vite_config
    assert "esbuild: false" not in vite_config
    assert 'find: /^react\\/jsx-runtime$/' in vite_config
    assert 'find: /^react\\/jsx-dev-runtime$/' in vite_config
    assert 'include: ["parse-diff"]' in vite_config
    assert 'React.createElement' in jsx_runtime
    assert 'export const jsx = createElement' in jsx_runtime
    assert 'return "solving"' in thinking_orb
    assert 'state={stable.state}' in thinking_orb
    assert 'Math.max(0, 2000 -' in thinking_orb
    assert 'aria-atomic={"true"}' in thinking_orb
    assert 'size={20}' in thinking_orb
    assert '"thinking-orbs": "0.2.0"' in package_json
    assert '"@vitejs/plugin-react": "4.7.0"' in package_json
    assert '"@babel/core"' not in package_json
    assert ".message-row.thinking-row .message-actions" in react_css
    assert 'appendMessage("assistant", "", { thinking: true, streaming: true })' in controller_js
    assert "setMessageThinking" in controller_js
    assert "renderMarkdown" in read("frontend/react/src/components/ChatMessages.jsx")
    assert "legacyTemplate" not in react_shell
    assert "dangerouslySetInnerHTML" not in react_shell
    assert "legacyApp.js" not in react_shell
    assert "LegacyControllerBridge" not in react_shell
    assert "auth-screen" in react_shell
    assert "app-shell" in react_shell
    assert "frontend/node_modules/" in gitignore
    assert "frontend/vite-dev*.log" in gitignore
    assert "frontend/codex-polish-*.png" in gitignore
    assert '"sync:assets": "node scripts/sync-assets.mjs"' in package_json
    assert '"sync:styles": "npm run sync:assets"' in package_json
    assert '"prebuild": "npm run sync:assets"' in package_json
    assert '"predev": "npm run sync:assets"' in package_json
    assert '["styles.css", "react/src/styles.css"]' in sync_assets
    assert 'app.mount("/vendor"' in app_py
    assert '"/vendor"' in app_py
    assert "legacyApp.js" not in sync_assets
    assert '["app.js", "react/public/assets/legacyApp.js"]' not in sync_assets
    assert "copyFileSync(source, target)" in sync_assets
    assert not (ROOT / "frontend" / "app.js").exists()
    assert not (ROOT / "frontend" / "react" / "public" / "assets" / "legacyApp.js").exists()

    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        dist = ROOT / "dist"
    if dist.exists():
        assert not (dist / "assets" / "legacyApp.js").exists()
        assert (dist / "vendor" / "react.production.min.js").exists()
        assert (dist / "vendor" / "react-dom.production.min.js").exists()
        main_scripts = list((dist / "assets").glob("index-*.js"))
        markdown_chunks = list((dist / "assets").glob("markdown-vendor-*.js"))
        assert main_scripts, "missing production entry bundle"
        assert markdown_chunks, "missing cacheable Markdown vendor chunk"
        assert max(asset.stat().st_size for asset in main_scripts) < 500_000, (
            "production entry bundle exceeded the 500 kB budget"
        )
        dist_text = read_active_dist_assets(dist)
        assert "姝ｅ湪缁勭粐鍥炵瓟" not in dist_text
        assert "streaming:empty" not in dist_text
        assert "legacyApp.js" not in dist_text
        assert "agent-thinking-orb" in dist_text
        assert "thinking-row" in dist_text
        assert "auth-screen" in dist_text
        assert "app-shell" in dist_text


if __name__ == "__main__":
    main()
