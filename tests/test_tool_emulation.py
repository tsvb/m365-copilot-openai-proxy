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
