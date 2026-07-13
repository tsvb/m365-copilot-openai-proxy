from __future__ import annotations

from m365_copilot_openai_proxy.config import Settings
from m365_copilot_openai_proxy.models import OpenAIChatRequest, OpenAIMessage


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


def test_run_reasks_on_duplicate_action() -> None:
    # Build messages with prior read action for a.py
    messages = [
        OpenAIMessage.model_validate({"role": "user", "content": "read a.py"}),
        OpenAIMessage.model_validate({
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "read", "arguments": "{\"filePath\": \"a.py\"}"}}
            ],
        }),
        OpenAIMessage.model_validate({"role": "tool", "tool_call_id": "c1", "content": "x = 1"}),
    ]

    # Client returns duplicate action first, then final answer
    client = ScriptedClient(
        ['{"action": "read", "args": {"filePath": "a.py"}}', "It defines x."]
    )

    # Get tools
    tools = _request({"model": "m", "tools": [READ_TOOL], "messages": [{"role": "user", "content": "x"}]}).tools

    # Run the emulation
    result = asyncio.run(
        run_emulation_turn(
            client,
            filter_tools(tools, frozenset({"read"})),
            messages,
            frozenset({"read"}),
            max_reasks=2,
            max_observation_chars=100
        )
    )

    # Assertions
    assert result == FinalAnswer(text="It defines x.")
    assert len(client.prompts) == 2
    assert "already requested" in client.prompts[1]
