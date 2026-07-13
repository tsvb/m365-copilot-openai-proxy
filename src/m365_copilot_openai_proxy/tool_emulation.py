from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .models import ContentPart, OpenAIMessage, ToolCall, ToolSpec


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


def flatten_message_content(content: str | list[ContentPart] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "".join(part.text or "" for part in content if part.type == "text")


def filter_tools(
    tools: list[ToolSpec] | None,
    allowed_names: frozenset[str],
) -> list[ToolSpec]:
    if not tools:
        return []
    return [tool for tool in tools if tool.function.name.lower() in allowed_names]


def _tool_arg_names(tool: ToolSpec) -> list[str]:
    params = tool.function.parameters or {}
    props = params.get("properties") if isinstance(params, dict) else None
    return list(props.keys()) if isinstance(props, dict) else []


def _describe_action(tool: ToolSpec) -> str:
    name = tool.function.name
    args = ", ".join(_tool_arg_names(tool))
    description = (tool.function.description or "").strip().splitlines()
    summary = description[0] if description else ""
    line = f"- {name}({args})"
    return f"{line}: {summary}" if summary else line


def _format_args(arguments: str) -> str:
    try:
        parsed = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return arguments
    if not isinstance(parsed, dict):
        return arguments
    return ", ".join(f"{key}={value}" for key, value in parsed.items())


def _action_label(tool_call: ToolCall) -> str:
    return f"{tool_call.function.name}({_format_args(tool_call.function.arguments)})"


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


_PROMPT_HEADER = (
    "You are analyzing a code repository to answer the user's request. To inspect the "
    "repository you can request information by emitting a single action. The system runs "
    "the action and returns the result to you.\n"
)

_PROMPT_INSTRUCTIONS = (
    'To request information, reply with ONLY a JSON object, for example:\n'
    '{"action": "read", "args": {"filePath": "src/app.py"}}\n'
    "Do not include any other text when you request information.\n"
    "When you have enough information to answer, reply normally with your answer as plain "
    "prose. Do not wrap your final answer in JSON."
)


def render_action_prompt(
    tools: list[ToolSpec],
    messages: list[OpenAIMessage],
    *,
    max_observation_chars: int,
    reask: str | None = None,
) -> str:
    call_names: dict[str, str] = {}
    system_lines: list[str] = []
    transcript: list[str] = []

    for message in messages:
        if message.role in {"system", "developer"}:
            text = flatten_message_content(message.content).strip()
            if text:
                system_lines.append(text)
            continue
        if message.role == "user":
            text = flatten_message_content(message.content).strip()
            if text:
                transcript.append(f"User: {text}")
            continue
        if message.role == "assistant":
            if message.tool_calls:
                for call in message.tool_calls:
                    call_names[call.id] = _action_label(call)
                    transcript.append(f"Assistant requested: {_action_label(call)}")
            else:
                text = flatten_message_content(message.content).strip()
                if text:
                    transcript.append(f"Assistant: {text}")
            continue
        if message.role == "tool":
            label = call_names.get(message.tool_call_id or "", "action")
            observation = _cap(flatten_message_content(message.content), max_observation_chars)
            transcript.append(f"Observation for {label}:\n{observation}")

    actions = "\n".join(_describe_action(tool) for tool in tools)

    sections = [_PROMPT_HEADER, f"Available actions:\n{actions}", _PROMPT_INSTRUCTIONS]
    if system_lines:
        sections.append("System instructions:\n" + "\n".join(system_lines))
    if transcript:
        sections.append("Conversation:\n" + "\n".join(transcript))
    if reask:
        sections.append(reask)
    sections.append("Respond now.")
    return "\n\n".join(sections)
