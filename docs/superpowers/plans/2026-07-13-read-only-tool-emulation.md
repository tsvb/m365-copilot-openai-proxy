# Read-Only Tool-Call Emulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let OpenCode drive read-only file interaction through the proxy by emulating OpenAI tool-calling on top of Microsoft 365 Copilot.

**Architecture:** The proxy stays a stateless translator. When a `/v1/chat/completions` request carries a `tools` array, a new emulation path renders the read-only tools plus conversation into a reframed prompt, sends one buffered Copilot turn, parses the reply into either a tool action or a prose final answer, and returns it as an OpenAI `tool_calls` response or a streamed final. OpenCode executes the reads itself and loops.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, pytest. No new dependencies.

## Global Constraints

- Python `>=3.11` (per `pyproject.toml`); no new runtime dependencies.
- All Pydantic models use `ConfigDict(extra="ignore")`, matching existing `models.py`.
- `substrate_client.py` MUST NOT be modified — it stays tool-agnostic (sends text, returns text).
- Read-only tools only this iteration: default allowlist `read,glob,grep,list,ls`. No `write`/`edit`/`bash`.
- One tool call per turn (no parallel tool calls).
- Run tests with: `uv run --extra dev pytest <path> -v` from the repo root (`m365-copilot-openai-proxy/`).
- Commit after each task with the message shown in that task's final step.

---

## File Structure

- Create: `src/m365_copilot_openai_proxy/tool_emulation.py` — action types, JSON extraction, turn parsing, prompt rendering, and the re-ask orchestration loop. All logic except the network call.
- Create: `tests/test_tool_emulation.py` — pure unit tests for the module above.
- Modify: `src/m365_copilot_openai_proxy/models.py` — add tool request/message fields and tool-call types.
- Modify: `src/m365_copilot_openai_proxy/config.py` — add allowlist + caps + `read_only_tool_names`.
- Modify: `src/m365_copilot_openai_proxy/app.py` — branch `/v1/chat/completions` into the emulation path (streaming + non-streaming).
- Modify: `tests/test_app.py` — integration tests for the emulation endpoint.
- Modify: `README.md` — correct the OpenCode base URL and document read-only tool support.

---

## Task 1: Tool types and request/message fields in models.py

**Files:**
- Modify: `src/m365_copilot_openai_proxy/models.py`
- Test: `tests/test_tool_emulation.py`

**Interfaces:**
- Produces: `ToolSpec` (`.type: str`, `.function: FunctionSpec` where `FunctionSpec` has `.name: str`, `.description: str | None`, `.parameters: dict | None`), `ToolCall` (`.id: str`, `.type: str`, `.function: ToolCallFunction` with `.name: str`, `.arguments: str`), and extended `OpenAIMessage` (`.content: str | list[ContentPart] | None`, `.tool_calls: list[ToolCall] | None`, `.tool_call_id: str | None`) and `OpenAIChatRequest.tools: list[ToolSpec] | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tool_emulation.py`:

```python
from __future__ import annotations

from m365_copilot_openai_proxy.models import OpenAIChatRequest


def test_chat_request_parses_tools_and_tool_messages() -> None:
    request = OpenAIChatRequest.model_validate(
        {
            "model": "m365-copilot",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
                    },
                }
            ],
            "messages": [
                {"role": "user", "content": "summarize app.py"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {"id": "call_1", "type": "function", "function": {"name": "read", "arguments": "{\"filePath\": \"app.py\"}"}}
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "print('hi')"},
            ],
        }
    )

    assert request.tools[0].function.name == "read"
    assert request.messages[1].tool_calls[0].id == "call_1"
    assert request.messages[1].tool_calls[0].function.arguments == '{"filePath": "app.py"}'
    assert request.messages[2].tool_call_id == "call_1"
    assert request.messages[1].content is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py::test_chat_request_parses_tools_and_tool_messages -v`
Expected: FAIL (validation error — `content` cannot be `None`, and `tools`/`tool_calls`/`tool_call_id` are dropped).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/models.py`, add these classes near `OpenAIMessage` and update `OpenAIMessage`/`OpenAIChatRequest`:

```python
class FunctionSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str = "function"
    function: FunctionSpec


class ToolCallFunction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    arguments: str = ""


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str = "function"
    function: ToolCallFunction
