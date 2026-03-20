from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
import ipaddress
import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request as urllib_request
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import get_model_catalog, get_settings
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
ROOM_STATE_PATH = BASE_DIR / "room_state.json"
ROOM_HISTORY_LIMIT = 120
ROOM_CONTEXT_MESSAGE_LIMIT = 18
ROOM_CONTEXT_CHAR_BUDGET = 16000
ROOM_CHAT_CONTENT_MAX_CHARS = 8000
ROOM_SYSTEM_MESSAGE_TTL_MS = 60_000
ROOM_SYSTEM_CLEANUP_INTERVAL_SECONDS = 1
ROOM_IMAGE_DATA_URL_MAX_CHARS = 2_000_000
ROOM_CHAT_ATTACHMENT_NAME_MAX_CHARS = 160
DRAFT_CHAT_HISTORY_LIMIT = 80
DRAFTER_TEXT_ASSET_LIMIT = 250_000
DRAFTER_IMAGE_ASSET_LIMIT = 3_500_000
HF_TTS_DEFAULT_MODEL = "microsoft/speecht5_tts"
HF_TTS_TEXT_CHAR_LIMIT = 1200
HF_TTS_MODEL_MAX_CHARS = 120
HF_TTS_VOICE_MAX_CHARS = 64
LLM_RESPONSE_LOG_PATH = BASE_DIR / "llm_responses.jsonl"
DRAFTER_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
DRAFTER_ALLOWED_TEXT_EXTENSIONS = {".bib", ".tex"}
DRAFTER_COMPILES_DIR = DOWNLOADS_DIR / "drafter_compiles"
DRAFTER_COMPILE_TIMEOUT_SECONDS = 45
DRAFTER_COMPILE_LOG_CHAR_LIMIT = 24_000
DRAFTER_COMPILE_HISTORY_LIMIT = 20
ROOM_UPLOADS_DIR = STATIC_DIR / "room_uploads"
ROOM_AI_SYSTEM_PROMPT = (
    "You are a participant-owned AI assistant inside a small multi-user chat room. "
    "Reply naturally to the room, keep answers concise, and use the recent chat context. "
    "If someone asks for code or technical help, be direct and practical."
)

app = FastAPI(title="Local Chat", version="0.1.0")
DRAFTER_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
DRAFTER_COMPILES_DIR.mkdir(parents=True, exist_ok=True)
ROOM_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
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
llm_response_log_lock = asyncio.Lock()


@app.on_event("startup")
async def startup_room_cleanup() -> None:
    app.state.room_system_cleanup_task = asyncio.create_task(expire_room_system_messages_loop())


@app.on_event("shutdown")
async def shutdown_room_cleanup() -> None:
    cleanup_task = getattr(app.state, "room_system_cleanup_task", None)
    if cleanup_task is None:
        return
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        return


def provider_error_status_code(message: str) -> int:
    normalized = message.lower()
    if "429" in message or "resource_exhausted" in normalized or "quota" in normalized or "rate limit" in normalized:
        return status.HTTP_429_TOO_MANY_REQUESTS
    if "401" in message or "unauthorized" in normalized or "invalid api key" in normalized:
        return status.HTTP_401_UNAUTHORIZED
    if "403" in message or "forbidden" in normalized:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


@dataclass
class RoomState:
    clients: set[WebSocket] = field(default_factory=set)
    history: list[dict[str, Any]] = field(default_factory=list)
    focus_mode: bool = False
    participants: dict[WebSocket, "RoomParticipant"] = field(default_factory=dict)


@dataclass
class RoomParticipant:
    participant_id: str
    username: str
    voice_enabled: bool = False
    mic_muted: bool = True


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
    chat_history: list[dict[str, Any]] = field(default_factory=list)


