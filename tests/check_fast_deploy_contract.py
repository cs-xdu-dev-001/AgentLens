from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "deploy" / "fast-deploy.sh").read_text(
        encoding="utf-8"
    )

    assert "*.sh text eol=lf" in attributes
    assert "runs-on: ubuntu-latest" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "DEPLOYMENT-MANIFEST.json" in workflow
    assert "bundle-contents.txt" in workflow
    assert "backend/knowflow" in workflow and "frontend/dist/index.html" in workflow
    assert "git reset" not in script and "git clean" not in script
    assert "git status --porcelain" in script
    assert "full 40-character commit SHA" in script
    assert "rev-parse --verify --end-of-options" in script
    assert "actions/runs" in script and 'conclusion") != "success"' in script
    assert "requirements.sha256" in script
    assert "package-lock.sha256" in script
    assert "frontend.sha256" in script
    assert "tests/check_" not in script
    assert script.index('conclusion") != "success"') < script.index("git checkout")
    assert script.index("systemctl restart") < script.index("health check failed")

    print("Linux deployment bundle and CI-gated fast deploy contract are present")


if __name__ == "__main__":
    main()