```

Change `OpenAIMessage` to:

```python
class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
```

Change `OpenAIChatRequest` to add these two fields:

```python
class OpenAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[OpenAIMessage]
    stream: bool = False
    temperature: float | None = None
    user: str | None = None
    tools: list[ToolSpec] | None = None
    tool_choice: Any | None = None
```

(`Any` is already imported in `models.py`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py::test_chat_request_parses_tools_and_tool_messages -v`
Expected: PASS

- [ ] **Step 5: Run the full suite to confirm no regression**

Run: `uv run --extra dev pytest -v`
Expected: PASS (existing tests still green — `content` is now optional but `flatten_content(None)` already returns `""`).

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/models.py tests/test_tool_emulation.py
git commit -m "feat: parse OpenAI tools and tool messages in chat request"
```

---

## Task 2: Config knobs for the allowlist and caps

**Files:**
- Modify: `src/m365_copilot_openai_proxy/config.py`
- Test: `tests/test_tool_emulation.py`

**Interfaces:**
- Produces: `Settings.read_only_tools: str`, `Settings.max_observation_chars: int`, `Settings.max_reasks: int`, and property `Settings.read_only_tool_names -> frozenset[str]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tool_emulation.py`:

```python
from m365_copilot_openai_proxy.config import Settings


def test_settings_expose_read_only_tool_names() -> None:
    settings = Settings(M365_ACCESS_TOKEN="x", M365_READ_ONLY_TOOLS="read, glob ,GREP")
    assert settings.read_only_tool_names == frozenset({"read", "glob", "grep"})
    assert settings.max_reasks == 2
    assert settings.max_observation_chars == 12000


def test_settings_default_read_only_tools() -> None:
    settings = Settings(M365_ACCESS_TOKEN="x")
    assert "read" in settings.read_only_tool_names
    assert "glob" in settings.read_only_tool_names
    assert "grep" in settings.read_only_tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py::test_settings_expose_read_only_tool_names -v`
Expected: FAIL (`read_only_tool_names` does not exist).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/config.py`, add fields and property to `Settings`:

```python
    read_only_tools: str = Field(default="read,glob,grep,list,ls", alias="M365_READ_ONLY_TOOLS")
    max_observation_chars: int = Field(default=12000, alias="M365_MAX_OBSERVATION_CHARS")
    max_reasks: int = Field(default=2, alias="M365_MAX_REASKS")

    @property
    def read_only_tool_names(self) -> frozenset[str]:
        return frozenset(
            name.strip().lower() for name in self.read_only_tools.split(",") if name.strip()
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k settings -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/m365_copilot_openai_proxy/config.py tests/test_tool_emulation.py
git commit -m "feat: add read-only tool allowlist and emulation caps to settings"
```

---

## Task 3: Action types, JSON extraction, and turn parsing

**Files:**
- Create: `src/m365_copilot_openai_proxy/tool_emulation.py`
- Test: `tests/test_tool_emulation.py`

**Interfaces:**
- Produces: dataclasses `ToolAction(name: str, args: dict)`, `FinalAnswer(text: str)`, `UnavailableAction(name: str)`; `extract_json_object(text: str) -> dict | None`; `parse_copilot_turn(text: str, allowed_names: frozenset[str]) -> ToolAction | FinalAnswer | UnavailableAction`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_emulation.py`:

```python
from m365_copilot_openai_proxy.tool_emulation import (
    FinalAnswer,
    ToolAction,
    UnavailableAction,
    extract_json_object,
    parse_copilot_turn,
)

ALLOWED = frozenset({"read", "glob", "grep"})


def test_parse_clean_action() -> None:
    result = parse_copilot_turn('{"action": "read", "args": {"filePath": "a.py"}}', ALLOWED)
    assert result == ToolAction(name="read", args={"filePath": "a.py"})


def test_parse_fenced_action() -> None:
    text = '```json\n{"action": "grep", "args": {"pattern": "def"}}\n```'
    result = parse_copilot_turn(text, ALLOWED)
    assert result == ToolAction(name="grep", args={"pattern": "def"})


def test_parse_prose_final() -> None:
    result = parse_copilot_turn("The file defines two functions.", ALLOWED)
    assert result == FinalAnswer(text="The file defines two functions.")


def test_parse_prose_containing_json_block_is_final() -> None:
    text = "Here is the config you asked about:\n```json\n{\"a\": 1}\n```\nThat is all."
    result = parse_copilot_turn(text, ALLOWED)
    assert isinstance(result, FinalAnswer)