class RoomHub:
    def __init__(self) -> None:
        self._rooms: dict[str, RoomState] = self._load_rooms()
        self._lock = asyncio.Lock()

    async def connect(self, room_name: str, websocket: WebSocket, username: str) -> dict[str, Any]:
        await websocket.accept()
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.setdefault(room_name, RoomState())
            room.clients.add(websocket)
            participant_ids = {participant.participant_id for participant in room.participants.values()}
            participant_id = self._next_participant_id(participant_ids)
            room.participants[websocket] = RoomParticipant(
                participant_id=participant_id,
                username=username,
            )
            return {
                "messages": list(room.history),
                "focusMode": room.focus_mode,
                "participantId": participant_id,
                "participants": self._serialize_participants(room),
            }

    async def disconnect(self, room_name: str, websocket: WebSocket) -> RoomParticipant | None:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return None
            room.clients.discard(websocket)
            participant = room.participants.pop(websocket, None)
            if not room.clients and not room.history:
                self._rooms.pop(room_name, None)
            return participant

    async def snapshot(self, room_name: str) -> list[dict[str, Any]]:
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.get(room_name)
            return list(room.history) if room else []

    async def append_and_broadcast(self, room_name: str, message: dict[str, Any]) -> None:
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.setdefault(room_name, RoomState())
            message.setdefault("reactions", {})
            room.history.append(message)
            if len(room.history) > ROOM_HISTORY_LIMIT:
                room.history = room.history[-ROOM_HISTORY_LIMIT:]
            self._persist_locked()
            clients = list(room.clients)
        await self._broadcast_clients(room_name, clients, message)

    async def broadcast(self, room_name: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            room = self._rooms.setdefault(room_name, RoomState())
            clients = list(room.clients)
        await self._broadcast_clients(room_name, clients, payload)

    async def set_focus_mode(self, room_name: str, enabled: bool) -> bool:
        async with self._lock:
            room = self._rooms.setdefault(room_name, RoomState())
            if room.focus_mode == enabled:
                return False
            room.focus_mode = enabled
            self._persist_locked()
            return True

    async def participants_snapshot(self, room_name: str) -> list[dict[str, Any]]:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return []
            return self._serialize_participants(room)

    async def update_voice_state(
        self,
        room_name: str,
        websocket: WebSocket,
        *,
        voice_enabled: bool,
        mic_muted: bool,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return []
            participant = room.participants.get(websocket)
            if participant is None:
                return []
            participant.voice_enabled = voice_enabled
            participant.mic_muted = mic_muted if voice_enabled else True
            return self._serialize_participants(room)

    async def resolve_voice_target(
        self,
        room_name: str,
        source_socket: WebSocket,
        target_participant_id: str,
    ) -> tuple[WebSocket | None, RoomParticipant | None]:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return None, None
            source_participant = room.participants.get(source_socket)
            target_socket = None
            for socket, participant in room.participants.items():
                if participant.participant_id == target_participant_id:
                    target_socket = socket
                    break
            return target_socket, source_participant

    async def toggle_reaction(
        self,
        room_name: str,
        *,
        message_id: str,
        emoji: str,
        username: str,
    ) -> dict[str, dict[str, Any]] | None:
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.get(room_name)
            if room is None:
                return None
            for message in room.history:
                if str(message.get("id")) != message_id:
                    continue
                reactions = message.setdefault("reactions", {})
                reaction_state = reactions.get(emoji) or {"count": 0, "users": []}
                users = [str(item) for item in reaction_state.get("users", []) if str(item)]
                user_set = set(users)
                if username in user_set:
                    users = [item for item in users if item != username]
                else:
                    users.append(username)
                users.sort(key=str.lower)
                if users:
                    reactions[emoji] = {"count": len(users), "users": users}
                else:
                    reactions.pop(emoji, None)
                self._persist_locked()
                return reactions
        return None

    async def delete_message(self, room_name: str, message_id: str) -> bool:
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.get(room_name)
            if room is None:
                return False
            original_len = len(room.history)
            room.history = [item for item in room.history if str(item.get("id")) != message_id]
            deleted = len(room.history) < original_len
            if deleted:
                self._persist_locked()
            return deleted

    async def edit_message(
        self,
        room_name: str,
        *,
        message_id: str,
        username: str,
        content: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        async with self._lock:
            self._prune_expired_system_messages_locked()
            room = self._rooms.get(room_name)
            if room is None:
                return None, "not_found"
            for message in room.history:
                if str(message.get("id")) != message_id:
                    continue
                if str(message.get("speakerType") or "").lower() != "user":
                    return None, "forbidden"
                if str(message.get("sender") or "") != username:
                    return None, "forbidden"
                message["content"] = content
                message["editedAt"] = int(time.time() * 1000)
                self._persist_locked()
                return dict(message), None
        return None, "not_found"

    async def expire_system_messages(self) -> list[tuple[str, str]]:
        async with self._lock:
            return self._prune_expired_system_messages_locked()

    async def _broadcast_clients(self, room_name: str, clients: list[WebSocket], payload: dict[str, Any]) -> None:
        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)

        for client in stale_clients:
            await self.disconnect(room_name, client)

    def _serialize_participants(self, room: RoomState) -> list[dict[str, Any]]:
        participants = [
            {
                "participantId": participant.participant_id,
                "name": participant.username,
                "voiceEnabled": participant.voice_enabled,
                "micMuted": participant.mic_muted,
            }
            for participant in room.participants.values()
        ]
        participants.sort(key=lambda item: str(item["name"]).lower())
        return participants

    def _next_participant_id(self, taken_ids: set[str]) -> str:
        while True:
            candidate = secrets.token_hex(6)
            if candidate not in taken_ids:
                return candidate

    def _load_rooms(self) -> dict[str, RoomState]:
        if not ROOM_STATE_PATH.exists():
            return {}
        try:
            payload = json.loads(ROOM_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}

        rooms_payload = payload.get("rooms") if isinstance(payload, dict) else {}
        if not isinstance(rooms_payload, dict):
            return {}

        rooms: dict[str, RoomState] = {}
        for room_name, room_value in rooms_payload.items():
            normalized_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(room_name).strip()).strip("-").lower()[:40]
            if not normalized_name:
                continue
            if not isinstance(room_value, dict):
                continue
            raw_history = room_value.get("history")
            history = [item for item in raw_history if isinstance(item, dict)] if isinstance(raw_history, list) else []
            history = [
                item
                for item in history
                if not self._is_expired_system_message(item, int(time.time() * 1000))
            ]
            rooms[normalized_name] = RoomState(
                history=history[-ROOM_HISTORY_LIMIT:],
                focus_mode=bool(room_value.get("focusMode", False)),
            )
        return rooms

    def _persist_locked(self) -> None:
        serialized = {
            "rooms": {
                room_name: {
                    "focusMode": room.focus_mode,
                    "history": room.history[-ROOM_HISTORY_LIMIT:],
                }
                for room_name, room in self._rooms.items()
            }
        }
        try:
            ROOM_STATE_PATH.write_text(json.dumps(serialized, ensure_ascii=True, indent=2), encoding="utf-8")
        except OSError:
            return

    def _prune_expired_system_messages_locked(self, now_ms: int | None = None) -> list[tuple[str, str]]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        removed: list[tuple[str, str]] = []
        changed = False
        empty_rooms: list[str] = []

        for room_name, room in self._rooms.items():
            filtered_history: list[dict[str, Any]] = []
            room_changed = False
            for message in room.history:
                if self._is_expired_system_message(message, current_ms):
                    removed.append((room_name, str(message.get("id") or "")))
                    room_changed = True
                    continue
                filtered_history.append(message)
            if room_changed:
                room.history = filtered_history
                changed = True
            if not room.clients and not room.history:
                empty_rooms.append(room_name)

        for room_name in empty_rooms:
            self._rooms.pop(room_name, None)

        if changed or empty_rooms:
            self._persist_locked()
        return [(room_name, message_id) for room_name, message_id in removed if message_id]

    def _is_expired_system_message(self, message: dict[str, Any], now_ms: int) -> bool:
        if str(message.get("speakerType") or "").lower() != "system":
            return False
        created_at = self._coerce_int(
            message.get("createdAt"),
            default=now_ms,
            minimum=0,
            maximum=now_ms + ROOM_SYSTEM_MESSAGE_TTL_MS,
        )
        expires_at = self._coerce_int(
            message.get("expiresAt"),
            default=created_at + ROOM_SYSTEM_MESSAGE_TTL_MS,
            minimum=created_at,
            maximum=created_at + (ROOM_SYSTEM_MESSAGE_TTL_MS * 4),
        )
        return expires_at <= now_ms

    @staticmethod
    def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            numeric = int(default)
        if numeric < minimum:
            return minimum
        if numeric > maximum:
            return maximum
        return numeric


room_hub = RoomHub()


async def expire_room_system_messages_loop() -> None:
    try:
        while True:
            await asyncio.sleep(ROOM_SYSTEM_CLEANUP_INTERVAL_SECONDS)
            expired_entries = await room_hub.expire_system_messages()
            if not expired_entries:
                continue
            deleted_at = int(time.time() * 1000)
            for room_name, message_id in expired_entries:
                await room_hub.broadcast(
                    room_name,
                    {
                        "type": "message_deleted",
                        "messageId": message_id,
                        "deletedBy": "system",
                        "deletedAt": deleted_at,
                        "reason": "expired",
                    },
                )
    except asyncio.CancelledError:
        return


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
                "chatMessages": list(draft.chat_history),
            }

    async def disconnect(self, draft_name: str, websocket: WebSocket) -> None:
        async with self._lock:
            draft = self._drafts.get(draft_name)
            if draft is None:
                return
            draft.clients.pop(websocket, None)
            if not draft.clients and not draft.content and not draft.chat_history:
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

    async def append_chat_message(self, draft_name: str, *, sender_name: str, content: str) -> None:
        async with self._lock:
            draft = self._drafts.setdefault(draft_name, DraftState())
            message = {
                "id": secrets.token_hex(10),
                "sender": sender_name,
                "content": content,
                "createdAt": int(time.time() * 1000),
            }
            draft.chat_history.append(message)
            if len(draft.chat_history) > DRAFT_CHAT_HISTORY_LIMIT:
                draft.chat_history = draft.chat_history[-DRAFT_CHAT_HISTORY_LIMIT:]
            payload = {
                "type": "draft_chat",
                "draft": draft_name,
                "message": message,
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
            if not draft.clients and not draft.content and not draft.chat_history:
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
    has_openai = bool(settings.openai_api_key)
    has_anthropic = bool(settings.anthropic_api_key)

    if installed is None:
        installed = set()

    filtered = []
    for model in get_model_catalog():
        if model.provider == "huggingface":
            if has_huggingface:
                filtered.append(model)
            continue
        if model.provider == "gemini":
            if has_gemini:
                filtered.append(model)
            continue
        if model.provider == "openai":
            if has_openai:
                filtered.append(model)
            continue
        if model.provider == "anthropic":
            if has_anthropic:
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
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Collaboration is limited to localhost or allowlisted client IPs.",
        )
    assets = [
        serialize_drafter_asset(path)
        for path in sorted(DRAFTER_ASSETS_DIR.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and drafter_asset_kind(path.name)
    ]
    assets.sort(key=lambda asset: (-int(asset["updatedAt"]), str(asset["name"]).lower()))
    return assets


@app.post("/api/drafter/assets")
async def create_drafter_asset(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Collaboration is limited to localhost or allowlisted client IPs.",
        )
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
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Collaboration is limited to localhost or allowlisted client IPs.",
        )
    normalized_name = normalize_drafter_asset_name(asset_name)
    asset_path = DRAFTER_ASSETS_DIR / normalized_name
    if not asset_path.is_file() or not drafter_asset_kind(asset_path.name):
        raise HTTPException(status_code=404, detail="Asset not found.")
    asset_path.unlink(missing_ok=False)
    return {"status": "deleted", "name": normalized_name}


@app.post("/api/drafter/compile")
async def compile_drafter_paper(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Collaboration is limited to localhost or allowlisted client IPs.",
        )
    source = normalize_draft_content(payload.get("content"))
    if not source.strip():
        raise HTTPException(status_code=400, detail="Draft content is empty.")
    prefer_engine = str(payload.get("engine") or "").strip().lower()
    compile_result = await asyncio.to_thread(run_drafter_latex_compile, source, prefer_engine)
    return compile_result


