from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, AsyncIterator, Callable, Iterable

try:
    from anthropic import AsyncAnthropic
except Exception:  # pragma: no cover - optional dependency fallback
    AsyncAnthropic = None  # type: ignore[assignment]
try:
    from google import genai
    from google.genai import types
except Exception:  # pragma: no cover - optional dependency fallback
    genai = None  # type: ignore[assignment]
    types = None  # type: ignore[assignment]
from openai import AsyncOpenAI

from .config import ModelDefinition, get_model_map, get_settings
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
    model_map = get_model_map()
    if model_id in model_map:
        model = model_map[model_id]
        return _to_resolved(model)

    for prefix, provider in (
        ("ollama:", "ollama"),
        ("hf:", "huggingface"),
        ("gemini:", "gemini"),
        ("openai:", "openai"),
        ("anthropic:", "anthropic"),
    ):
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

    available = ", ".join(model_map.keys())
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
    _require_gemini_sdk()
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


def provider_options(request: ChatCompletionRequest) -> dict:
    return request.provider_options if isinstance(request.provider_options, dict) else {}


def _extract_text_from_gemini_response(response: Any) -> str:
    try:
        text = getattr(response, "text", None)
    except Exception:
        text = None
    if isinstance(text, str):
        if text:
            return text
    elif text is not None:
        rendered = str(text)
        if rendered:
            return rendered

    candidates = getattr(response, "candidates", None)
    if candidates is None and isinstance(response, dict):
        candidates = response.get("candidates")

    text_parts: list[str] = []
    for candidate in candidates or []:
        content = getattr(candidate, "content", None)
        if content is None and isinstance(candidate, dict):
            content = candidate.get("content")

        parts = getattr(content, "parts", None) if content is not None else None
        if parts is None and isinstance(content, dict):
            parts = content.get("parts")

        for part in parts or []:
            part_text = getattr(part, "text", None)
            if part_text is None and isinstance(part, dict):
                part_text = part.get("text")
            if isinstance(part_text, str):
                if part_text:
                    text_parts.append(part_text)
            elif part_text is not None:
                rendered_part = str(part_text)
                if rendered_part:
                    text_parts.append(rendered_part)
    return "".join(text_parts)


def _gemini_empty_response_reason(response: Any) -> str:
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            return f"prompt blocked ({block_reason})"

    candidates = getattr(response, "candidates", None)
    if candidates is None and isinstance(response, dict):
        candidates = response.get("candidates")
    if not candidates:
        return "no candidates returned"

    finish_reasons: list[str] = []
    for candidate in candidates:
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason is None and isinstance(candidate, dict):
            finish_reason = candidate.get("finish_reason")
        rendered = str(finish_reason or "").strip()
        if rendered:
            finish_reasons.append(rendered)
    finish_reasons = [reason for reason in finish_reasons if reason]
    if finish_reasons:
        return f"finish_reason={','.join(finish_reasons)}"
    return "candidate parts contained no text"


def _build_gemini_thinking_config(options: dict, fallback_budget: int | None = None) -> Any | None:
    budget_raw = options.get("thinking_budget", fallback_budget)
    include_thoughts_raw = options.get("include_thoughts")

    payload: dict[str, Any] = {}
    if budget_raw is not None:
        try:
            payload["thinking_budget"] = int(budget_raw)
        except (TypeError, ValueError):
            pass
    if include_thoughts_raw is not None:
        payload["include_thoughts"] = bool(include_thoughts_raw)

    if not payload:
        return None
    return types.ThinkingConfig(**payload)


def _gemini_generate_config(
    *,
    system_instruction: str | None,
    temperature: float | None,
    max_tokens: int | None,
    options: dict,
    fallback_thinking_budget: int | None = None,
) -> Any:
    return types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_tokens,
        top_k=options.get("top_k"),
        top_p=options.get("top_p"),
        thinking_config=_build_gemini_thinking_config(options, fallback_budget=fallback_thinking_budget),
    )


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
def _openai_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key or "missing",
    )


@lru_cache(maxsize=1)
def _gemini_client() -> Any:
    _require_gemini_sdk()
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


@lru_cache(maxsize=1)
def _anthropic_client() -> AsyncAnthropic:
    if AsyncAnthropic is None:
        raise ProviderError("Anthropic support requires the 'anthropic' package. Run dependency sync/install.")
    settings = get_settings()
    return AsyncAnthropic(
        api_key=settings.anthropic_api_key or "missing",
        base_url=settings.anthropic_base_url,
    )


def _require_provider_key(provider: str) -> None:
    settings = get_settings()
    if provider == "huggingface" and not settings.huggingface_api_key:
        raise ProviderError("HUGGINGFACE_API_KEY is missing in .env")
    if provider == "gemini" and not settings.gemini_api_key:
        raise ProviderError("GEMINI_API_KEY is missing in .env")
    if provider == "openai" and not settings.openai_api_key:
        raise ProviderError("OPENAI_API_KEY is missing in .env")
    if provider == "anthropic" and not settings.anthropic_api_key:
        raise ProviderError("ANTHROPIC_API_KEY is missing in .env")


def _require_gemini_sdk() -> None:
    if genai is None or types is None:
        raise ProviderError("Gemini support requires the 'google-genai' package. Run dependency sync/install.")


