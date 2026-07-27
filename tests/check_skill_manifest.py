from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.skill_manifest import (  # noqa: E402
    SkillManifestError,
    parse_skill_markdown,
)


def manifest(front_matter: str, body: str = "Use the declared workflow.") -> str:
    return f"---\n{front_matter.strip()}\n---\n{body}"


def expect_invalid(content: str, *, max_body_chars: int = 50_000) -> None:
    try:
        parse_skill_markdown(content, max_body_chars=max_body_chars)
    except SkillManifestError as exc:
        assert exc.code == "skill_invalid_manifest"
    else:
        raise AssertionError(f"manifest unexpectedly accepted: {content!r}")


def main() -> None:
    rich = manifest(
        """
name: notion-research
description: Research Notion and public sources.
homepage: https://example.test/skill
metadata:
  vendor:
    channel: stable
  knowflow:
    display_name: Notion 调研整理
    version: 1.2.0
    required_tools: [web_search, web_search, browser.open]
    required_mcp: [notion, notion, notion-server:v2]
    future_option: retained
"""
    )
    parsed = parse_skill_markdown(rich, max_body_chars=50_000)
    assert parsed.slug == "notion-research"
    assert parsed.display_name == "Notion 调研整理"
    assert parsed.description == "Research Notion and public sources."
    assert parsed.version == "1.2.0"
    assert parsed.required_tools == ("web_search", "browser.open")
    assert parsed.required_mcp == ("notion", "notion-server:v2")
    assert parsed.body == "Use the declared workflow."
    assert parsed.raw_metadata["homepage"] == "https://example.test/skill"
    assert parsed.raw_metadata["metadata"]["vendor"]["channel"] == "stable"
    assert parsed.raw_metadata["metadata"]["knowflow"]["future_option"] == "retained"

    minimal = manifest("name: stable-defaults\ndescription:  A useful Skill.  ")
    defaults = parse_skill_markdown(minimal, max_body_chars=50_000)
    assert defaults.display_name == "stable-defaults"
    assert defaults.version == "0.0.0"
    assert defaults.description == "A useful Skill."
    assert defaults.required_tools == ()
    assert defaults.required_mcp == ()
    assert defaults == parse_skill_markdown(minimal, max_body_chars=50_000)

    exact = minimal + "\r\n"
    expected_hash = hashlib.sha256(exact.encode("utf-8")).hexdigest()
    assert (
        parse_skill_markdown(exact, max_body_chars=50_000).content_hash
        == expected_hash
    )
    assert parsed.content_hash == hashlib.sha256(rich.encode("utf-8")).hexdigest()

    aliased = manifest(
        """
name: immutable-metadata
description: Metadata must remain stable.
metadata:
  shared: &shared
    channel: stable
    channels: [stable, beta]
  mirror: *shared
  knowflow:
    required_tools: [web_search]
"""
    )
    mutation_failures: list[str] = []

    top_level = parse_skill_markdown(aliased, max_body_chars=50_000)
    try:
        top_level.raw_metadata["name"] = "mutated"
    except TypeError:
        pass
    else:
        mutation_failures.append("top-level assignment")

    nested = parse_skill_markdown(aliased, max_body_chars=50_000)
    shared = nested.raw_metadata["metadata"]["shared"]
    mirror = nested.raw_metadata["metadata"]["mirror"]
    try:
        mirror["channel"] = "nightly"
    except TypeError:
        pass
    else:
        mutation_failures.append("nested mapping assignment")
    if shared["channel"] != "stable":
        mutation_failures.append("YAML alias mutation leaked")

    sequence = parse_skill_markdown(aliased, max_body_chars=50_000)
    channels = sequence.raw_metadata["metadata"]["shared"]["channels"]
    try:
        channels.append("nightly")
    except (AttributeError, TypeError):
        pass
    else:
        mutation_failures.append("nested sequence append")

    assert not mutation_failures, mutation_failures
    stable = parse_skill_markdown(aliased, max_body_chars=50_000)
    stable_again = parse_skill_markdown(aliased, max_body_chars=50_000)
    assert stable.content_hash == stable_again.content_hash
    assert stable.raw_metadata == stable_again.raw_metadata
    assert dict(stable.raw_metadata)["name"] == "immutable-metadata"
    serialized = json.dumps(
        stable.raw_metadata,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert json.loads(serialized)["metadata"]["shared"]["channels"] == [
        "stable",
        "beta",
    ]

    for invalid in (
        "",
        "name: no-front-matter\ndescription: bad",
        "---\nname: no-closing\ndescription: bad",
        manifest("description: missing name"),
        manifest("name: missing-description"),
        manifest("name: ''\ndescription: bad"),
        manifest("name: valid\ndescription: ''"),
        manifest("name: ../escape\ndescription: bad"),
        manifest("name: Invalid_Name\ndescription: bad"),
        manifest("name: valid\ndescription: [not, text]"),
        "---\n- not\n- a\n- mapping\n---\nBody",
        manifest("name: valid\ndescription: fine\nmetadata: []"),
        manifest("name: valid\ndescription: fine\nmetadata:\n  knowflow: []"),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            "  knowflow:\n    required_tools: web_search"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            "  knowflow:\n    required_mcp: [notion, ../escape]"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            "  knowflow:\n    required_tools: [safe, 'has space']"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            "  knowflow:\n    display_name: 42"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            "  knowflow:\n    version: [1, 2]"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            f"  knowflow:\n    display_name: {'x' * 121}"
        ),
        manifest(
            "name: valid\ndescription: fine\nmetadata:\n"
            f"  knowflow:\n    version: {'1' * 65}"
        ),
        manifest(
            "name: dangerous\ndescription: bad\n"
            "payload: !!python/object/apply:os.system ['echo unsafe']"
        ),
    ):
        expect_invalid(invalid)

    expect_invalid(manifest("name: bounded\ndescription: fine", "12345"), max_body_chars=4)
    bounded = parse_skill_markdown(
        manifest("name: bounded\ndescription: fine", "12345"),
        max_body_chars=5,
    )
    assert bounded.body == "12345"
    expect_invalid(
        manifest("name: boolean-limit\ndescription: fine", ""),
        max_body_chars=True,
    )

    oversized_front_matter = (
        "---\nname: bounded\ndescription: fine\nextra: "
        + ("x" * 70_000)
        + "\n---\nBody"
    )
    expect_invalid(oversized_front_matter)

    print("skill manifest checks passed")


if __name__ == "__main__":
    main()
