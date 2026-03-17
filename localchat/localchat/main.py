from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request as urllib_request
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import DEFAULT_MODELS, get_settings
from .providers import (
    ProviderError,
    complete_text,
    completion_payload,
    resolve_model,
    stream_chunk,
    stream_text,
)
from .schemas import ChatCompletionRequest, ChatMessage, ModelResponse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DRAFTER_ASSETS_DIR = STATIC_DIR / "drafter_uploads"
DOWNLOADS_DIR = BASE_DIR.parent / "downloads"
ROOM_HISTORY_LIMIT = 120
ROOM_CONTEXT_MESSAGE_LIMIT = 18
ROOM_CONTEXT_CHAR_BUDGET = 16000
DRAFTER_TEXT_ASSET_LIMIT = 250_000
DRAFTER_IMAGE_ASSET_LIMIT = 3_500_000
DRAFTER_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
DRAFTER_ALLOWED_TEXT_EXTENSIONS = {".bib", ".tex"}
ROOM_AI_SYSTEM_PROMPT = (
    "You are a participant-owned AI assistant inside a small multi-user chat room. "
    "Reply naturally to the room, keep answers concise, and use the recent chat context. "
    "If someone asks for code or technical help, be direct and practical."
)

app = FastAPI(title="Local Chat", version="0.1.0")
DRAFTER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
app.mount("/downloads", StaticFiles(directory=DOWNLOADS_DIR), name="downloads")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)


@dataclass
class RoomState:
    clients: set[WebSocket] = field(default_factory=set)
    history: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class DraftCollaborator:
    name: str
    state: str = "viewing"
    joined_at: int = field(default_factory=lambda: int(time.time() * 1000))
    last_active: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class DraftState:
    clients: dict[WebSocket, DraftCollaborator] = field(default_factory=dict)
    content: str = ""
    updated_at: int = 0