async def stream_text(request: ChatCompletionRequest, resolved: ResolvedModel) -> AsyncIterator[str]:
    if resolved.provider in {"ollama", "huggingface", "openai"}:
        async for chunk in _stream_openai_compatible(request, resolved):
            yield chunk
        return

    if resolved.provider == "gemini":
        async for chunk in _stream_gemini(request, resolved):
            yield chunk
        return

    if resolved.provider == "anthropic":
        async for chunk in _stream_anthropic(request, resolved):
            yield chunk
        return

    raise ProviderError(f"Unsupported provider '{resolved.provider}'")


async def complete_text(request: ChatCompletionRequest, resolved: ResolvedModel) -> str:
    if resolved.provider in {"ollama", "huggingface", "openai"}:
        return await _complete_openai_compatible(request, resolved)
    if resolved.provider == "gemini":
        return await _complete_gemini(request, resolved)
    if resolved.provider == "anthropic":
        return await _complete_anthropic(request, resolved)
    raise ProviderError(f"Unsupported provider '{resolved.provider}'")


async def _stream_openai_compatible(
    request: ChatCompletionRequest, resolved: ResolvedModel
) -> AsyncIterator[str]:
    if resolved.provider == "huggingface":
        _require_provider_key("huggingface")
    if resolved.provider == "openai":
        _require_provider_key("openai")

    if resolved.provider == "ollama":
        client = _ollama_client()
    elif resolved.provider == "huggingface":
        client = _huggingface_client()
    else:
        client = _openai_client()
    try:
        stream = await client.chat.completions.create(
            model=resolved.upstream_model,
            messages=openai_style_messages(request.messages),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            extra_body=provider_options(request) or None,
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
    if resolved.provider == "openai":
        _require_provider_key("openai")

    if resolved.provider == "ollama":
        client = _ollama_client()
    elif resolved.provider == "huggingface":
        client = _huggingface_client()
    else:
        client = _openai_client()
    try:
        response = await client.chat.completions.create(
            model=resolved.upstream_model,
            messages=openai_style_messages(request.messages),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            extra_body=provider_options(request) or None,
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
    options = provider_options(request)
    config = _gemini_generate_config(
        system_instruction=system_instruction,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        options=options,
    )

    def factory() -> Iterable[str]:
        stream = _gemini_client().models.generate_content_stream(
            model=resolved.upstream_model,
            contents=contents,
            config=config,
        )
        for chunk in stream:
            text = _extract_text_from_gemini_response(chunk)
            if text:
                yield text

    async for chunk in _iterate_blocking_stream(factory):
        yield chunk


async def _complete_gemini(request: ChatCompletionRequest, resolved: ResolvedModel) -> str:
    _require_provider_key("gemini")
    system_instruction, contents = gemini_contents(request.messages)
    options = provider_options(request)
    config = _gemini_generate_config(
        system_instruction=system_instruction,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        options=options,
    )

    def run_completion() -> str:
        response = _gemini_client().models.generate_content(
            model=resolved.upstream_model,
            contents=contents,
            config=config,
        )
        text = _extract_text_from_gemini_response(response)
        if text:
            return text

        reason = _gemini_empty_response_reason(response)
        if "MAX_TOKENS" in reason:
            retry_config = _gemini_generate_config(
                system_instruction=system_instruction,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                options=options,
                fallback_thinking_budget=128,
            )
            retry_response = _gemini_client().models.generate_content(
                model=resolved.upstream_model,
                contents=contents,
                config=retry_config,
            )
            retry_text = _extract_text_from_gemini_response(retry_response)
            if retry_text:
                return retry_text

        # Some google-genai responses can expose no top-level text in non-stream mode.
        stream = _gemini_client().models.generate_content_stream(
            model=resolved.upstream_model,
            contents=contents,
            config=config,
        )
        stream_chunks: list[str] = []
        for chunk in stream:
            chunk_text = _extract_text_from_gemini_response(chunk)
            if chunk_text:
                stream_chunks.append(chunk_text)
        stream_text = "".join(stream_chunks)
        if stream_text:
            return stream_text

        raise ProviderError(f"Gemini returned an empty response ({reason}).")

    try:
        return await asyncio.to_thread(run_completion)
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise ProviderError(str(exc)) from exc


def anthropic_messages(messages: list[ChatMessage]) -> tuple[str | None, list[dict[str, str]]]:
    system_messages = [message.content for message in messages if message.role == "system"]
    contents = [
        {"role": "assistant" if message.role == "assistant" else "user", "content": message.content}
        for message in messages
        if message.role != "system"
    ]
    return ("\n\n".join(system_messages) or None, contents)


async def _stream_anthropic(request: ChatCompletionRequest, resolved: ResolvedModel) -> AsyncIterator[str]:
    # Keep streaming shape simple and reliable by yielding a complete response chunk.
    text = await _complete_anthropic(request, resolved)
    if text:
        yield text


async def _complete_anthropic(request: ChatCompletionRequest, resolved: ResolvedModel) -> str:
    _require_provider_key("anthropic")
    system_instruction, messages = anthropic_messages(request.messages)
    options = provider_options(request)
    try:
        response = await _anthropic_client().messages.create(
            model=resolved.upstream_model,
            system=system_instruction if system_instruction is not None else "",
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens or 1024,
            top_k=options.get("top_k"),
            top_p=options.get("top_p"),
        )
        text_parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        return "".join(text_parts).strip()
    except Exception as exc:  # pragma: no cover - network/provider failure path
        raise ProviderError(str(exc)) from exc


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
