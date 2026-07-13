from __future__ import annotations

from m365_copilot_openai_proxy.config import Settings
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