def test_parse_unknown_tool_is_unavailable() -> None:
    result = parse_copilot_turn('{"action": "write", "args": {"filePath": "a.py"}}', ALLOWED)
    assert result == UnavailableAction(name="write")


def test_parse_explicit_final_action() -> None:
    result = parse_copilot_turn('{"action": "final", "args": {"text": "done"}}', ALLOWED)
    assert result == FinalAnswer(text="done")


def test_parse_malformed_json_is_final() -> None:
    result = parse_copilot_turn('{"action": "read", "args":', ALLOWED)
    assert isinstance(result, FinalAnswer)


def test_parse_empty_is_final_empty() -> None:
    result = parse_copilot_turn("   ", ALLOWED)
    assert result == FinalAnswer(text="")


def test_extract_json_object_ignores_non_object() -> None:
    assert extract_json_object("[1, 2, 3]") is None
    assert extract_json_object("just prose") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k parse -v`
Expected: FAIL (`tool_emulation` module does not exist).

- [ ] **Step 3: Write minimal implementation**

Create `src/m365_copilot_openai_proxy/tool_emulation.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k "parse or extract_json" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/m365_copilot_openai_proxy/tool_emulation.py tests/test_tool_emulation.py
git commit -m "feat: parse Copilot turns into tool actions or final answers"
```

---

## Task 4: Render the action prompt (actions, transcript, observations, re-ask)

**Files:**
- Modify: `src/m365_copilot_openai_proxy/tool_emulation.py`
- Test: `tests/test_tool_emulation.py`

**Interfaces:**
- Consumes: `ToolSpec`, `OpenAIMessage` from `models.py`.
- Produces: `filter_tools(tools: list[ToolSpec] | None, allowed_names: frozenset[str]) -> list[ToolSpec]`; `render_action_prompt(tools: list[ToolSpec], messages: list[OpenAIMessage], *, max_observation_chars: int, reask: str | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_emulation.py`:

```python
from m365_copilot_openai_proxy.models import OpenAIChatRequest
from m365_copilot_openai_proxy.tool_emulation import filter_tools, render_action_prompt


def _request(payload: dict) -> OpenAIChatRequest:
    return OpenAIChatRequest.model_validate(payload)


READ_TOOL = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read a file from disk",
        "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
    },
}
WRITE_TOOL = {
    "type": "function",
    "function": {"name": "write", "description": "Write a file", "parameters": {}},
}


def test_filter_tools_keeps_only_allowlisted() -> None:
    request = _request({"model": "m", "tools": [READ_TOOL, WRITE_TOOL], "messages": [{"role": "user", "content": "hi"}]})
    kept = filter_tools(request.tools, frozenset({"read"}))
    assert [t.function.name for t in kept] == ["read"]


def test_render_prompt_lists_actions_and_omits_filtered() -> None:
    request = _request({"model": "m", "tools": [READ_TOOL], "messages": [{"role": "user", "content": "summarize app.py"}]})
    prompt = render_action_prompt(filter_tools(request.tools, frozenset({"read"})), request.messages, max_observation_chars=100)
    assert "read(filePath)" in prompt
    assert "Read a file from disk" in prompt
    assert "write" not in prompt
    assert "User: summarize app.py" in prompt
    assert '{"action":' in prompt  # instruction example present


def test_render_prompt_folds_tool_result_as_observation() -> None:
    request = _request(
        {
            "model": "m",
            "tools": [READ_TOOL],
            "messages": [
                {"role": "user", "content": "summarize app.py"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{\"filePath\": \"app.py\"}"}}],
                },
                {"role": "tool", "tool_call_id": "c1", "content": "print('hi')"},
            ],
        }
    )
    prompt = render_action_prompt(filter_tools(request.tools, frozenset({"read"})), request.messages, max_observation_chars=100)
    assert "read(filePath=app.py)" in prompt
    assert "print('hi')" in prompt
    assert "Observation" in prompt


