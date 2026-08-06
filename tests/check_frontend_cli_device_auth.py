from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "react" / "src"


def main() -> None:
    app = (SRC / "App.jsx").read_text(encoding="utf-8")
    page = (SRC / "components" / "CliDeviceAuthPage.jsx").read_text(encoding="utf-8")
    client = (SRC / "api" / "client.js").read_text(encoding="utf-8")
    source_styles = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert '"cli-auth"' in app
    assert "<CliDeviceAuthPage" in app
    assert "允许KnowFlow CLI登录？" in page
    assert "decideCliDevice" in page
    assert "useEffect" not in page, "authorization must not happen on page load"
    assert "/api/auth/cli/device/decision" in client
    assert ".cli-device-page" in source_styles
    assert "sessionToken" not in page

    print("frontend cli device auth checks passed")


if __name__ == "__main__":
    main()