@app.post("/api/rooms/{room_name}/attachments")
async def upload_room_attachments(
    request: Request,
    room_name: str,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Room uploads are limited to localhost or allowlisted client IPs.",
        )

    normalized_room = normalize_room_name(room_name, fallback="lobby")
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="At least one attachment is required.")

    room_dir = ROOM_UPLOADS_DIR / normalized_room
    room_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, Any]] = []

    for upload in files:
        normalized_name = normalize_room_attachment_name(upload.filename)
        stored_name = f"{int(time.time() * 1000)}-{secrets.token_hex(6)}-{normalized_name}"
        destination = room_dir / stored_name
        size = await write_upload_to_disk(upload, destination, max_bytes=None)
        mime_type = str(upload.content_type or "").strip()[:120]
        attachment_type = room_attachment_type_from_name_or_mime(normalized_name, mime_type)
        url = f"/assets/room_uploads/{quote(normalized_room)}/{quote(stored_name)}"
        uploaded.append(
            {
                "type": attachment_type,
                "name": normalized_name,
                "url": url,
                "size": size,
                "mimeType": mime_type,
            }
        )

    return {
        "room": normalized_room,
        "attachments": uploaded,
    }


@app.post("/api/rooms/{room_name}/pictochat")
async def create_room_pictochat(request: Request, room_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Room uploads are limited to localhost or allowlisted client IPs.",
        )

    normalized_room = normalize_room_name(room_name, fallback="lobby")
    normalized_title = normalize_room_label((payload or {}).get("title") or "Pictochat", fallback="Pictochat")
    board_id = secrets.token_hex(5)
    room_dir = ROOM_UPLOADS_DIR / normalized_room
    room_dir.mkdir(parents=True, exist_ok=True)
    normalized_name = normalize_room_attachment_name(f"{normalized_title}.pictochat.html")
    stored_name = f"{int(time.time() * 1000)}-{board_id}-{normalized_name}"
    destination = room_dir / stored_name
    html_content = build_pictochat_html(title=normalized_title, board_id=board_id)
    destination.write_text(html_content, encoding="utf-8")
    size = destination.stat().st_size

    url = f"/assets/room_uploads/{quote(normalized_room)}/{quote(stored_name)}"
    attachment = {
        "type": "file",
        "name": normalized_name,
        "url": url,
        "size": size,
        "mimeType": "text/html",
    }
    return {
        "room": normalized_room,
        "attachment": attachment,
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/provider-health/google")
async def google_provider_health(model: str = "gemini:gemini-2.5-flash") -> dict[str, Any]:
    started_at = int(time.time() * 1000)
    settings = get_settings()
    if not settings.gemini_api_key:
        return {
            "provider": "google",
            "status": "not_configured",
            "model": model,
            "checkedAt": started_at,
            "detail": "GEMINI_API_KEY is missing in .env",
        }

    try:
        resolved = resolve_model(model)
        if resolved.provider != "gemini":
            raise ProviderError("Requested model is not a Gemini model.")
        probe_request = ChatCompletionRequest(
            model=model,
            stream=False,
            temperature=0.0,
            max_tokens=24,
            messages=[ChatMessage(role="user", content="Reply with exactly: OK")],
        )
        text = await asyncio.wait_for(complete_text(probe_request, resolved), timeout=20)
        duration_ms = int(time.time() * 1000) - started_at
        return {
            "provider": "google",
            "status": "ok",
            "model": model,
            "checkedAt": started_at,
            "durationMs": duration_ms,
            "responsePreview": _truncate_for_log(text, 180),
        }
    except Exception as exc:  # pragma: no cover - network/provider failure path
        duration_ms = int(time.time() * 1000) - started_at
        return {
            "provider": "google",
            "status": "error",
            "model": model,
            "checkedAt": started_at,
            "durationMs": duration_ms,
            "detail": str(exc),
        }


@app.get("/api/models", response_model=list[ModelResponse])
async def api_models() -> list[ModelResponse]:
    return [
        ModelResponse(
            id=model.id,
            label=model.label,
            provider=model.provider,
            description=model.description,
            remote=model.remote,
            default_temperature=model.default_temperature,
            default_max_tokens=model.default_max_tokens,
            provider_options=model.provider_options,
        )
        for model in visible_models()
    ]


@app.get("/api/client/runtime")
async def client_runtime() -> dict[str, str]:
    settings = get_settings()
    return {"ollamaBaseUrl": settings.ollama_base_url}


@app.post("/api/tts/huggingface")
async def huggingface_tts(request: Request, payload: dict[str, Any]) -> StreamingResponse:
    if not collaboration_client_allowed(request):
        raise HTTPException(
            status_code=403,
            detail="Voice reader requests are limited to localhost or allowlisted client IPs.",
        )

    settings = get_settings()
    if not settings.huggingface_api_key:
        raise HTTPException(status_code=400, detail="HUGGINGFACE_API_KEY is required for voice reader.")

    text = normalize_hf_tts_text(payload.get("text"))
    if not text:
        raise HTTPException(status_code=400, detail="Voice reader text is empty.")

    model_id = normalize_hf_tts_model(payload.get("modelId"))
    voice = normalize_hf_tts_voice(payload.get("voice"))

    try:
        audio_bytes, media_type = await asyncio.to_thread(
            request_huggingface_tts_audio,
            api_key=settings.huggingface_api_key,
            model_id=model_id,
            text=text,
            voice=voice,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return StreamingResponse(
        iter([audio_bytes]),
        media_type=media_type,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


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
        raise HTTPException(status_code=provider_error_status_code(str(exc)), detail=str(exc)) from exc

    completion_id = f"chatcmpl_{secrets.token_hex(12)}"

    if request.stream:
        async def event_stream():
            chunks: list[str] = []
            try:
                yield _sse(stream_chunk(request.model, completion_id))
                async for text in stream_text(request, resolved):
                    chunks.append(text)
                    yield _sse(stream_chunk(request.model, completion_id, text))
                await append_llm_response_log(
                    completion_id=completion_id,
                    request=request,
                    resolved=resolved,
                    response_text="".join(chunks),
                )
                yield _sse(stream_chunk(request.model, completion_id, done=True))
                yield "data: [DONE]\n\n"
            except ProviderError as exc:
                await append_llm_response_log(
                    completion_id=completion_id,
                    request=request,
                    resolved=resolved,
                    response_text="".join(chunks),
                    error=str(exc),
                )
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
        await append_llm_response_log(
            completion_id=completion_id,
            request=request,
            resolved=resolved,
            response_text="",
            error=str(exc),
        )
        raise HTTPException(status_code=provider_error_status_code(str(exc)), detail=str(exc)) from exc

    await append_llm_response_log(
        completion_id=completion_id,
        request=request,
        resolved=resolved,
        response_text=text,
    )
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
    snapshot = await room_hub.connect(normalized_room, websocket, username=username)
    pending_ai_requests: dict[str, dict[str, str]] = {}

    try:
        await websocket.send_json(
            {
                "type": "history",
                "room": normalized_room,
                "messages": snapshot["messages"],
                "focusMode": bool(snapshot.get("focusMode")),
                "canDeleteMessages": can_manage_room_messages(websocket),
                "participantId": snapshot.get("participantId"),
                "participants": snapshot.get("participants", []),
            }
        )
        await room_hub.broadcast(
            normalized_room,
            {
                "type": "voice_participants",
                "participants": await room_hub.participants_snapshot(normalized_room),
                "updatedBy": username,
                "updatedAt": int(time.time() * 1000),
            },
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
            event_type = str(payload.get("type") or "").strip().lower()

            if event_type == "reaction_toggle":
                message_id = str(payload.get("messageId") or "").strip()
                emoji = normalize_reaction_emoji(payload.get("emoji"))
                if not message_id or not emoji:
                    continue
                reactions = await room_hub.toggle_reaction(
                    normalized_room,
                    message_id=message_id,
                    emoji=emoji,
                    username=username,
                )
                if reactions is None:
                    continue
                await room_hub.broadcast(
                    normalized_room,
                    {
                        "type": "reaction_update",
                        "messageId": message_id,
                        "reactions": reactions,
                        "updatedBy": username,
                        "updatedAt": int(time.time() * 1000),
                    },
                )
                continue

            if event_type == "delete_message":
                if not can_manage_room_messages(websocket):
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": "You are not allowed to delete messages in this room.",
                        }
                    )
                    continue
                message_id = str(payload.get("messageId") or "").strip()
                if not message_id:
                    continue
                deleted = await room_hub.delete_message(normalized_room, message_id)
                if not deleted:
                    continue
                await room_hub.broadcast(
                    normalized_room,
                    {
                        "type": "message_deleted",
                        "messageId": message_id,
                        "deletedBy": username,
                        "deletedAt": int(time.time() * 1000),
                    },
                )
                continue

            if event_type == "edit_message":
                message_id = str(payload.get("messageId") or "").strip()
                content = normalize_room_message_content(payload.get("content"))
                if not message_id:
                    continue
                if not content:
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": "Message content cannot be empty.",
                        }
                    )
                    continue
                updated_message, edit_error = await room_hub.edit_message(
                    normalized_room,
                    message_id=message_id,
                    username=username,
                    content=content,
                )
                if edit_error == "forbidden":
                    await websocket.send_json(
                        {
                            "type": "error",
                            "detail": "You can only edit your own user messages.",
                        }
                    )
                    continue
                if updated_message is None:
                    continue
                await room_hub.broadcast(
                    normalized_room,
                    {
                        "type": "message_edited",
                        "messageId": message_id,
                        "content": str(updated_message.get("content") or ""),
                        "editedBy": username,
                        "editedAt": int(updated_message.get("editedAt") or int(time.time() * 1000)),
                    },
                )
                continue

            if event_type == "focus_mode":
                enabled = bool(payload.get("enabled"))
                changed = await room_hub.set_focus_mode(normalized_room, enabled)
                if not changed:
                    continue
                await room_hub.broadcast(
                    normalized_room,
                    {
                        "type": "focus_mode",
                        "enabled": enabled,
                        "updatedBy": username,
                        "updatedAt": int(time.time() * 1000),
                    },
                )
                continue

            if event_type == "voice_state":
                participants = await room_hub.update_voice_state(
                    normalized_room,
                    websocket,
                    voice_enabled=bool(payload.get("enabled")),
                    mic_muted=bool(payload.get("muted")),
                )
                await room_hub.broadcast(
                    normalized_room,
                    {
                        "type": "voice_participants",
                        "participants": participants,
                        "updatedBy": username,
                        "updatedAt": int(time.time() * 1000),
                    },
                )
                continue

            if event_type == "voice_signal":
                target_participant_id = str(payload.get("targetParticipantId") or "").strip()
                signal_payload = payload.get("signal")
                if not target_participant_id or not isinstance(signal_payload, dict):
                    continue
                target_socket, source_participant = await room_hub.resolve_voice_target(
                    normalized_room,
                    websocket,
                    target_participant_id,
                )
                if target_socket is None or source_participant is None:
                    continue
                try:
                    await target_socket.send_json(
                        {
                            "type": "voice_signal",
                            "fromParticipantId": source_participant.participant_id,
                            "fromName": source_participant.username,
                            "signal": signal_payload,
                            "sentAt": int(time.time() * 1000),
                        }
                    )
                except Exception:
                    pass
                continue

            if event_type == "ai_result":
                request_id = str(payload.get("requestId") or "").strip()
                pending = pending_ai_requests.pop(request_id, None)
                if pending is None:
                    continue

                resolved_model_id = str(payload.get("modelId") or pending["model_id"])
                error_text = str(payload.get("error") or "").strip()
                if error_text:
                    await room_hub.append_and_broadcast(
                        normalized_room,
                        build_room_event(
                            event_type="system",
                            sender="system",
                            speaker_type="system",
                            content=f"@ai failed: {error_text}",
                            model_id=resolved_model_id,
                        ),
                    )
                    continue

                ai_reply = str(payload.get("content") or "").strip() or "I did not have a useful reply for that."
                reply_sender = normalize_room_label(
                    payload.get("agentName") or pending["agent_name"],
                    fallback=pending["agent_name"],
                )
                await room_hub.append_and_broadcast(
                    normalized_room,
                    build_room_event(
                        event_type="chat",
                        sender=reply_sender,
                        speaker_type="ai",
                        content=ai_reply,
                        model_id=resolved_model_id,
                    ),
                )
                continue

            if event_type != "chat":
                continue

            message_type = str(payload.get("messageType") or "text").strip().lower()
            content = normalize_room_message_content(payload.get("content"))
            image_data_url = normalize_room_image_data_url(payload.get("imageData"))
            image_name = normalize_room_image_name(payload.get("imageName"))
            attachments = normalize_room_chat_attachments(payload.get("attachments"))
            if image_data_url:
                attachments.insert(
                    0,
                    {
                        "type": "image",
                        "name": image_name,
                        "dataUrl": image_data_url,
                        "size": 0,
                        "mimeType": "image/*",
                    },
                )
            if not content and not attachments:
                continue

            agent_name = normalize_room_label(payload.get("agentName") or f"{username} ai", fallback=f"{username} ai")
            system_prompt = normalize_room_system_prompt(payload.get("systemPrompt"))
            default_model_id = get_model_catalog()[0].id if get_model_catalog() else "ollama:qwen2.5:7b"
            model_id = str(payload.get("modelId") or default_model_id)
            temperature = clamp_float(payload.get("temperature"), default=0.7, minimum=0.0, maximum=2.0)
            max_tokens = clamp_int(payload.get("maxTokens"), default=512, minimum=64, maximum=4096)
            provider_options = payload.get("providerOptions") if isinstance(payload.get("providerOptions"), dict) else {}
            fallback_route = {
                "trigger": "ai",
                "agent_name": agent_name,
                "system_prompt": system_prompt,
                "model_id": model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "provider_options": provider_options,
                "context_mode": "room",
            }

            user_message = build_room_event(
                event_type="chat",
                sender=username,
                speaker_type="user",
                content=content,
                model_id=model_id,
                message_type=(
                    "image"
                    if any(str(item.get("type") or "").lower() == "image" for item in attachments)
                    else message_type
                ),
                attachments=attachments,
            )
            await room_hub.append_and_broadcast(normalized_room, user_message)

            selected_ai_route = select_room_ai_route(
                content,
                payload.get("aiRouting"),
                fallback_route=fallback_route,
            )
            if content and selected_ai_route:
                request_id = secrets.token_hex(8)
                history = await room_hub.snapshot(normalized_room)
                selected_trigger = str(selected_ai_route.get("trigger") or "ai")
                direct_prompt = extract_agent_prompt_from_mention(content, selected_trigger)
                ai_messages = build_room_ai_messages(
                    history,
                    requester_name=username,
                    agent_name=str(selected_ai_route.get("agent_name") or agent_name),
                    system_prompt=str(selected_ai_route.get("system_prompt") or ""),
                    context_mode=str(selected_ai_route.get("context_mode") or "room"),
                    direct_prompt=direct_prompt,
                )
                pending_ai_requests[request_id] = {
                    "agent_name": str(selected_ai_route.get("agent_name") or agent_name),
                    "model_id": str(selected_ai_route.get("model_id") or model_id),
                }
                await room_hub.append_and_broadcast(
                    normalized_room,
                    build_room_event(
                        event_type="system",
                        sender="system",
                        speaker_type="system",
                        content=(
                            f"{str(selected_ai_route.get('agent_name') or agent_name)} "
                            f"is generating a local reply with {str(selected_ai_route.get('model_id') or model_id)}."
                        ),
                        model_id=str(selected_ai_route.get("model_id") or model_id),
                    ),
                )
                await websocket.send_json(
                    {
                        "type": "ai_request",
                        "requestId": request_id,
                        "room": normalized_room,
                        "requester": username,
                        "agentName": str(selected_ai_route.get("agent_name") or agent_name),
                        "modelId": str(selected_ai_route.get("model_id") or model_id),
                        "temperature": selected_ai_route.get("temperature", temperature),
                        "maxTokens": selected_ai_route.get("max_tokens", max_tokens),
                        "providerOptions": selected_ai_route.get("provider_options", provider_options),
                        "messages": [message.model_dump() for message in ai_messages],
                    }
                )
    except WebSocketDisconnect:
        pass
    finally:
        departed_participant = await room_hub.disconnect(normalized_room, websocket)
        await room_hub.broadcast(
            normalized_room,
            {
                "type": "voice_participants",
                "participants": await room_hub.participants_snapshot(normalized_room),
                "updatedBy": username,
                "updatedAt": int(time.time() * 1000),
            },
        )
        if departed_participant is not None:
            await room_hub.broadcast(
                normalized_room,
                {
                    "type": "voice_participant_left",
                    "participantId": departed_participant.participant_id,
                    "name": departed_participant.username,
                    "updatedAt": int(time.time() * 1000),
                },
            )
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
                "chatMessages": snapshot["chatMessages"],
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

            if event_type == "draft_chat":
                chat_text = normalize_draft_chat_content(payload.get("content"))
                if not chat_text:
                    continue
                await draft_hub.append_chat_message(
                    normalized_draft,
                    sender_name=username,
                    content=chat_text,
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


def _truncate_for_log(value: Any, limit: int = 1800) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    remaining = len(text) - limit
    return f"{text[:limit]}...[truncated {remaining} chars]"


def build_request_log_messages(messages: list[ChatMessage]) -> list[dict[str, str]]:
    recent = messages[-24:] if len(messages) > 24 else messages
    return [
        {
            "role": message.role,
            "content": _truncate_for_log(message.content),
        }
        for message in recent
    ]


async def append_llm_response_log(
    *,
    completion_id: str,
    request: ChatCompletionRequest,
    resolved: Any,
    response_text: str,
    error: str = "",
) -> None:
    entry = {
        "timestampMs": int(time.time() * 1000),
        "timestampUtc": datetime.now(timezone.utc).isoformat(),
        "completionId": completion_id,
        "provider": getattr(resolved, "provider", ""),
        "model": request.model,
        "upstreamModel": getattr(resolved, "upstream_model", ""),
        "stream": bool(request.stream),
        "temperature": request.temperature,
        "maxTokens": request.max_tokens,
        "messageCount": len(request.messages),
        "messages": build_request_log_messages(request.messages),
        "response": {
            "content": response_text,
            "chars": len(response_text),
        },
        "success": not bool(error),
        "error": error,
    }
    serialized = json.dumps(entry, ensure_ascii=False)
    async with llm_response_log_lock:
        try:
            with LLM_RESPONSE_LOG_PATH.open("a", encoding="utf-8") as file_handle:
                file_handle.write(serialized)
                file_handle.write("\n")
        except OSError:
            return


def request_huggingface_tts_audio(
    *,
    api_key: str,
    model_id: str,
    text: str,
    voice: str = "",
) -> tuple[bytes, str]:
    endpoint = f"https://router.huggingface.co/hf-inference/models/{quote(model_id, safe='')}"
    payload: dict[str, Any] = {
        "text_inputs": text,
    }
    parameters: dict[str, Any] = {}
    if voice:
        parameters["voice"] = voice
    if parameters:
        payload["parameters"] = parameters

    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    request_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "audio/mpeg, audio/wav, audio/*, application/json",
    }
    response_body = b""
    response_type = "application/octet-stream"
    max_attempts = 3
    for attempt in range(max_attempts):
        request_obj = urllib_request.Request(
            endpoint,
            data=body,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib_request.urlopen(request_obj, timeout=90) as response:
                response_body = response.read()
                response_type = response.headers.get_content_type() or "application/octet-stream"
                break
        except error.HTTPError as exc:
            retry_after = _hf_tts_retry_after_seconds(exc)
            if retry_after > 0 and attempt < max_attempts - 1:
                time.sleep(retry_after)
                continue
            detail = _parse_hf_tts_error(exc)
            raise RuntimeError(detail) from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Hugging Face TTS request failed: {exc}") from exc

    if not response_body:
        raise RuntimeError("Hugging Face TTS returned empty audio.")

    if response_type.startswith("application/json"):
        detail = _extract_hf_tts_error_message(response_body) or "Hugging Face TTS returned JSON instead of audio."
        raise RuntimeError(detail)

    if not response_type.startswith("audio/"):
        raise RuntimeError(f"Hugging Face TTS returned unsupported media type: {response_type}")

    return response_body, response_type


def _parse_hf_tts_error(exc: error.HTTPError) -> str:
    status_code = getattr(exc, "code", 0)
    response_body = b""
    try:
        response_body = exc.read()
    except OSError:
        response_body = b""
    detail = _extract_hf_tts_error_message(response_body) if response_body else ""
    if not detail:
        detail = f"Hugging Face TTS request failed ({status_code})."
    if status_code == 401:
        return "Hugging Face TTS unauthorized. Check HUGGINGFACE_API_KEY."
    if status_code == 410:
        return (
            "This TTS model is deprecated or not served by hf-inference. "
            "Try microsoft/speecht5_tts or another model currently available in HF Inference."
        )
    if status_code == 429:
        return "Hugging Face TTS rate limited this request."
    return detail


def _hf_tts_retry_after_seconds(exc: error.HTTPError) -> int:
    status_code = getattr(exc, "code", 0)
    if status_code != 503:
        return 0
    response_body = b""
    try:
        response_body = exc.read()
    except OSError:
        response_body = b""
    parsed = _parse_hf_tts_error_payload(response_body)
    if not parsed:
        return 2
    estimated = parsed.get("estimated_time")
    if isinstance(estimated, (int, float)):
        return max(1, min(15, int(estimated) + 1))
    message = str(parsed.get("error") or parsed.get("detail") or "").lower()
    if "loading" in message or "currently loading" in message:
        return 3
    return 0


def _parse_hf_tts_error_payload(raw_payload: bytes) -> dict[str, Any]:
    if not raw_payload:
        return {}
    try:
        parsed = json.loads(raw_payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _extract_hf_tts_error_message(raw_payload: bytes) -> str:
    parsed = _parse_hf_tts_error_payload(raw_payload)
    if parsed:
        if isinstance(parsed.get("error"), str):
            return parsed["error"][:300]
        detail = parsed.get("detail")
        if isinstance(detail, str):
            return detail[:300]
    return ""


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
    if not allowed_hosts:
        return True
    return "*" in allowed_hosts or host in allowed_hosts


def can_manage_room_messages(connection: Request | WebSocket) -> bool:
    host = connection_host(connection)
    if is_loopback_host(host):
        return True
    settings = get_settings()
    allowed_hosts = set(settings.collaboration_allowed_client_ips)
    if settings.collaboration_allow_remote_clients and not allowed_hosts:
        return True
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
    message_type: str = "text",
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    created_at = int(time.time() * 1000)
    message = {
        "id": secrets.token_hex(10),
        "type": event_type,
        "sender": sender,
        "speakerType": speaker_type,
        "content": content,
        "modelId": model_id,
        "messageType": message_type if message_type in {"text", "image", "file"} else "text",
        "attachments": [item for item in (attachments or []) if isinstance(item, dict)],
        "createdAt": created_at,
    }
    if str(speaker_type).lower() == "system":
        message["expiresAt"] = created_at + ROOM_SYSTEM_MESSAGE_TTL_MS
    return message


def normalize_room_name(value: str, fallback: str = "lobby") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", (value or "").strip()).strip("-").lower()
    return cleaned[:40] or fallback


def normalize_room_label(value: Any, fallback: str = "Room AI") -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    cleaned = re.sub(r"[^a-zA-Z0-9 .:_-]+", "", cleaned)
    return cleaned[:48] or fallback


def normalize_room_system_prompt(value: Any) -> str:
    return str(value or "").strip()[:4000]


def normalize_room_message_content(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized[:ROOM_CHAT_CONTENT_MAX_CHARS]


def normalize_hf_tts_text(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "")).strip()
    return normalized[:HF_TTS_TEXT_CHAR_LIMIT]


def normalize_hf_tts_model(value: Any) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "").strip())
    if not cleaned:
        return HF_TTS_DEFAULT_MODEL
    normalized = re.sub(r"[^a-zA-Z0-9._/-]+", "", cleaned)
    if normalized.lower() == "hexgrad/kokoro-82m":
        return HF_TTS_DEFAULT_MODEL
    return normalized[:HF_TTS_MODEL_MAX_CHARS] or HF_TTS_DEFAULT_MODEL


