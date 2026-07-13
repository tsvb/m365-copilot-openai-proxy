from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolAction:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FinalAnswer:
    text: str


@dataclass(frozen=True)
class UnavailableAction:
    name: str


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = _strip_fences(text)
    if not candidate.startswith("{"):
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_copilot_turn(
    text: str,
    allowed_names: frozenset[str],
) -> ToolAction | FinalAnswer | UnavailableAction:
    obj = extract_json_object(text)
    if obj is not None and isinstance(obj.get("action"), str):
        name = obj["action"].strip()
        args = obj.get("args")
        if not isinstance(args, dict):
            args = {}
        if name == "final":
            return FinalAnswer(text=str(args.get("text", "")).strip() or text.strip())
        if name in allowed_names:
            return ToolAction(name=name, args=args)
        return UnavailableAction(name=name)
    return FinalAnswer(text=text.strip())
