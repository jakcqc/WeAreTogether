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
ROOM_STATE_PATH = BASE_DIR / "room_state.json"
ROOM_HISTORY_LIMIT = 120
ROOM_CONTEXT_MESSAGE_LIMIT = 18
ROOM_CONTEXT_CHAR_BUDGET = 16000
DRAFT_CHAT_HISTORY_LIMIT = 80
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
    focus_mode: bool = False


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

    async def connect(self, room_name: str, websocket: WebSocket) -> dict[str, Any]:
        await websocket.accept()
        async with self._lock:
            room = self._rooms.setdefault(room_name, RoomState())
            room.clients.add(websocket)
            return {
                "messages": list(room.history),
                "focusMode": room.focus_mode,
            }

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

    async def toggle_reaction(
        self,
        room_name: str,
        *,
        message_id: str,
        emoji: str,
        username: str,
    ) -> dict[str, dict[str, Any]] | None:
        async with self._lock:
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
            room = self._rooms.get(room_name)
            if room is None:
                return False
            original_len = len(room.history)
            room.history = [item for item in room.history if str(item.get("id")) != message_id]
            deleted = len(room.history) < original_len
            if deleted:
                self._persist_locked()
            return deleted

    async def _broadcast_clients(self, room_name: str, clients: list[WebSocket], payload: dict[str, Any]) -> None:
        stale_clients: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale_clients.append(client)

        for client in stale_clients:
            await self.disconnect(room_name, client)

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


@app.get("/api/client/runtime")
async def client_runtime() -> dict[str, str]:
    settings = get_settings()
    return {"ollamaBaseUrl": settings.ollama_base_url}


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
    snapshot = await room_hub.connect(normalized_room, websocket)
    pending_ai_requests: dict[str, dict[str, str]] = {}

    try:
        await websocket.send_json(
            {
                "type": "history",
                "room": normalized_room,
                "messages": snapshot["messages"],
                "focusMode": bool(snapshot.get("focusMode")),
                "canDeleteMessages": can_manage_room_messages(websocket),
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
                request_id = secrets.token_hex(8)
                history = await room_hub.snapshot(normalized_room)
                ai_messages = build_room_ai_messages(
                    history,
                    requester_name=username,
                    agent_name=agent_name,
                    system_prompt=system_prompt,
                )
                pending_ai_requests[request_id] = {
                    "agent_name": agent_name,
                    "model_id": model_id,
                }
                await room_hub.append_and_broadcast(
                    normalized_room,
                    build_room_event(
                        event_type="system",
                        sender="system",
                        speaker_type="system",
                        content=f"{agent_name} is generating a local reply with {model_id}.",
                        model_id=model_id,
                    ),
                )
                await websocket.send_json(
                    {
                        "type": "ai_request",
                        "requestId": request_id,
                        "room": normalized_room,
                        "requester": username,
                        "agentName": agent_name,
                        "modelId": model_id,
                        "temperature": temperature,
                        "maxTokens": max_tokens,
                        "messages": [message.model_dump() for message in ai_messages],
                    }
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


def can_manage_room_messages(connection: Request | WebSocket) -> bool:
    host = connection_host(connection)
    if is_loopback_host(host):
        return True
    settings = get_settings()
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


def normalize_reaction_emoji(value: Any) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    candidate = re.sub(r"\s+", "", candidate)
    return candidate[:16]


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


def run() -> None:
    settings = get_settings()
    uvicorn.run("localchat.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    run()