def normalize_hf_tts_voice(value: Any) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "").strip())
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "", cleaned)
    return normalized[:HF_TTS_VOICE_MAX_CHARS]


def normalize_reaction_emoji(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"\s+", "", candidate)
    return candidate[:16]


def normalize_room_image_name(value: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-")
    return cleaned[:72] or "shared-image"


def normalize_room_image_data_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if len(candidate) > ROOM_IMAGE_DATA_URL_MAX_CHARS:
        return ""
    pattern = re.compile(r"^data:image\/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+$", flags=re.IGNORECASE)
    if not pattern.match(candidate):
        return ""
    return candidate


def normalize_room_attachment_name(value: Any) -> str:
    raw_name = Path(str(value or "")).name.strip()
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip(" ._-")
    return cleaned[:ROOM_CHAT_ATTACHMENT_NAME_MAX_CHARS] or "shared-file"


def normalize_room_attachment_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 600:
        return ""
    if ".." in candidate:
        return ""
    if candidate.startswith("/"):
        if re.match(r"^/assets/room_uploads/[A-Za-z0-9._%/\-]+$", candidate):
            return candidate
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return ""
    if not parsed.netloc:
        return ""
    if not re.match(r"^/assets/room_uploads/[A-Za-z0-9._%/\-]+$", parsed.path or ""):
        return ""
    return candidate


def room_attachment_type_from_name_or_mime(name: str, mime_type: str) -> str:
    mime = str(mime_type or "").strip().lower()
    if mime.startswith("image/"):
        return "image"
    if Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}:
        return "image"
    return "file"