class RoomHub:
    def __init__(self) -> None:
        self._rooms: dict[str, RoomState] = {}
        self._lock = asyncio.Lock()

    async def connect(self, room_name: str, websocket: WebSocket) -> list[dict[str, Any]]:
        await websocket.accept()
        async with self._lock:
            room = self._rooms.setdefault(room_name, RoomState())
            room.clients.add(websocket)
            return list(room.history)

    async def disconnect(self, room_name: str, websocket: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return
            room.clients.discard(websocket)
            if not room.clients and not room.history:
                self._rooms.pop(room_name, None)

    async def snapshot(self, room_name: str) -> list[dict[str, Any]]:
        async with self._lock:
            room = self._rooms.get(room_name)
            return list(room.history) if room else []

    async def append_and_broadcast(self, room_name: str, message: dict[str, Any]) -> None:
        async with self._lock:
            room = self._rooms.setdefault(room_name, RoomState())
            room.history.append(message)
            if len(room.history) > ROOM_HISTORY_LIMIT:
                room.history = room.history[-ROOM_HISTORY_LIMIT:]
            clients = list(room.clients)

        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(message)
            except Exception:
                stale_clients.append(client)

        for client in stale_clients:
            await self.disconnect(room_name, client)


room_hub = RoomHub()


class DraftHub:
    def __init__(self) -> None:
        self._drafts: dict[str, DraftState] = {}
        self._lock = asyncio.Lock()

    async def connect(self, draft_name: str, websocket: WebSocket, collaborator_name: str) -> dict[str, Any]:
        await websocket.accept()
        now = int(time.time() * 1000)
        async with self._lock:
            draft = self._drafts.setdefault(draft_name, DraftState())
            draft.clients[websocket] = DraftCollaborator(name=collaborator_name, joined_at=now, last_active=now)
            return {
                "content": draft.content,
                "updatedAt": draft.updated_at,
                "collaborators": self._serialize_collaborators(draft),
            }

    async def disconnect(self, draft_name: str, websocket: WebSocket) -> None:
        async with self._lock:
            draft = self._drafts.get(draft_name)
            if draft is None:
                return
            draft.clients.pop(websocket, None)
            if not draft.clients and not draft.content:
                self._drafts.pop(draft_name, None)

    async def broadcast_presence(self, draft_name: str) -> None:
        async with self._lock:
            draft = self._drafts.get(draft_name)
            if draft is None:
                return
            payload = {
                "type": "presence",
                "draft": draft_name,
                "collaborators": self._serialize_collaborators(draft),
                "updatedAt": draft.updated_at,
            }
        await self._broadcast(draft_name, payload)

    async def update_presence(self, draft_name: str, websocket: WebSocket, state: str) -> None:
        async with self._lock:
            draft = self._drafts.get(draft_name)
            if draft is None:
                return
            collaborator = draft.clients.get(websocket)
            if collaborator is None:
                return
            collaborator.state = state
            collaborator.last_active = int(time.time() * 1000)
        await self.broadcast_presence(draft_name)

    async def sync_content(
        self,
        draft_name: str,
        websocket: WebSocket,
        *,
        sender_name: str,
        content: str,
        state: str,
    ) -> None:
        async with self._lock:
            draft = self._drafts.setdefault(draft_name, DraftState())
            collaborator = draft.clients.get(websocket)
            if collaborator is not None:
                collaborator.state = state
                collaborator.last_active = int(time.time() * 1000)
            draft.content = content
            draft.updated_at = int(time.time() * 1000)
            payload = {
                "type": "draft_update",
                "draft": draft_name,
                "sender": sender_name,
                "content": draft.content,
                "updatedAt": draft.updated_at,
                "collaborators": self._serialize_collaborators(draft),
            }
        await self._broadcast(draft_name, payload)

    async def _broadcast(self, draft_name: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            draft = self._drafts.get(draft_name)
            clients = list(draft.clients.keys()) if draft else []

        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)

        if not stale_clients:
            return

        async with self._lock:
            draft = self._drafts.get(draft_name)
            if draft is None:
                return
            for client in stale_clients:
                draft.clients.pop(client, None)
            if not draft.clients and not draft.content:
                self._drafts.pop(draft_name, None)

    def _serialize_collaborators(self, draft: DraftState) -> list[dict[str, Any]]:
        collaborators = [
            {
                "name": collaborator.name,
                "state": collaborator.state,
                "joinedAt": collaborator.joined_at,
                "lastActive": collaborator.last_active,
            }
            for collaborator in draft.clients.values()
        ]
        collaborators.sort(key=lambda item: (-int(item["lastActive"]), str(item["name"]).lower()))
        return collaborators


draft_hub = DraftHub()


def installed_ollama_models() -> set[str] | None:
    tags_url = f"{get_settings().ollama_base_url}/api/tags"
    try:
        with urllib_request.urlopen(tags_url, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, error.URLError):
        return None

    models = set()
    for item in payload.get("models", []):
        name = str(item.get("name") or "").strip()
        model = str(item.get("model") or "").strip()
        for candidate in (name, model):
            if not candidate:
                continue
            models.add(candidate)
            if ":" in candidate:
                models.add(candidate.rsplit(":", 1)[0])
    return models


def visible_models() -> list:
    installed = installed_ollama_models()
    settings = get_settings()
    has_huggingface = bool(settings.huggingface_api_key)
    has_gemini = bool(settings.gemini_api_key)

    if installed is None:
        installed = set()

    filtered = []
    for model in DEFAULT_MODELS:
        if model.provider == "huggingface":
            if has_huggingface:
                filtered.append(model)
            continue
        if model.provider == "gemini":
            if has_gemini:
                filtered.append(model)
            continue
        if model.provider != "ollama":
            filtered.append(model)
            continue
        if model.upstream_model in installed:
            filtered.append(model)
    return filtered


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/room", include_in_schema=False)
async def room_page(request: Request) -> FileResponse:
    ensure_collaboration_page_access(request)
    return FileResponse(STATIC_DIR / "room.html")


@app.get("/drafter", include_in_schema=False)
async def drafter_page(request: Request) -> FileResponse:
    ensure_collaboration_page_access(request)
    return FileResponse(STATIC_DIR / "drafter.html")


@app.get("/api/drafter/assets")
async def api_drafter_assets(request: Request) -> list[dict[str, Any]]:
    ensure_collaboration_page_access(request)
    assets = [
        serialize_drafter_asset(path)
        for path in sorted(DRAFTER_ASSETS_DIR.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and drafter_asset_kind(path.name)
    ]
    assets.sort(key=lambda asset: (-int(asset["updatedAt"]), str(asset["name"]).lower()))
    return assets


@app.post("/api/drafter/assets")
async def create_drafter_asset(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_collaboration_page_access(request)
    asset_name = normalize_drafter_asset_name(payload.get("name"))
    asset_kind = drafter_asset_kind(asset_name)
    if not asset_kind:
        raise HTTPException(status_code=400, detail="Only image, .bib, and .tex assets are supported.")

    asset_path = DRAFTER_ASSETS_DIR / asset_name
    content = payload.get("content")
    if asset_kind == "image":
        data_url = str(content or "").strip()
        match = re.match(r"^data:[^;]+;base64,(.+)$", data_url, flags=re.IGNORECASE)
        if not match:
            raise HTTPException(status_code=400, detail="Image uploads must include a base64 data URL.")
        try:
            image_bytes = base64.b64decode(match.group(1), validate=True)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Image upload could not be decoded.") from exc
        if len(image_bytes) > DRAFTER_IMAGE_ASSET_LIMIT:
            raise HTTPException(status_code=400, detail="Image upload is too large.")
        asset_path.write_bytes(image_bytes)
    else:
        text_content = str(content or "")
        encoded = text_content.encode("utf-8")
        if len(encoded) > DRAFTER_TEXT_ASSET_LIMIT:
            raise HTTPException(status_code=400, detail="Text asset is too large.")
        asset_path.write_text(text_content, encoding="utf-8")

    return serialize_drafter_asset(asset_path)


@app.delete("/api/drafter/assets/{asset_name}")
async def delete_drafter_asset(request: Request, asset_name: str) -> dict[str, str]:
    ensure_collaboration_page_access(request)
    normalized_name = normalize_drafter_asset_name(asset_name)
    asset_path = DRAFTER_ASSETS_DIR / normalized_name
    if not asset_path.is_file() or not drafter_asset_kind(asset_path.name):
        raise HTTPException(status_code=404, detail="Asset not found.")
    asset_path.unlink(missing_ok=False)
    return {"status": "deleted", "name": normalized_name}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models", response_model=list[ModelResponse])
async def api_models() -> list[ModelResponse]:
    return [
        ModelResponse(
            id=model.id,
            label=model.label,
            provider=model.provider,
            description=model.description,
            remote=model.remote,
        )
        for model in visible_models()
    ]


@app.get("/v1/models")
async def openai_models() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": model.id,
                "object": "model",
                "created": 0,
                "owned_by": model.provider,
            }
            for model in visible_models()
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    try:
        resolved = resolve_model(request.model)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    completion_id = f"chatcmpl_{secrets.token_hex(12)}"

    if request.stream:
        async def event_stream():
            try:
                yield _sse(stream_chunk(request.model, completion_id))
                async for text in stream_text(request, resolved):
                    yield _sse(stream_chunk(request.model, completion_id, text))
                yield _sse(stream_chunk(request.model, completion_id, done=True))
                yield "data: [DONE]\n\n"
            except ProviderError as exc:
                error_chunk = {
                    "error": {
                        "message": str(exc),
                        "type": "provider_error",
                    }
                }
                yield _sse(error_chunk)
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    try:
        text = await complete_text(request, resolved)
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return JSONResponse(completion_payload(request.model, completion_id, text))


@app.websocket("/ws/rooms/{room_name}")
async def room_socket(websocket: WebSocket, room_name: str) -> None:
    if not collaboration_client_allowed(websocket):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Collaboration is limited to localhost or allowlisted client IPs.",
        )
        return
    normalized_room = normalize_room_name(room_name)
    username = normalize_room_name(websocket.query_params.get("name") or "guest", fallback="guest")
    history = await room_hub.connect(normalized_room, websocket)

    try:
        await websocket.send_json(
            {
                "type": "history",
                "room": normalized_room,
                "messages": history,
            }
        )
        await room_hub.append_and_broadcast(
            normalized_room,
            build_room_event(
                event_type="system",
                sender="system",
                speaker_type="system",
                content=f"{username} joined #{normalized_room}.",
            ),
        )

        while True:
            payload = await websocket.receive_json()
            if payload.get("type") != "chat":
                continue

            content = str(payload.get("content") or "").strip()
            if not content:
                continue

            agent_name = normalize_room_label(payload.get("agentName") or f"{username} ai", fallback=f"{username} ai")
            system_prompt = normalize_room_system_prompt(payload.get("systemPrompt"))
            model_id = str(payload.get("modelId") or DEFAULT_MODELS[0].id)
            temperature = clamp_float(payload.get("temperature"), default=0.7, minimum=0.0, maximum=2.0)
            max_tokens = clamp_int(payload.get("maxTokens"), default=512, minimum=64, maximum=4096)

            user_message = build_room_event(
                event_type="chat",
                sender=username,
                speaker_type="user",
                content=content,
                model_id=model_id,
            )
            await room_hub.append_and_broadcast(normalized_room, user_message)

            if mentions_ai(content):
                await room_hub.append_and_broadcast(
                    normalized_room,
                    build_room_event(
                        event_type="system",
                        sender="system",
                        speaker_type="system",
                        content=f"{agent_name} is replying with {model_id}.",
                        model_id=model_id,
                    ),
                )
                try:
                    ai_reply = await generate_room_ai_reply(
                        room_name=normalized_room,
                        requester_name=username,
                        agent_name=agent_name,
                        system_prompt=system_prompt,
                        model_id=model_id,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except ProviderError as exc:
                    await room_hub.append_and_broadcast(
                        normalized_room,
                        build_room_event(
                            event_type="system",
                            sender="system",
                            speaker_type="system",
                            content=f"@ai failed: {exc}",
                            model_id=model_id,
                        ),
                    )
                    continue

                await room_hub.append_and_broadcast(
                    normalized_room,
                    build_room_event(
                        event_type="chat",
                        sender=agent_name,
                        speaker_type="ai",
                        content=ai_reply,
                        model_id=model_id,
                    ),
                )
    except WebSocketDisconnect:
        pass
    finally:
        await room_hub.disconnect(normalized_room, websocket)
        await room_hub.append_and_broadcast(
            normalized_room,
            build_room_event(
                event_type="system",
                sender="system",
                speaker_type="system",
                content=f"{username} left #{normalized_room}.",
            ),
        )


@app.websocket("/ws/drafts/{draft_name}")
async def draft_socket(websocket: WebSocket, draft_name: str) -> None:
    if not collaboration_client_allowed(websocket):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Collaboration is limited to localhost or allowlisted client IPs.",
        )
        return
    normalized_draft = normalize_room_name(draft_name, fallback="paper")
    username = normalize_room_label(websocket.query_params.get("name") or "guest", fallback="guest")
    snapshot = await draft_hub.connect(normalized_draft, websocket, username)

    try:
        await websocket.send_json(
            {
                "type": "snapshot",
                "draft": normalized_draft,
                "content": snapshot["content"],
                "updatedAt": snapshot["updatedAt"],
                "collaborators": snapshot["collaborators"],
            }
        )
        await draft_hub.broadcast_presence(normalized_draft)

        while True:
            payload = await websocket.receive_json()
            event_type = str(payload.get("type") or "").strip().lower()

            if event_type == "presence":
                await draft_hub.update_presence(
                    normalized_draft,
                    websocket,
                    normalize_draft_presence_state(payload.get("state")),
                )
                continue

            if event_type != "sync":
                continue

            await draft_hub.sync_content(
                normalized_draft,
                websocket,
                sender_name=username,
                content=normalize_draft_content(payload.get("content")),
                state=normalize_draft_presence_state(payload.get("state"), fallback="editing"),
            )
    except WebSocketDisconnect:
        pass
    finally:
        await draft_hub.disconnect(normalized_draft, websocket)
        await draft_hub.broadcast_presence(normalized_draft)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def connection_host(connection: Request | WebSocket) -> str:
    forwarded = connection.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    client = connection.client
    return client.host if client else ""


def is_loopback_host(host: str) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.strip().lower() == "localhost"


def collaboration_client_allowed(connection: Request | WebSocket) -> bool:
    host = connection_host(connection)
    settings = get_settings()
    if is_loopback_host(host):
        return True
    if not settings.collaboration_allow_remote_clients:
        return False
    allowed_hosts = set(settings.collaboration_allowed_client_ips)
    return "*" in allowed_hosts or host in allowed_hosts


def ensure_collaboration_page_access(request: Request) -> None:
    host = connection_host(request)
    settings = get_settings()
    if is_loopback_host(host):
        return
    if settings.collaboration_allow_remote_pages and collaboration_client_allowed(request):
        return
    raise HTTPException(
        status_code=403,
        detail=(
            "Collaboration pages are only served to localhost by default. "
            "Remote collaborators should run LocalChat from source on their own machine "
            "and connect to your shared server IP."
        ),
    )


def build_room_event(
    *,
    event_type: str,
    sender: str,
    speaker_type: str,
    content: str,
    model_id: str = "",
) -> dict[str, Any]:
    return {
        "id": secrets.token_hex(10),
        "type": event_type,
        "sender": sender,
        "speakerType": speaker_type,
        "content": content,
        "modelId": model_id,
        "createdAt": int(time.time() * 1000),
    }


def normalize_room_name(value: str, fallback: str = "lobby") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip()).strip("-").lower()
    return cleaned[:40] or fallback


