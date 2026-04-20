# Local Chat

Local-first collaboration app (room + drafter + sockets) where each client is responsible for their own model runtime setup.

## Local-First Quick Start (Per Client)

1. Install Python 3.12+ and Ollama.
2. From repo root:
```powershell
cd localchat
python -m pip install uv
uv sync
```
3. Run local bootstrap (checks Ollama, pulls base Ollama models, checks CUDA/Torch, probes local TTS):
```powershell
uv run localchat-bootstrap
```
4. Start app:
```powershell
uv run localchat
```
5. Open:
```text
http://127.0.0.1:8000
```

## GPU + Local Voice Reader

- Voice Reader uses `POST /api/tts/local` with local `qwen-tts` runtime.
- Device selection is local per client:
  - `LOCAL_TTS_DEVICE=auto` (default)
  - `LOCAL_TTS_DEVICE=cuda:0`
  - `LOCAL_TTS_DEVICE=cpu`
- Quick CUDA check:
```powershell
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count(), (torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''))"
```
- Local TTS status endpoint:
```text
GET /api/tts/local/status
```

## Environment

Copy `localchat/.env.example` to `localchat/.env` and adjust as needed.

Most important values:
- `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`)
- `LOCAL_TTS_DEVICE` (`auto`, `cuda:0`, or `cpu`)
- `HOST` / `PORT`
- `COLLAB_ALLOW_REMOTE_CLIENTS`
- `COLLAB_ALLOW_REMOTE_PAGES`
- `COLLAB_ALLOWED_CLIENT_IPS`

## How To Use The UI

1. Open the page in your browser.
2. Pick a model from the model selector.
3. Optionally set a system prompt.
4. Type a message and press `Enter`.
5. Use `Shift+Enter` for a newline.
6. Use `Stop` to abort a streaming response.

UI features:

- conversation history stored in browser local storage
- delete whole chats from history or the active chat view
- auto-generated short chat names after the first user prompt and assistant reply
- syntax-highlighted code blocks
- copy buttons for messages and code blocks
- temperature and max token controls
- token-by-token streaming into the message pane

## Collaboration Setup

The room and drafter collaboration routes are now gated separately from the main app:

- `GET /room` and `GET /drafter` are served only to localhost unless `COLLAB_ALLOW_REMOTE_PAGES=true`.
- Websocket collaboration on `/ws/rooms/...` and `/ws/drafts/...` allows localhost by default.
- Remote collaborators must be explicitly enabled with `COLLAB_ALLOW_REMOTE_CLIENTS=true`.
- When remote collaboration is enabled, add the allowed client IPs to `COLLAB_ALLOWED_CLIENT_IPS` as a comma-separated list.

Recommended private setup:

1. Keep `COLLAB_ALLOW_REMOTE_PAGES=false`.
2. Run your own server on a reachable host/IP.
3. Have collaborators run LocalChat from source on their own machine.
4. Give them your server IP and allowlist their client IP in `COLLAB_ALLOWED_CLIENT_IPS`.

### Connect To The Drafter Socket

Use the right-side `Connection` panel on `/drafter`:

1. Set `Server URL / IP` to the host running LocalChat, for example `http://192.168.1.40:8000`.
2. Enter `Your Name`.
3. Enter the shared `Draft Room` name.
4. Click `Connect`.

The page converts that server value into the drafter websocket automatically:

```text
ws://HOST:PORT/ws/drafts/ROOM?name=YOUR_NAME
```

Example:

```text
ws://192.168.1.40:8000/ws/drafts/paper-main?name=jake
```

Notes:

- If the server uses HTTPS, the socket uses `wss://`.
- The host machine must allow the collaborator IP through `COLLAB_ALLOWED_CLIENT_IPS` when remote clients are enabled.
- `Save Snapshot`, `Download .tex`, and `Export PDF` are available from the left-side `Overview` panel in Drafter.
- Drafter PDF compile requires a local TeX toolchain on the host machine. LocalChat auto-detects `tectonic`, `latexmk`, or `pdflatex`.

## Vintage Ad Downloader

A separate script is included for pulling a starter set of retro banner ads from the Wayback Machine into a local folder.

From PowerShell:

```powershell
cd d:\APPS\Tools\localchat
python .\scripts\fetch_vintage_ads.py --count 50
```

Default output:

```text
d:\APPS\Tools\localchat\downloads\vintage_ads
```

Notes:

- the script queries archived captures from the 1995-2009 range
- it writes a `manifest.json` alongside the downloaded files
- some configured seeds target casino, ad-network, and adult-style "spicy" banner inventory
- archive availability varies, so rerunning may find a different mix of captures

## API Endpoints

### `GET /`

Serves the frontend.

### `GET /health`

Simple health check.

### `GET /api/provider-health/google`

Checks Gemini/Google model connectivity with a lightweight probe.

Example:

```text
GET /api/provider-health/google?model=gemini:gemini-2.5-flash
```

Returns status metadata (`ok`, `not_configured`, or `error`) plus timing.

### `GET /api/models`

Returns model metadata for the frontend.

### `POST /api/drafter/compile`

Compiles Drafter `main.tex` with a real LaTeX compiler and returns a PDF URL + compile log.

Request body:

```json
{
  "content": "\\documentclass{article} ...",
  "engine": "tectonic"
}
```

`engine` is optional. When omitted, LocalChat chooses the first available compiler from:

1. `tectonic`
2. `latexmk`
3. `pdflatex`

### `GET /v1/models`

Returns an OpenAI-style model list.

### `POST /v1/chat/completions`

Accepts the OpenAI Chat Completions request shape.

Streaming example:

```json
{
  "model": "ollama:qwen2.5:7b",
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 1024,
  "messages": [
    { "role": "system", "content": "You are concise." },
    { "role": "user", "content": "Write a hello world script in Python." }
  ]
}
```

## LLM Response Log

Every completion request now appends a JSON line entry to:

```text
localchat/localchat/llm_responses.jsonl
```

Each entry includes timestamp, model/provider, request metadata, response text, and error state.

Non-streaming example:

```json
{
  "model": "gemini:gemini-2.5-flash",
  "stream": false,
  "messages": [
    { "role": "user", "content": "Summarize FastAPI in one paragraph." }
  ]
}
```

## Example `curl`

```powershell
curl -N http://127.0.0.1:8000/v1/chat/completions `
  -H "Content-Type: application/json" `
  -d "{\"model\":\"ollama:qwen2.5:7b\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Write a Python function that reverses a string.\"}]}"
```

## Troubleshooting

### `uv` is not installed

Install it with:

```powershell
python -m pip install uv
```

### `ollama` is not recognized

Install Ollama, restart your terminal, then rerun the model setup command.

### Hugging Face requests fail

Check that `HUGGINGFACE_API_KEY` is set in `d:\APPS\Tools\localchat\.env`.

### Gemini requests fail

Check that `GEMINI_API_KEY` is set in `d:\APPS\Tools\localchat\.env`.

### Local models fail

Check:

1. Ollama is installed
2. Ollama is running
3. The models were pulled successfully
4. `OLLAMA_BASE_URL` matches your Ollama server

## Development Notes

- The backend serves the frontend directly from the same origin.
- The backend normalizes provider output into an OpenAI-style response shape.
- The package explicitly loads `.env` from the project root, not from the workspace root.
