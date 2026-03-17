from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class ModelDefinition:
    id: str
    label: str
    provider: str
    upstream_model: str
    description: str
    remote: bool


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
    ),
)

MODEL_MAP = {model.id: model for model in DEFAULT_MODELS}


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    huggingface_api_key: str
    gemini_api_key: str
    ollama_base_url: str
    collaboration_allow_remote_clients: bool
    collaboration_allow_remote_pages: bool
    collaboration_allowed_client_ips: tuple[str, ...]
    huggingface_base_url: str = "https://router.huggingface.co/v1"


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        huggingface_api_key=os.getenv("HUGGINGFACE_API_KEY", "").strip(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
        collaboration_allow_remote_clients=env_bool("COLLAB_ALLOW_REMOTE_CLIENTS", False),
        collaboration_allow_remote_pages=env_bool("COLLAB_ALLOW_REMOTE_PAGES", False),
        collaboration_allowed_client_ips=env_csv("COLLAB_ALLOWED_CLIENT_IPS"),
    )
