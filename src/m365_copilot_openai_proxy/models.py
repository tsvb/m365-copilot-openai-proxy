from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContentPart(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str
    text: str | None = None


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


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None


class OpenAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[OpenAIMessage]
    stream: bool = False
    temperature: float | None = None
    user: str | None = None
    tools: list[ToolSpec] | None = None
    tool_choice: Any | None = None


class AnthropicMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str | list[ContentPart]


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    messages: list[AnthropicMessage]
    system: str | list[ContentPart] | None = None
    stream: bool = False
    max_tokens: int | None = None
    temperature: float | None = None


class CopilotMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    text: str = ""
    attributions: list[dict[str, Any]] = Field(default_factory=list)


class CopilotConversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    messages: list[CopilotMessage] = Field(default_factory=list)


class OpenAIResponsesRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    input: str | list[Any]
    instructions: str | None = None
    stream: bool = False


class TranslatedRequest(BaseModel):
    prompt: str
    additional_context: list[str] = Field(default_factory=list)
