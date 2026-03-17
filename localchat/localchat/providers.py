from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import AsyncIterator, Callable, Iterable

from google import genai
from google.genai import types
from openai import AsyncOpenAI

from .config import MODEL_MAP, ModelDefinition, get_settings
from .schemas import ChatCompletionRequest, ChatMessage


class ProviderError(RuntimeError):
    """Raised when a provider request cannot be completed."""


@dataclass(frozen=True)
class ResolvedModel:
    public_id: str
    provider: str
    upstream_model: str
    label: str
    description: str
    remote: bool


def resolve_model(model_id: str) -> ResolvedModel:
    if model_id in MODEL_MAP:
        model = MODEL_MAP[model_id]
        return _to_resolved(model)

    for prefix, provider in (("ollama:", "ollama"), ("hf:", "huggingface"), ("gemini:", "gemini")):
        if model_id.startswith(prefix):
            upstream_model = model_id[len(prefix) :]
            return ResolvedModel(
                public_id=model_id,
                provider=provider,
                upstream_model=upstream_model,
                label=upstream_model,
                description="Direct model reference.",
                remote=provider != "ollama",
            )

    available = ", ".join(MODEL_MAP.keys())
    raise ProviderError(f"Unknown model '{model_id}'. Use one of: {available}")


def _to_resolved(model: ModelDefinition) -> ResolvedModel:
    return ResolvedModel(
        public_id=model.id,
        provider=model.provider,
        upstream_model=model.upstream_model,
        label=model.label,
        description=model.description,
        remote=model.remote,
    )


def openai_style_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


def gemini_contents(messages: list[ChatMessage]) -> tuple[str | None, list[types.Content]]:
    system_messages = [message.content for message in messages if message.role == "system"]
    contents = [
        types.Content(
            role="model" if message.role == "assistant" else "user",
            parts=[types.Part.from_text(text=message.content)],
        )
        for message in messages
        if message.role != "system"
    ]
    return ("\n\n".join(system_messages) or None, contents)


def _openai_base_url_for_ollama() -> str:
    base_url = get_settings().ollama_base_url
    return base_url if base_url.endswith("/v1") else f"{base_url}/v1"


@lru_cache(maxsize=1)
def _ollama_client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=_openai_base_url_for_ollama(), api_key="ollama")


@lru_cache(maxsize=1)
def _huggingface_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.huggingface_base_url,
        api_key=settings.huggingface_api_key or "missing",
    )


@lru_cache(maxsize=1)
def _gemini_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _require_provider_key(provider: str) -> None:
    settings = get_settings()
    if provider == "huggingface" and not settings.huggingface_api_key:
        raise ProviderError("HUGGINGFACE_API_KEY is missing in .env")
    if provider == "gemini" and not settings.gemini_api_key:
        raise ProviderError("GEMINI_API_KEY is missing in .env")


async def stream_text(request: ChatCompletionRequest, resolved: ResolvedModel) -> AsyncIterator[str]:
    if resolved.provider in {"ollama", "huggingface"}:
        async for chunk in _stream_openai_compatible(request, resolved):
            yield chunk
        return

    if resolved.provider == "gemini":
        async for chunk in _stream_gemini(request, resolved):
            yield chunk
        return

    raise ProviderError(f"Unsupported provider '{resolved.provider}'")


async def complete_text(request: ChatCompletionRequest, resolved: ResolvedModel) -> str:
    if resolved.provider in {"ollama", "huggingface"}:
        return await _complete_openai_compatible(request, resolved)
    if resolved.provider == "gemini":
        return await _complete_gemini(request, resolved)
    raise ProviderError(f"Unsupported provider '{resolved.provider}'")


async def _stream_openai_compatible(
    request: ChatCompletionRequest, resolved: ResolvedModel
) -> AsyncIterator[str]:
    if resolved.provider == "huggingface":
        _require_provider_key("huggingface")

    client = _ollama_client() if resolved.provider == "ollama" else _huggingface_client()
    try:
        stream = await client.chat.completions.create(
            model=resolved.upstream_model,
            messages=openai_style_messages(request.messages),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None or not getattr(delta, "content", None):
                continue
            content = delta.content
            if isinstance(content, str):
                yield content
                continue
            if isinstance(content, list):
                for part in content:
                    text = getattr(part, "text", None)
                    if text:
                        yield text
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise ProviderError(str(exc)) from exc


async def _complete_openai_compatible(
    request: ChatCompletionRequest, resolved: ResolvedModel
) -> str:
    if resolved.provider == "huggingface":
        _require_provider_key("huggingface")

    client = _ollama_client() if resolved.provider == "ollama" else _huggingface_client()
    try:
        response = await client.chat.completions.create(
            model=resolved.upstream_model,
            messages=openai_style_messages(request.messages),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False,
        )
        content = response.choices[0].message.content or ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(getattr(part, "text", "") for part in content)
        return str(content)
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise ProviderError(str(exc)) from exc


async def _stream_gemini(request: ChatCompletionRequest, resolved: ResolvedModel) -> AsyncIterator[str]:
    _require_provider_key("gemini")
    system_instruction, contents = gemini_contents(request.messages)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=request.temperature,
        max_output_tokens=request.max_tokens,
    )

    def factory() -> Iterable[str]:
        stream = _gemini_client().models.generate_content_stream(
            model=resolved.upstream_model,
            contents=contents,
            config=config,
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text

    async for chunk in _iterate_blocking_stream(factory):
        yield chunk


async def _complete_gemini(request: ChatCompletionRequest, resolved: ResolvedModel) -> str:
    _require_provider_key("gemini")
    system_instruction, contents = gemini_contents(request.messages)
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=request.temperature,
        max_output_tokens=request.max_tokens,
    )

    def run_completion() -> str:
        response = _gemini_client().models.generate_content(
            model=resolved.upstream_model,
            contents=contents,
            config=config,
        )
        return response.text or ""

    return await asyncio.to_thread(run_completion)


async def _iterate_blocking_stream(factory: Callable[[], Iterable[str]]) -> AsyncIterator[str]:
    queue: asyncio.Queue[tuple[str, str | Exception | None]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker() -> None:
        try:
            for item in factory():
                asyncio.run_coroutine_threadsafe(queue.put(("data", item)), loop).result()
        except Exception as exc:  # pragma: no cover - network/provider failure path
            asyncio.run_coroutine_threadsafe(queue.put(("error", exc)), loop).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop).result()

    worker_task = asyncio.create_task(asyncio.to_thread(worker))
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "data":
                yield str(payload)
            elif kind == "error":
                raise ProviderError(str(payload))
            else:
                break
    finally:
        await worker_task


def stream_chunk(model: str, completion_id: str, text: str | None = None, *, done: bool = False) -> dict:
    delta: dict[str, str] = {"role": "assistant"}
    finish_reason = None
    if text is not None:
        delta = {"content": text}
    if done:
        delta = {}
        finish_reason = "stop"
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def completion_payload(model: str, completion_id: str, text: str) -> dict:
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }
