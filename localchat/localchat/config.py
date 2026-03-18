from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CUSTOM_MODELS_PATH = PROJECT_ROOT / "custom_models.json"
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    label: str
    provider: str
    upstream_model: str
    description: str
    remote: bool
    default_temperature: float | None = None
    default_max_tokens: int | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)


DEFAULT_MODELS = (
    ModelDefinition(
        id="ollama:qwen2.5:7b",
        label="Qwen 2.5 7B Local",
        provider="ollama",
        upstream_model="qwen2.5:7b",
        description="Local Ollama model tuned for general chat and coding.",
        remote=False,
    ),
    ModelDefinition(
        id="ollama:deepseek-r1",
        label="DeepSeek R1 Local",
        provider="ollama",
        upstream_model="deepseek-r1",
        description="Local Ollama reasoning model.",
        remote=False,
    ),
    ModelDefinition(
        id="ollama:gemma3:7b",
        label="Gemma 3 7B Local",
        provider="ollama",
        upstream_model="gemma3:7b",
        description="Local Gemma 7B-class model served by Ollama.",
        remote=False,
    ),
    ModelDefinition(
        id="ollama:gemma3:12b",
        label="Gemma 3 12B Local",
        provider="ollama",
        upstream_model="gemma3:12b",
        description="Stronger local Gemma model that fits well on a 4070-class machine with system RAM fallback.",
        remote=False,
    ),
    ModelDefinition(
        id="hf:Qwen/Qwen2.5-Coder-32B-Instruct",
        label="Qwen 2.5 Coder 32B",
        provider="huggingface",
        upstream_model="Qwen/Qwen2.5-Coder-32B-Instruct",
        description="Remote Hugging Face instruction model for stronger drafting and coding help.",
        remote=True,
    ),
    ModelDefinition(
        id="hf:deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        label="DeepSeek R1 Distill Qwen 32B",
        provider="huggingface",
        upstream_model="deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        description="Remote Hugging Face reasoning-oriented model.",
        remote=True,
    ),
    ModelDefinition(
        id="gemini:gemini-2.5-flash",
        label="Gemini 2.5 Flash",
        provider="gemini",
        upstream_model="gemini-2.5-flash",
        description="Fast remote Gemini model for drafting assistance.",
        remote=True,
        default_temperature=0.4,
        default_max_tokens=1400,
    ),
    ModelDefinition(
        id="gemini:gemini-2.5-pro",
        label="Gemini 2.5 Pro",
        provider="gemini",
        upstream_model="gemini-2.5-pro",
        description="Higher quality Gemini model for deeper reasoning and drafting.",
        remote=True,
        default_temperature=0.3,
        default_max_tokens=1800,
    ),
    ModelDefinition(
        id="openai:gpt-4o-mini",
        label="OpenAI GPT-4o Mini",
        provider="openai",
        upstream_model="gpt-4o-mini",
        description="Remote OpenAI model for general chat and drafting.",
        remote=True,
        default_temperature=0.4,
        default_max_tokens=1400,
    ),
    ModelDefinition(
        id="anthropic:claude-3-5-sonnet-latest",
        label="Anthropic Claude 3.5 Sonnet",
        provider="anthropic",
        upstream_model="claude-3-5-sonnet-latest",
        description="Remote Anthropic model for reasoning and writing help.",
        remote=True,
        default_temperature=0.4,
        default_max_tokens=1600,
    ),
)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    huggingface_api_key: str
    gemini_api_key: str
    openai_api_key: str
    anthropic_api_key: str
    ollama_base_url: str
    collaboration_allow_remote_clients: bool
    collaboration_allow_remote_pages: bool
    collaboration_allowed_client_ips: tuple[str, ...]
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_base_url: str = "https://api.anthropic.com"
    huggingface_base_url: str = "https://router.huggingface.co/v1"


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _to_model_definition(raw: dict[str, Any]) -> ModelDefinition | None:
    provider = str(raw.get("provider") or "").strip().lower()
    model_id = str(raw.get("id") or "").strip()
    upstream_model = str(raw.get("upstream_model") or raw.get("upstreamModel") or "").strip()
    if not provider or not model_id or not upstream_model:
        return None
    if provider not in {"ollama", "huggingface", "gemini", "openai", "anthropic"}:
        return None
    label = str(raw.get("label") or upstream_model).strip() or upstream_model
    description = str(raw.get("description") or "Custom model").strip() or "Custom model"
    remote = bool(raw.get("remote", provider != "ollama"))
    default_temperature = raw.get("default_temperature", raw.get("defaultTemperature"))
    default_max_tokens = raw.get("default_max_tokens", raw.get("defaultMaxTokens"))
    provider_options = raw.get("provider_options", raw.get("providerOptions"))

    try:
        parsed_temperature = float(default_temperature) if default_temperature is not None else None
    except (TypeError, ValueError):
        parsed_temperature = None
    if parsed_temperature is not None:
        parsed_temperature = max(0.0, min(2.0, parsed_temperature))

    try:
        parsed_max_tokens = int(default_max_tokens) if default_max_tokens is not None else None
    except (TypeError, ValueError):
        parsed_max_tokens = None
    if parsed_max_tokens is not None:
        parsed_max_tokens = max(1, min(8192, parsed_max_tokens))

    normalized_options = provider_options if isinstance(provider_options, dict) else {}

    return ModelDefinition(
        id=model_id,
        label=label,
        provider=provider,
        upstream_model=upstream_model,
        description=description,
        remote=remote,
        default_temperature=parsed_temperature,
        default_max_tokens=parsed_max_tokens,
        provider_options=normalized_options,
    )


@lru_cache(maxsize=1)
def load_custom_models() -> tuple[ModelDefinition, ...]:
    if not CUSTOM_MODELS_PATH.exists():
        return ()
    try:
        payload = json.loads(CUSTOM_MODELS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return ()

    items = payload if isinstance(payload, list) else []
    models: list[ModelDefinition] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        model = _to_model_definition(item)
        if model is None or model.id in seen_ids:
            continue
        models.append(model)
        seen_ids.add(model.id)
    return tuple(models)


@lru_cache(maxsize=1)
def get_model_catalog() -> tuple[ModelDefinition, ...]:
    combined: list[ModelDefinition] = []
    seen_ids: set[str] = set()
    for model in (*DEFAULT_MODELS, *load_custom_models()):
        if model.id in seen_ids:
            continue
        combined.append(model)
        seen_ids.add(model.id)
    return tuple(combined)


@lru_cache(maxsize=1)
def get_model_map() -> dict[str, ModelDefinition]:
    return {model.id: model for model in get_model_catalog()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        huggingface_api_key=os.getenv("HUGGINGFACE_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        collaboration_allow_remote_clients=env_bool("COLLAB_ALLOW_REMOTE_CLIENTS", False),
        collaboration_allow_remote_pages=env_bool("COLLAB_ALLOW_REMOTE_PAGES", False),
        collaboration_allowed_client_ips=env_csv("COLLAB_ALLOWED_CLIENT_IPS"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
    )
