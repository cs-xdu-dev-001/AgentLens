from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    source = read("frontend/refinement.css")
    main_js = read("frontend/react/src/main.jsx")
    sync = read("frontend/scripts/sync-assets.mjs")
    assert '["refinement.css", "react/src/refinement.css"]' in sync
    assert 'import "./refinement.css";' in main_js
    assert main_js.index('import "./styles.css";') < main_js.index(
        'import "./refinement.css";'
    )
    for token in (
        "--kf-type-page",
        "--kf-type-title",
        "--kf-type-body",
        "--kf-radius-control",
        "--kf-space-4",
        "/* KnowFlow refinement: foundation */",
    ):
        assert token in source, f"missing refinement token: {token}"
    print("frontend refinement system is wired")


if __name__ == "__main__":
    main()