def normalize_room_chat_attachments(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        url = normalize_room_attachment_url(item.get("url"))
        if not url:
            continue
        name = normalize_room_attachment_name(item.get("name"))
        mime_type = str(item.get("mimeType") or "").strip()[:120]
        normalized.append(
            {
                "type": room_attachment_type_from_name_or_mime(name, mime_type),
                "name": name,
                "url": url,
                "size": max(0, clamp_int(item.get("size"), default=0, minimum=0, maximum=9_223_372_036_854_775_807)),
                "mimeType": mime_type,
            }
        )
    return normalized


def build_pictochat_html(*, title: str, board_id: str) -> str:
    safe_title = re.sub(r"[<>&]", "", title).strip() or "Pictochat"
    board_label = re.sub(r"[^a-zA-Z0-9_-]+", "", board_id)[:16] or "board"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f4f7ff;
      --panel: #ffffff;
      --ink: #1c2552;
      --line: #2a3e82;
      --accent: #0f9d58;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Trebuchet MS", Tahoma, sans-serif;
      background: linear-gradient(180deg, #eef3ff 0%, #e0ebff 100%);
      color: var(--ink);
    }}
    .shell {{
      display: grid;
      gap: 10px;
      padding: 10px;
    }}
    .header {{
      border: 2px solid var(--line);
      background: var(--panel);
      padding: 8px;
      font-weight: 800;
      letter-spacing: 0.02em;
    }}
    .layout {{
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(0, 1fr) 220px;
    }}
    .card {{
      border: 2px solid var(--line);
      background: var(--panel);
      padding: 8px;
    }}
    .tools {{
      display: grid;
      gap: 6px;
    }}
    .tools button {{
      padding: 7px 10px;
      border: 2px solid var(--line);
      background: linear-gradient(180deg, #ffffff 0%, #deebff 100%);
      color: var(--ink);
      font-weight: 700;
      cursor: pointer;
    }}
    .tools button.active {{
      background: linear-gradient(180deg, #ccffdd 0%, #a6f1be 100%);
      border-color: #0d7a42;
    }}
    .tools input {{
      width: 100%;
    }}
    canvas {{
      display: block;
      width: 100%;
      min-height: 280px;
      border: 2px solid var(--line);
      background: #ffffff;
      touch-action: none;
      cursor: crosshair;
    }}
    .chat-log {{
      display: grid;
      gap: 6px;
      max-height: 180px;
      overflow: auto;
      border: 2px solid var(--line);
      padding: 6px;
      background: #f9fbff;
    }}
    .chat-line {{
      border: 1px solid #b8c8ff;
      padding: 5px;
      background: #ffffff;
      font-size: 0.88rem;
    }}
    .chat-compose {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 6px;
      margin-top: 6px;
    }}
    .chat-compose input {{
      padding: 7px 8px;
      border: 2px solid var(--line);
    }}
    .chat-compose button {{
      padding: 7px 10px;
      border: 2px solid var(--line);
      background: linear-gradient(180deg, #dbffe9 0%, #bcf8cf 100%);
      color: #0b5a31;
      font-weight: 800;
      cursor: pointer;
    }}
    .hint {{
      font-size: 0.78rem;
      color: #3b4b82;
    }}
    @media (max-width: 760px) {{
      .layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">{safe_title} :: Board {board_label}</div>
    <div class="layout">
      <section class="card">
        <canvas id="pictochat-canvas" width="920" height="460"></canvas>
        <div class="hint">Draw anything. This board is local to this file view.</div>
      </section>
      <aside class="card">
        <div class="tools">
          <button type="button" data-color="#1c2552" class="active">Ink</button>
          <button type="button" data-color="#db2e79">Pink</button>
          <button type="button" data-color="#0f9d58">Green</button>
          <button type="button" data-color="#ca8a04">Gold</button>
          <button type="button" data-color="#ffffff">Eraser</button>
          <label>
            Brush
            <input id="brush-size" type="range" min="1" max="30" step="1" value="4">
          </label>
          <button id="clear-canvas" type="button">Clear Canvas</button>
        </div>
      </aside>
    </div>

    <section class="card">
      <strong>Pictochat Notes</strong>
      <div id="chat-log" class="chat-log"></div>
      <div class="chat-compose">
        <input id="chat-input" type="text" maxlength="220" placeholder="Write a note about this board...">
        <button id="chat-send" type="button">Post</button>
      </div>
    </section>
  </div>

  <script>
    (function () {{
      const canvas = document.getElementById("pictochat-canvas");
      const context = canvas.getContext("2d");
      const brushSizeInput = document.getElementById("brush-size");
      const colorButtons = Array.from(document.querySelectorAll("[data-color]"));
      const clearButton = document.getElementById("clear-canvas");
      const chatLog = document.getElementById("chat-log");
      const chatInput = document.getElementById("chat-input");
      const chatSend = document.getElementById("chat-send");

      let drawing = false;
      let color = "#1c2552";
      let brushSize = Number(brushSizeInput.value || 4);

      function setColor(next) {{
        color = next;
        colorButtons.forEach((button) => button.classList.toggle("active", button.dataset.color === next));
      }}

      function toLocalPoint(event) {{
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        return {{
          x: (event.clientX - rect.left) * scaleX,
          y: (event.clientY - rect.top) * scaleY,
        }};
      }}

      function start(event) {{
        drawing = true;
        const point = toLocalPoint(event);
        context.beginPath();
        context.moveTo(point.x, point.y);
      }}

      function move(event) {{
        if (!drawing) {{
          return;
        }}
        const point = toLocalPoint(event);
        context.lineWidth = brushSize;
        context.lineCap = "round";
        context.lineJoin = "round";
        context.strokeStyle = color;
        context.lineTo(point.x, point.y);
        context.stroke();
      }}

      function stop() {{
        drawing = false;
        context.closePath();
      }}

      function appendChatLine(text) {{
        const line = document.createElement("div");
        line.className = "chat-line";
        line.textContent = text;
        chatLog.append(line);
        chatLog.scrollTop = chatLog.scrollHeight;
      }}

      function sendChatLine() {{
        const value = String(chatInput.value || "").trim();
        if (!value) {{
          return;
        }}
        appendChatLine(value);
        chatInput.value = "";
      }}

      canvas.addEventListener("pointerdown", start);
      canvas.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
      canvas.addEventListener("pointerleave", stop);
      brushSizeInput.addEventListener("input", () => {{
        brushSize = Number(brushSizeInput.value || 4);
      }});
      colorButtons.forEach((button) => {{
        button.addEventListener("click", () => setColor(button.dataset.color || "#1c2552"));
      }});
      clearButton.addEventListener("click", () => {{
        context.clearRect(0, 0, canvas.width, canvas.height);
      }});
      chatSend.addEventListener("click", sendChatLine);
      chatInput.addEventListener("keydown", (event) => {{
        if (event.key === "Enter") {{
          event.preventDefault();
          sendChatLine();
        }}
      }});

      appendChatLine("Pictochat ready. Draw and drop quick notes here.");
    }})();
  </script>
</body>
</html>
"""


async def write_upload_to_disk(upload: UploadFile, destination: Path, *, max_bytes: int | None) -> int:
    total = 0
    try:
        with destination.open("wb") as file_handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Attachment exceeds {max_bytes} bytes ({upload.filename or 'file'}).",
                    )
                file_handle.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save uploaded attachment.") from exc
    finally:
        await upload.close()
    return total


def _truncate_compile_log(text: str, *, limit: int = DRAFTER_COMPILE_LOG_CHAR_LIMIT) -> str:
    if len(text) <= limit:
        return text
    overflow = len(text) - limit
    return f"{text[:limit]}\n...[truncated {overflow} chars]"


def _detect_latex_compilers(prefer_engine: str = "") -> list[tuple[str, str]]:
    available: list[tuple[str, str]] = []
    for engine_name, binary_name in (("tectonic", "tectonic"), ("latexmk", "latexmk"), ("pdflatex", "pdflatex")):
        binary = shutil.which(binary_name)
        if binary:
            available.append((engine_name, binary))
    if not prefer_engine:
        return available
    preferred = [item for item in available if item[0] == prefer_engine]
    remainder = [item for item in available if item[0] != prefer_engine]
    return preferred + remainder


def _run_compile_command(
    command: list[str],
    *,
    cwd: Path,
    timeout_seconds: int = DRAFTER_COMPILE_TIMEOUT_SECONDS,
) -> tuple[int, str]:
    display = " ".join(command)
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = f"$ {display}\n{completed.stdout}{completed.stderr}".strip()
        return completed.returncode, output
    except subprocess.TimeoutExpired as exc:
        timeout_output = f"{str(exc.stdout or '')}{str(exc.stderr or '')}"
        return 124, f"$ {display}\n{timeout_output}\n[error] compile timed out after {timeout_seconds}s".strip()
    except OSError as exc:
        return 127, f"$ {display}\n[error] could not execute compiler: {exc}".strip()


def _copy_drafter_assets_for_compile(work_dir: Path) -> None:
    uploads_dir = work_dir / "drafter_uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    for source in DRAFTER_ASSETS_DIR.iterdir():
        if not source.is_file() or not drafter_asset_kind(source.name):
            continue
        target = uploads_dir / source.name
        shutil.copy2(source, target)
        # Also copy text assets into the workspace root for plain \input{file} and \bibliography{file}.
        if source.suffix.lower() in {".tex", ".bib"}:
            shutil.copy2(source, work_dir / source.name)


def _aux_requests_bibtex(aux_path: Path) -> bool:
    if not aux_path.exists():
        return False
    content = aux_path.read_text(encoding="utf-8", errors="ignore")
    return "\\citation" in content or "\\bibdata" in content


def _extract_latex_log(work_dir: Path) -> str:
    log_path = work_dir / "main.log"
    if not log_path.exists():
        return ""
    return log_path.read_text(encoding="utf-8", errors="replace")


def _cleanup_old_drafter_compiles() -> None:
    compile_dirs = [path for path in DRAFTER_COMPILES_DIR.iterdir() if path.is_dir()]
    if len(compile_dirs) <= DRAFTER_COMPILE_HISTORY_LIMIT:
        return
    compile_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for stale in compile_dirs[DRAFTER_COMPILE_HISTORY_LIMIT:]:
        shutil.rmtree(stale, ignore_errors=True)


def run_drafter_latex_compile(source: str, prefer_engine: str = "") -> dict[str, Any]:
    started = int(time.time() * 1000)
    supported = {"", "tectonic", "latexmk", "pdflatex"}
    normalized_preference = prefer_engine if prefer_engine in supported else ""
    compilers = _detect_latex_compilers(normalized_preference)
    if not compilers:
        return {
            "success": False,
            "status": "error",
            "compiler": "",
            "pdfUrl": "",
            "compiledAt": started,
            "durationMs": 0,
            "log": (
                "[error] No LaTeX compiler is installed.\n"
                "Install one of: tectonic, latexmk (with TeX Live/MacTeX), or pdflatex."
            ),
        }

    with tempfile.TemporaryDirectory(prefix="drafter-compile-") as temp_dir:
        work_dir = Path(temp_dir)
        main_path = work_dir / "main.tex"
        main_path.write_text(source, encoding="utf-8")
        _copy_drafter_assets_for_compile(work_dir)

        selected_engine = compilers[0][0]
        selected_binary = compilers[0][1]
        log_sections: list[str] = [f"[compile] engine={selected_engine}"]

        if selected_engine == "tectonic":
            exit_code, output = _run_compile_command(
                [
                    selected_binary,
                    "--keep-logs",
                    "--keep-intermediates",
                    "--outdir",
                    str(work_dir),
                    "main.tex",
                ],
                cwd=work_dir,
            )
            log_sections.append(output)
        elif selected_engine == "latexmk":
            exit_code, output = _run_compile_command(
                [
                    selected_binary,
                    "-pdf",
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    "main.tex",
                ],
                cwd=work_dir,
            )
            log_sections.append(output)
        else:
            pass1_code, pass1_output = _run_compile_command(
                [
                    selected_binary,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-file-line-error",
                    "main.tex",
                ],
                cwd=work_dir,
            )
            log_sections.append("[pdflatex] pass 1")
            log_sections.append(pass1_output)
            exit_code = pass1_code

            if pass1_code == 0 and shutil.which("bibtex") and _aux_requests_bibtex(work_dir / "main.aux"):
                bibtex_code, bibtex_output = _run_compile_command(["bibtex", "main"], cwd=work_dir)
                log_sections.append("[bibtex]")
                log_sections.append(bibtex_output)
                exit_code = bibtex_code if bibtex_code != 0 else exit_code

            if exit_code == 0:
                pass2_code, pass2_output = _run_compile_command(
                    [
                        selected_binary,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-file-line-error",
                        "main.tex",
                    ],
                    cwd=work_dir,
                )
                log_sections.append("[pdflatex] pass 2")
                log_sections.append(pass2_output)
                exit_code = pass2_code

            if exit_code == 0:
                pass3_code, pass3_output = _run_compile_command(
                    [
                        selected_binary,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        "-file-line-error",
                        "main.tex",
                    ],
                    cwd=work_dir,
                )
                log_sections.append("[pdflatex] pass 3")
                log_sections.append(pass3_output)
                exit_code = pass3_code

        main_pdf = work_dir / "main.pdf"
        latex_log = _extract_latex_log(work_dir)
        if latex_log:
            log_sections.append("[main.log]")
            log_sections.append(latex_log)

        compile_log = _truncate_compile_log("\n\n".join(section for section in log_sections if section))
        duration_ms = int(time.time() * 1000) - started
        succeeded = exit_code == 0 and main_pdf.exists() and main_pdf.stat().st_size > 0

        if not succeeded:
            return {
                "success": False,
                "status": "error",
                "compiler": selected_engine,
                "pdfUrl": "",
                "compiledAt": int(time.time() * 1000),
                "durationMs": duration_ms,
                "log": compile_log or f"[error] compile failed with exit code {exit_code}",
            }

        compile_id = f"{int(time.time() * 1000)}-{secrets.token_hex(5)}"
        output_dir = DRAFTER_COMPILES_DIR / compile_id
        output_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = output_dir / "main.pdf"
        shutil.copy2(main_pdf, output_pdf)
        (output_dir / "compile.log").write_text(compile_log, encoding="utf-8")
        _cleanup_old_drafter_compiles()

        status_label = "warn" if re.search(r"\bwarning\b", compile_log, flags=re.IGNORECASE) else "clean"
        return {
            "success": True,
            "status": status_label,
            "compiler": selected_engine,
            "pdfUrl": f"/downloads/drafter_compiles/{compile_id}/main.pdf",
            "compiledAt": int(time.time() * 1000),
            "durationMs": duration_ms,
            "log": compile_log,
        }


def normalize_draft_content(value: Any) -> str:
    return str(value or "")[:200000]


def normalize_draft_chat_content(value: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned[:1200]


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


def normalize_agent_trigger(value: Any, fallback: str = "ai") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip().lstrip("@").lower()).strip("-")
    return (cleaned[:24] or fallback).lower()


def normalize_agent_context_mode(value: Any) -> str:
    return "mention" if str(value or "").strip().lower() == "mention" else "room"


def list_agent_mentions(value: str) -> list[str]:
    mentions: list[str] = []
    for match in re.finditer(r"(?<!\w)@([a-z0-9._-]+)\b", str(value or ""), flags=re.IGNORECASE):
        mentions.append(normalize_agent_trigger(match.group(1)))
    return mentions


def strip_agent_mentions(value: str) -> str:
    cleaned = re.sub(r"(?<!\w)@[a-z0-9._-]+\b[:,]?\s*", "", str(value or ""), flags=re.IGNORECASE).strip()
    return cleaned or "Respond to the latest chat room discussion."


def extract_agent_prompt_from_mention(content: str, trigger: str) -> str:
    cleaned_trigger = normalize_agent_trigger(trigger)
    pattern = re.compile(rf"(?<!\w)@{re.escape(cleaned_trigger)}\b[:,]?\s*", flags=re.IGNORECASE)
    match = pattern.search(content or "")
    if not match:
        return strip_agent_mentions(content)
    mention_prompt = str(content or "")[match.end() :].strip()
    return mention_prompt or "Respond to the latest chat room discussion."


def normalize_route_model_id(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    return candidate or fallback


def normalize_route_provider_options(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def parse_route_entry(entry: Any, fallback_route: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    trigger = normalize_agent_trigger(entry.get("mentionTrigger") or entry.get("trigger"), fallback="")
    if not trigger:
        return None
    model_fallback = str(fallback_route.get("model_id") or "ollama:qwen2.5:7b")
    return {
        "trigger": trigger,
        "agent_name": normalize_room_label(entry.get("name") or entry.get("agentName"), fallback=fallback_route["agent_name"]),
        "system_prompt": normalize_room_system_prompt(entry.get("systemPrompt")),
        "model_id": normalize_route_model_id(entry.get("modelId"), fallback=model_fallback),
        "temperature": clamp_float(entry.get("temperature"), default=fallback_route["temperature"], minimum=0.0, maximum=2.0),
        "max_tokens": clamp_int(entry.get("maxTokens"), default=fallback_route["max_tokens"], minimum=64, maximum=4096),
        "provider_options": normalize_route_provider_options(entry.get("providerOptions")),
        "context_mode": normalize_agent_context_mode(entry.get("contextMode")),
    }


def select_room_ai_route(
    content: str,
    ai_routing: Any,
    *,
    fallback_route: dict[str, Any],
) -> dict[str, Any] | None:
    mentions = list_agent_mentions(content)
    if not mentions:
        return None

    routes_by_trigger: dict[str, dict[str, Any]] = {}
    if isinstance(ai_routing, dict):
        saved_agents = ai_routing.get("savedAgents")
        if isinstance(saved_agents, list):
            for entry in saved_agents:
                parsed = parse_route_entry(entry, fallback_route)
                if parsed:
                    routes_by_trigger[parsed["trigger"]] = parsed
        default_entry = ai_routing.get("defaultAgent")
        parsed_default = parse_route_entry(default_entry, fallback_route) if default_entry is not None else None
        if parsed_default:
            routes_by_trigger.setdefault(parsed_default["trigger"], parsed_default)

    fallback_trigger = normalize_agent_trigger(fallback_route.get("trigger"), fallback="ai")
    routes_by_trigger.setdefault(
        fallback_trigger,
        {
            "trigger": fallback_trigger,
            "agent_name": fallback_route["agent_name"],
            "system_prompt": fallback_route["system_prompt"],
            "model_id": fallback_route["model_id"],
            "temperature": fallback_route["temperature"],
            "max_tokens": fallback_route["max_tokens"],
            "provider_options": fallback_route["provider_options"],
            "context_mode": normalize_agent_context_mode(fallback_route.get("context_mode")),
        },
    )

    for mention in mentions:
        matched = routes_by_trigger.get(mention)
        if matched:
            return matched
    return None


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
    context_mode: str = "room",
    direct_prompt: str = "",
) -> list[ChatMessage]:
    transcript: list[ChatMessage] = []
    for item in history:
        if item.get("type") != "chat":
            continue
        sender = str(item.get("sender") or "guest")
        content = str(item.get("content") or "").strip()
        attachments = item.get("attachments") if isinstance(item.get("attachments"), list) else []
        has_image = any(
            isinstance(attachment, dict) and str(attachment.get("type") or "").lower() == "image"
            for attachment in attachments
        )
        file_attachments = [
            attachment
            for attachment in attachments
            if isinstance(attachment, dict) and str(attachment.get("type") or "").lower() == "file"
        ]
        if has_image:
            image_note = f"{sender} shared an image."
            if content:
                image_note = f"{image_note} Caption: {content}"
            content = image_note
        elif file_attachments:
            file_note = f"{sender} shared {len(file_attachments)} file"
            if len(file_attachments) != 1:
                file_note = f"{file_note}s"
            file_note = f"{file_note}."
            if content:
                file_note = f"{file_note} Caption: {content}"
            content = file_note
        if not content:
            continue

        if item.get("speakerType") == "ai":
            transcript.append(ChatMessage(role="assistant", content=content))
            continue

        transcript.append(ChatMessage(role="user", content=f"{sender}: {strip_agent_mentions(content)}"))

    system_parts = [
        ROOM_AI_SYSTEM_PROMPT,
        f"You are {agent_name}, replying on behalf of {requester_name}.",
    ]
    if normalize_agent_context_mode(context_mode) == "mention":
        system_parts.append("Only use the direct text after your trigger mention as context.")
    else:
        system_parts.append("The transcript is shared across the room, so stay consistent with the ongoing conversation.")
    if system_prompt:
        system_parts.append(f"Additional instructions: {system_prompt}")

    if normalize_agent_context_mode(context_mode) == "mention":
        prompt = direct_prompt.strip() or "Respond to the latest chat room discussion."
        return [
            ChatMessage(role="system", content=" ".join(system_parts)),
            ChatMessage(role="user", content=f"{requester_name}: {prompt}"),
        ]

    trimmed = trim_room_context(transcript)
    return [ChatMessage(role="system", content=" ".join(system_parts)), *trimmed]


def run() -> None:
    settings = get_settings()
    uvicorn.run("localchat.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
