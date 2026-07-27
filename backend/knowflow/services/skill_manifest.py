from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

import yaml


_MAX_FRONT_MATTER_CHARS = 65_536
_MAX_FRONT_MATTER_BYTES = 65_536
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DEPENDENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


@dataclass(frozen=True)
class SkillManifest:
    slug: str
    display_name: str
    description: str
    version: str
    required_tools: tuple[str, ...]
    required_mcp: tuple[str, ...]
    body: str
    raw_metadata: dict[str, Any]
    content_hash: str


class SkillManifestError(ValueError):
    code = "skill_invalid_manifest"


def _front_matter_and_body(content: str) -> tuple[str, str]:
    if content.startswith("---\r\n"):
        metadata_start = 5
    elif content.startswith("---\n"):
        metadata_start = 4
    else:
        raise SkillManifestError("missing front matter")

    cursor = metadata_start
    while cursor - metadata_start <= _MAX_FRONT_MATTER_CHARS:
        newline = content.find("\n", cursor)
        line_end = len(content) if newline == -1 else newline
        if line_end - metadata_start > _MAX_FRONT_MATTER_CHARS:
            raise SkillManifestError("front matter too large")
        line = content[cursor:line_end]
        if line.endswith("\r"):
            line = line[:-1]
        if line == "---":
            front_matter = content[metadata_start:cursor]
            if len(front_matter.encode("utf-8")) > _MAX_FRONT_MATTER_BYTES:
                raise SkillManifestError("front matter too large")
            body_start = len(content) if newline == -1 else newline + 1
            return front_matter, content[body_start:].strip()
        if newline == -1:
            break
        cursor = newline + 1

    raise SkillManifestError("unterminated front matter")


def _optional_text(
    values: dict[str, Any],
    key: str,
    *,
    default: str,
    max_chars: int,
) -> str:
    if key not in values:
        return default
    value = values[key]
    if not isinstance(value, str):
        raise SkillManifestError(f"invalid {key}")
    value = value.strip()
    if not value or len(value) > max_chars:
        raise SkillManifestError(f"invalid {key}")
    return value


def _dependencies(values: dict[str, Any], key: str) -> tuple[str, ...]:
    if key not in values:
        return ()
    value = values[key]
    if not isinstance(value, list):
        raise SkillManifestError(f"invalid {key}")

    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not _DEPENDENCY_PATTERN.fullmatch(item):
            raise SkillManifestError(f"invalid {key}")
        if item not in seen:
            result.append(item)
            seen.add(item)
    return tuple(result)


def parse_skill_markdown(
    content: str,
    *,
    max_body_chars: int,
) -> SkillManifest:
    if not isinstance(content, str) or type(max_body_chars) is not int:
        raise SkillManifestError("invalid manifest input")
    if max_body_chars < 0:
        raise SkillManifestError("invalid body limit")

    front_matter, body = _front_matter_and_body(content)
    try:
        loaded = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise SkillManifestError("invalid YAML front matter") from exc
    if not isinstance(loaded, dict):
        raise SkillManifestError("front matter must be a mapping")

    slug = loaded.get("name")
    if not isinstance(slug, str) or not _SLUG_PATTERN.fullmatch(slug):
        raise SkillManifestError("invalid name")
    description = loaded.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillManifestError("invalid description")

    metadata = loaded.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SkillManifestError("invalid metadata")
    knowflow = metadata.get("knowflow", {})
    if not isinstance(knowflow, dict):
        raise SkillManifestError("invalid knowflow metadata")

    if len(body) > max_body_chars:
        raise SkillManifestError("body too large")

    return SkillManifest(
        slug=slug,
        display_name=_optional_text(
            knowflow,
            "display_name",
            default=slug,
            max_chars=120,
        ),
        description=description.strip(),
        version=_optional_text(
            knowflow,
            "version",
            default="0.0.0",
            max_chars=64,
        ),
        required_tools=_dependencies(knowflow, "required_tools"),
        required_mcp=_dependencies(knowflow, "required_mcp"),
        body=body,
        raw_metadata=loaded,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