def normalize_room_label(value: Any, fallback: str = "Room AI") -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    cleaned = re.sub(r"[^a-zA-Z0-9 .:_-]+", "", cleaned)
    return cleaned[:48] or fallback


def normalize_room_system_prompt(value: Any) -> str:
    return str(value or "").strip()[:4000]


def normalize_draft_content(value: Any) -> str:
    return str(value or "")[:200000]


def normalize_draft_presence_state(value: Any, fallback: str = "viewing") -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"editing", "viewing", "idle", "reviewing"}:
        return candidate
    return fallback


def normalize_drafter_asset_name(value: Any) -> str:
    raw_name = Path(str(value or "")).name.strip()
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(raw_name).stem).strip(" ._-")
    suffix = Path(raw_name).suffix.lower()
    if not stem or not suffix:
        raise HTTPException(status_code=400, detail="Asset name must include a supported file extension.")
    if suffix not in DRAFTER_ALLOWED_IMAGE_EXTENSIONS | DRAFTER_ALLOWED_TEXT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported asset extension.")
    return f"{stem[:72]}{suffix}"


def drafter_asset_kind(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix in DRAFTER_ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if suffix == ".bib":
        return "bib"
    if suffix == ".tex":
        return "tex"
    return ""


def serialize_drafter_asset(path: Path) -> dict[str, Any]:
    stat = path.stat()
    kind = drafter_asset_kind(path.name)
    payload: dict[str, Any] = {
        "name": path.name,
        "kind": kind,
        "size": stat.st_size,
        "updatedAt": int(stat.st_mtime * 1000),
        "referencePath": f"drafter_uploads/{path.name}",
        "url": f"/assets/drafter_uploads/{quote(path.name)}",
    }
    if kind in {"bib", "tex"}:
        content = path.read_text(encoding="utf-8", errors="replace")
        payload["content"] = content
        if kind == "bib":
            payload["citationKeys"] = extract_bibtex_keys(content)
    return payload


def extract_bibtex_keys(content: str) -> list[str]:
    keys = []
    seen: set[str] = set()
    for match in re.finditer(r"@\w+\s*\{\s*([^,\s]+)", content):
        key = match.group(1).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys[:48]


def mentions_ai(value: str) -> bool:
    return bool(re.search(r"(?<!\w)@ai\b", value, flags=re.IGNORECASE))


def strip_ai_mentions(value: str) -> str:
    cleaned = re.sub(r"(?<!\w)@ai\b[:,]?\s*", "", value, flags=re.IGNORECASE).strip()
    return cleaned or "Respond to the latest chat room discussion."


def clamp_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(maximum, coerced))


def clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    return max(minimum, min(maximum, coerced))


def trim_room_context(messages: list[ChatMessage]) -> list[ChatMessage]:
    if not messages:
        return []

    selected: list[ChatMessage] = []
    char_count = 0
    for message in reversed(messages):
        message_cost = len(message.content) + 32
        if selected and char_count + message_cost > ROOM_CONTEXT_CHAR_BUDGET:
            break
        if len(selected) >= ROOM_CONTEXT_MESSAGE_LIMIT:
            break
        selected.insert(0, message)
        char_count += message_cost

    return selected or [messages[-1]]


def build_room_ai_messages(
    history: list[dict[str, Any]],
    *,
    requester_name: str,
    agent_name: str,
    system_prompt: str,
) -> list[ChatMessage]:
    transcript: list[ChatMessage] = []
    for item in history:
        if item.get("type") != "chat":
            continue
        sender = str(item.get("sender") or "guest")
        content = str(item.get("content") or "").strip()
        if not content:
            continue

        if item.get("speakerType") == "ai":
            transcript.append(ChatMessage(role="assistant", content=content))
            continue

        transcript.append(ChatMessage(role="user", content=f"{sender}: {strip_ai_mentions(content)}"))

    system_parts = [
        ROOM_AI_SYSTEM_PROMPT,
        f"You are {agent_name}, replying on behalf of {requester_name}.",
        "The transcript is shared across the room, so stay consistent with the ongoing conversation.",
    ]
    if system_prompt:
        system_parts.append(f"Additional instructions: {system_prompt}")

    trimmed = trim_room_context(transcript)
    return [ChatMessage(role="system", content=" ".join(system_parts)), *trimmed]


async def generate_room_ai_reply(
    *,
    room_name: str,
    requester_name: str,
    agent_name: str,
    system_prompt: str,
    model_id: str,
    temperature: float,
    max_tokens: int,
) -> str:
    history = await room_hub.snapshot(room_name)
    messages = build_room_ai_messages(
        history,
        requester_name=requester_name,
        agent_name=agent_name,
        system_prompt=system_prompt,
    )

    request = ChatCompletionRequest(
        model=model_id,
        messages=messages,
        stream=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    resolved = resolve_model(model_id)
    reply = await complete_text(request, resolved)
    cleaned = (reply or "").strip()
    return cleaned or "I did not have a useful reply for that."


def run() -> None:
    settings = get_settings()
    uvicorn.run("localchat.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