def test_render_prompt_caps_large_observation() -> None:
    big = "x" * 500
    request = _request(
        {
            "model": "m",
            "tools": [READ_TOOL],
            "messages": [
                {"role": "user", "content": "read it"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": big},
            ],
        }
    )
    prompt = render_action_prompt(filter_tools(request.tools, frozenset({"read"})), request.messages, max_observation_chars=100)
    assert "x" * 100 in prompt
    assert "x" * 200 not in prompt
    assert "truncated" in prompt


def test_render_prompt_includes_reask_note() -> None:
    request = _request({"model": "m", "tools": [READ_TOOL], "messages": [{"role": "user", "content": "hi"}]})
    prompt = render_action_prompt(filter_tools(request.tools, frozenset({"read"})), request.messages, max_observation_chars=100, reask="TRY AGAIN NOTE")
    assert "TRY AGAIN NOTE" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k render -v`
Expected: FAIL (`render_action_prompt`/`filter_tools` not defined).

- [ ] **Step 3: Write minimal implementation**

Add to `src/m365_copilot_openai_proxy/tool_emulation.py` (imports at top, functions below):

```python
from .models import ContentPart, OpenAIMessage, ToolCall, ToolSpec
```

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k render -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/m365_copilot_openai_proxy/tool_emulation.py tests/test_tool_emulation.py
git commit -m "feat: render reframed action prompt with observations"
```

---

## Task 5: Orchestration loop with re-ask, dedupe, and fallback

**Files:**
- Modify: `src/m365_copilot_openai_proxy/tool_emulation.py`
- Test: `tests/test_tool_emulation.py`

**Interfaces:**
- Consumes: a client object exposing `async chat(prompt: str, additional_context: list[str], session=None) -> str`.
- Produces: `async run_emulation_turn(client, tools, messages, allowed_names, *, max_reasks: int, max_observation_chars: int) -> ToolAction | FinalAnswer`. Never returns `UnavailableAction`; unavailable/duplicate/garbage all resolve to a re-ask and then a `FinalAnswer`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tool_emulation.py`:

```python
import asyncio

from m365_copilot_openai_proxy.tool_emulation import run_emulation_turn


class ScriptedClient:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    async def chat(self, prompt: str, additional_context: list[str], session=None) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _msgs(user: str):
    return [OpenAIMessage.model_validate({"role": "user", "content": user})]


def test_run_returns_tool_action() -> None:
    client = ScriptedClient(['{"action": "read", "args": {"filePath": "a.py"}}'])
    tools = _request({"model": "m", "tools": [READ_TOOL], "messages": [{"role": "user", "content": "x"}]}).tools
    result = asyncio.run(
        run_emulation_turn(client, filter_tools(tools, frozenset({"read"})), _msgs("summarize a.py"), frozenset({"read"}), max_reasks=2, max_observation_chars=100)
    )
    assert result == ToolAction(name="read", args={"filePath": "a.py"})


def test_run_returns_final_answer() -> None:
    client = ScriptedClient(["It defines a class."])
    result = asyncio.run(
        run_emulation_turn(client, [], _msgs("what is in a.py"), frozenset({"read"}), max_reasks=2, max_observation_chars=100)
    )
    assert result == FinalAnswer(text="It defines a class.")


def test_run_reasks_on_unavailable_then_finalizes() -> None:
    client = ScriptedClient(
        ['{"action": "write", "args": {}}', '{"action": "bash", "args": {}}', '{"action": "bash", "args": {}}']
    )
    result = asyncio.run(
        run_emulation_turn(client, [], _msgs("do it"), frozenset({"read"}), max_reasks=2, max_observation_chars=100)
    )
    assert isinstance(result, FinalAnswer)
    assert len(client.prompts) == 3  # initial + 2 re-asks
    assert "not available" in client.prompts[1]


def test_run_reasks_on_garbage_then_takes_prose() -> None:
    client = ScriptedClient(["The answer is 42."])
    result = asyncio.run(
        run_emulation_turn(client, [], _msgs("q"), frozenset({"read"}), max_reasks=2, max_observation_chars=100)
    )
    assert result == FinalAnswer(text="The answer is 42.")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k run_ -v`
Expected: FAIL (`run_emulation_turn` not defined).

- [ ] **Step 3: Write minimal implementation**

Add to `src/m365_copilot_openai_proxy/tool_emulation.py`:

```python
_REASK_STRICT = (
    "Note: your previous reply could not be understood. Reply with ONLY a single JSON "
    "action object, or your final answer as plain prose."
)
_REASK_DUPLICATE = (
    "Note: you already requested that information (see the observation above). Continue "
    "with a different action or give your final answer as plain prose."
)


def _reask_unavailable(name: str, allowed_names: frozenset[str]) -> str:
    listed = ", ".join(sorted(allowed_names))
    return (
        f'Note: the action "{name}" is not available. Use only these actions: {listed}. '
        "Or give your final answer as plain prose."
    )


def _prior_action_keys(messages: list[OpenAIMessage]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            for call in message.tool_calls:
                try:
                    parsed = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    parsed = {}
                keys.add((call.function.name, json.dumps(parsed, sort_keys=True)))
    return keys


def _action_key(action: ToolAction) -> tuple[str, str]:
    return (action.name, json.dumps(action.args, sort_keys=True))


async def run_emulation_turn(
    client,
    tools: list[ToolSpec],
    messages: list[OpenAIMessage],
    allowed_names: frozenset[str],
    *,
    max_reasks: int,
    max_observation_chars: int,
) -> ToolAction | FinalAnswer:
    prior_keys = _prior_action_keys(messages)
    reask: str | None = None
    last_text = ""

    for _ in range(max_reasks + 1):
        prompt = render_action_prompt(
            tools, messages, max_observation_chars=max_observation_chars, reask=reask
        )
        last_text = await client.chat(prompt, [])
        result = parse_copilot_turn(last_text, allowed_names)

        if isinstance(result, FinalAnswer):
            return result
        if isinstance(result, UnavailableAction):
            reask = _reask_unavailable(result.name, allowed_names)
            continue
        if _action_key(result) in prior_keys:
            reask = _REASK_DUPLICATE
            continue
        return result

    return FinalAnswer(text=last_text.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -k run_ -v`
Expected: PASS

- [ ] **Step 5: Run the module suite**

Run: `uv run --extra dev pytest tests/test_tool_emulation.py -v`
Expected: PASS (all unit tests green)

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/tool_emulation.py tests/test_tool_emulation.py
git commit -m "feat: add emulation turn loop with re-ask and dedupe"
```

---

## Task 6: Wire the non-streaming emulation path into /v1/chat/completions

**Files:**
- Modify: `src/m365_copilot_openai_proxy/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `run_emulation_turn`, `filter_tools`, `ToolAction`, `FinalAnswer` from `tool_emulation`; `Settings.read_only_tool_names`, `.max_reasks`, `.max_observation_chars`.
- Produces: emulation branch in `chat_completions`; helpers `_tool_calls_response(model_alias, action)` and `_final_message_response(model_alias, text)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`. First add a scripted fake near `FakeCopilotClient`:

```python
class ScriptedChatClient(FakeCopilotClient):
    def __init__(self, replies: list[str]):
        super().__init__()
        self._replies = replies

    async def chat(self, prompt: str, additional_context: list[str], session: object | None = None) -> str:
        self.calls.append((prompt, additional_context))
        self.sessions.append(session)
        return self._replies.pop(0)
```

Then the tests:

```python
READ_TOOL_PAYLOAD = {
    "type": "function",
    "function": {
        "name": "read",
        "description": "Read a file",
        "parameters": {"type": "object", "properties": {"filePath": {"type": "string"}}},
    },
}


def test_chat_completions_emits_tool_call() -> None:
    fake = ScriptedChatClient(['{"action": "read", "args": {"filePath": "app.py"}}'])
    client = build_client(fake)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "m365-copilot",
            "tools": [READ_TOOL_PAYLOAD],
            "messages": [{"role": "user", "content": "summarize app.py"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    choice = body["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["function"]["name"] == "read"
    assert json.loads(call["function"]["arguments"]) == {"filePath": "app.py"}
    assert call["id"].startswith("call_")


def test_chat_completions_emits_final_after_tool_result() -> None:
    fake = ScriptedChatClient(["The file defines create_app()."])
    client = build_client(fake)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "m365-copilot",
            "tools": [READ_TOOL_PAYLOAD],
            "messages": [
                {"role": "user", "content": "summarize app.py"},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{\"filePath\": \"app.py\"}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "def create_app(): ..."},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    choice = body["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert choice["message"]["content"] == "The file defines create_app()."


def test_chat_completions_without_tools_uses_plain_path() -> None:
    fake = FakeCopilotClient()
    client = build_client(fake)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "m365-copilot", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "copilot reply"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_app.py -k "emits_tool_call or emits_final_after or without_tools_uses_plain" -v`
Expected: FAIL (emulation branch not implemented; `tool_calls` absent from response).

- [ ] **Step 3: Write minimal implementation**

In `src/m365_copilot_openai_proxy/app.py`, extend the imports:

```python
from .tool_emulation import FinalAnswer, ToolAction, filter_tools, run_emulation_turn
```

Inside `chat_completions`, before `translated = translate_openai_request(request)`, add the emulation branch:

```python
        allowed = settings.read_only_tool_names
        emulation_tools = filter_tools(request.tools, allowed)
        if emulation_tools:
            if request.stream:
                return StreamingResponse(
                    _emulation_stream(settings.model_alias, client, request, emulation_tools, allowed, settings),
                    media_type="text/event-stream",
                )
            try:
                result = await run_emulation_turn(
                    client,
                    emulation_tools,
                    request.messages,
                    allowed,
                    max_reasks=settings.max_reasks,
                    max_observation_chars=settings.max_observation_chars,
                )
            except SubstrateCopilotError as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            if isinstance(result, ToolAction):
                return JSONResponse(_tool_calls_response(settings.model_alias, result))
            return JSONResponse(_final_message_response(settings.model_alias, result.text))
```

At module level (near the other helper functions), add:

```python
def _tool_calls_response(model_alias: str, action: ToolAction) -> dict:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_alias,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {
                                "name": action.name,
                                "arguments": json.dumps(action.args),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }


def _final_message_response(model_alias: str, text: str) -> dict:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_alias,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
```

Add a placeholder streaming function so the module imports cleanly (implemented fully in Task 7):

```python
async def _emulation_stream(model_alias, client, request, tools, allowed, settings) -> AsyncIterator[str]:
    result = await run_emulation_turn(
        client,
        tools,
        request.messages,
        allowed,
        max_reasks=settings.max_reasks,
        max_observation_chars=settings.max_observation_chars,
    )
    text = result.text if isinstance(result, FinalAnswer) else json.dumps(result.args)
    yield f"data: {json.dumps({'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': 'stop'}]})}\n\n"
    yield "data: [DONE]\n\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_app.py -k "emits_tool_call or emits_final_after or without_tools_uses_plain" -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/app.py tests/test_app.py
git commit -m "feat: emit tool_calls and final answers from chat completions"
```

---

## Task 7: Streaming emulation (tool_calls SSE + final SSE)

**Files:**
- Modify: `src/m365_copilot_openai_proxy/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Replaces the placeholder `_emulation_stream` with a full implementation that emits a proper OpenAI streaming shape for both a tool action and a final answer, and an SSE error on `SubstrateCopilotError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app.py`:

```python
def _collect_stream(client, payload) -> str:
    with client.stream("POST", "/v1/chat/completions", json=payload) as response:
        assert response.status_code == 200
        return "".join(
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for chunk in response.iter_text()
        )


def test_streaming_tool_call_emits_tool_calls_delta() -> None:
    fake = ScriptedChatClient(['{"action": "read", "args": {"filePath": "app.py"}}'])
    client = build_client(fake)
    payload = {
        "model": "m365-copilot",
        "stream": True,
        "tools": [READ_TOOL_PAYLOAD],
        "messages": [{"role": "user", "content": "summarize app.py"}],
    }
    body = _collect_stream(client, payload)
    assert '"tool_calls"' in body
    assert '"name": "read"' in body
    assert '"finish_reason": "tool_calls"' in body
    assert "data: [DONE]" in body


def test_streaming_final_emits_content_delta() -> None:
    fake = ScriptedChatClient(["It defines create_app()."])
    client = build_client(fake)
    payload = {
        "model": "m365-copilot",
        "stream": True,
        "tools": [READ_TOOL_PAYLOAD],
        "messages": [
            {"role": "user", "content": "summarize app.py"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "def create_app(): ..."},
        ],
    }
    body = _collect_stream(client, payload)
    assert '"content": "It defines create_app()."' in body
    assert '"finish_reason": "stop"' in body
    assert "data: [DONE]" in body


def test_streaming_emulation_emits_error_on_upstream_failure() -> None:
    client = build_client(FailingStreamChatClient())
    payload = {
        "model": "m365-copilot",
        "stream": True,
        "tools": [READ_TOOL_PAYLOAD],
        "messages": [{"role": "user", "content": "summarize app.py"}],
    }
    body = _collect_stream(client, payload)
    assert '"type": "upstream_error"' in body
    assert "data: [DONE]" in body
```

Also add this failing client near `FailingStreamCopilotClient`:

```python
class FailingStreamChatClient(FakeCopilotClient):
    async def chat(self, prompt: str, additional_context: list[str], session: object | None = None) -> str:
        raise SubstrateCopilotError("upstream broke")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest tests/test_app.py -k "streaming_tool_call or streaming_final or streaming_emulation_emits_error" -v`
Expected: FAIL (placeholder stream lacks role/tool_calls deltas and error handling).

- [ ] **Step 3: Write the full implementation**

Replace the placeholder `_emulation_stream` in `src/m365_copilot_openai_proxy/app.py` with:

```python
async def _emulation_stream(
    model_alias: str,
    client: SubstrateCopilotClient,
    request: OpenAIChatRequest,
    tools,
    allowed,
    settings: Settings,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl_{uuid.uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict, finish_reason=None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_alias,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    try:
        result = await run_emulation_turn(
            client,
            tools,
            request.messages,
            allowed,
            max_reasks=settings.max_reasks,
            max_observation_chars=settings.max_observation_chars,
        )
    except SubstrateCopilotError as exc:
        yield f"data: {json.dumps({'error': {'message': str(exc), 'type': 'upstream_error'}})}\n\n"
        yield "data: [DONE]\n\n"
        return

    yield chunk({"role": "assistant"})
    if isinstance(result, ToolAction):
        yield chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "type": "function",
                        "function": {"name": result.name, "arguments": json.dumps(result.args)},
                    }
                ]
            }
        )
        yield chunk({}, finish_reason="tool_calls")
    else:
        yield chunk({"content": result.text})
        yield chunk({}, finish_reason="stop")
    yield "data: [DONE]\n\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest tests/test_app.py -k "streaming_tool_call or streaming_final or streaming_emulation_emits_error" -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run --extra dev pytest -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/m365_copilot_openai_proxy/app.py tests/test_app.py
git commit -m "feat: stream tool_calls and final answers for emulation path"
```

---

## Task 8: End-to-end acceptance with OpenCode and README fix

**Files:**
- Modify: `README.md`

**Interfaces:** none (manual acceptance + docs).

- [ ] **Step 1: Confirm the proxy is serving with a valid token**

Run: `Invoke-RestMethod http://127.0.0.1:8000/v1/token/status` (PowerShell)
Expected: `valid: True`, `seconds_remaining > 0`. If not, capture a fresh token first.

- [ ] **Step 2: Verify OpenCode config points at the /v1 base URL**

Confirm `~/.config/opencode/opencode.jsonc` provider `options.baseURL` is `http://127.0.0.1:8000/v1`. (Already set during setup.)

- [ ] **Step 3: Run OpenCode headless against a small project and request a read**

In a directory containing a file `hello.py`, run:
`opencode run "Read hello.py and tell me in one sentence what it does." --model m365copilot/m365-copilot`
Expected: OpenCode performs a `read` tool call (visible in its output) and returns a one-sentence summary of the file. Confirms the full loop: action emitted → OpenCode reads → observation folded → final answer.

- [ ] **Step 4: Update the README**

In `README.md`, in the OpenCode section, change the base URL guidance to note that OpenCode needs the `/v1` suffix and a provider block (not `OPENAI_BASE_URL=http://127.0.0.1:8000`). Under "Limitations", change "Tool calls are not supported" to state that **read-only** tool calls (`read`, `glob`, `grep`, `list`) are supported via emulation for OpenCode, while write/edit/bash are not yet.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document read-only tool support and correct OpenCode base URL"
```

---

## Self-Review Notes

- **Spec coverage:** models/tools (Task 1), config allowlist + caps (Task 2), parse matrix (Task 3), reframed prompt + observations + cap (Task 4), re-ask/dedupe/fallback matrix (Task 5), tool_calls + final responses (Task 6), buffer-then-emit streaming (Task 7), end-to-end acceptance + README fix (Task 8). All spec sections map to a task.
- **Type consistency:** `run_emulation_turn`, `filter_tools`, `render_action_prompt`, `parse_copilot_turn`, `ToolAction`, `FinalAnswer`, `UnavailableAction` names are used identically across tasks. `read_only_tool_names` returns `frozenset[str]` and is consumed as `allowed`/`allowed_names` throughout.
- **No placeholders:** every code step contains full code; the Task 6 `_emulation_stream` is explicitly a minimal placeholder that Task 7 replaces (called out in both tasks).
```
