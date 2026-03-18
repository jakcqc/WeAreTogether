from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class ChatCompletionRequest(BaseModel):
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = True
    temperature: float | None = Field(default=0.7, ge=0, le=2)
    max_tokens: int | None = Field(default=1024, ge=1, le=8192)
    provider_options: dict[str, Any] | None = None


class ModelResponse(BaseModel):
    id: str
    label: str
    provider: str
    description: str
    remote: bool
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    provider_options: dict[str, Any] = Field(default_factory=dict)
