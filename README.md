# Local Chat

Local chat app with:

- a FastAPI backend
- an OpenAI-style `POST /v1/chat/completions` endpoint
- SSE token streaming
- provider routing for local Ollama, Hugging Face, and Gemini
- a plain HTML/CSS/JS frontend with chat history, markdown, syntax highlighting, copy buttons, and model selection
- chat auto-titles generated from the first completed exchange
- chat deletion from the local history list or current chat toolbar

## Project Location

This project now lives entirely under:

```text
d:\APPS\Tools\localchat
```

The Python package is in:

```text
d:\APPS\Tools\localchat\localchat
```

## Included Models

- `ollama:qwen2.5:7b`
- `ollama:deepseek-r1`
- `hf:Qwen/Qwen2.5-Coder-32B-Instruct`
- `hf:deepseek-ai/DeepSeek-R1-Distill-Qwen-32B`
- `gemini:gemini-2.5-flash`

## Prerequisites

### Required

1. Python 3.12 or newer
2. Internet access for Hugging Face or Gemini calls

### Optional but recommended

1. `uv` for dependency and run management
2. Ollama if you want local models

## End-to-End Setup

### 1. Open the project folder

From PowerShell:

```powershell
cd d:\APPS\Tools\localchat
```

### 2. Configure environment variables

This project uses its own local env file:

```text
d:\APPS\Tools\localchat\.env
```

Template:

```text
d:\APPS\Tools\localchat\.env.example
```

Variables used by the app:

- `HUGGINGFACE_API_KEY`
- `GEMINI_API_KEY`
- `OLLAMA_BASE_URL`
- `HOST`
- `PORT`
- `COLLAB_ALLOW_REMOTE_CLIENTS`
- `COLLAB_ALLOW_REMOTE_PAGES`
- `COLLAB_ALLOWED_CLIENT_IPS`

Notes:

- `HUGGINGFACE_API_KEY` is required for Hugging Face models.
- `GEMINI_API_KEY` is required for Gemini models.
- `OLLAMA_BASE_URL` defaults to `http://127.0.0.1:11434`.
- `HOST` and `PORT` control where the FastAPI app runs.
- Collaboration pages are localhost-only by default.
- To let remote collaborators join room or drafter sessions, set `COLLAB_ALLOW_REMOTE_CLIENTS=true` and put their client IPs in `COLLAB_ALLOWED_CLIENT_IPS`.
- Keep `COLLAB_ALLOW_REMOTE_PAGES=false` if collaborators should run LocalChat from source on their own machine and connect to your shared server IP from there.

### 3. Install dependencies

#### Option A: use `uv`

Install `uv` if it is not already installed:

```powershell
python -m pip install uv
```

Install project dependencies:

```powershell
uv sync
```

#### Option B: use standard `pip`

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install the project:

```powershell
python -m pip install -e .
```

## Ollama Setup For Local Models

If you want to run Qwen and DeepSeek locally, install Ollama first.

### 1. Install Ollama

Download and install the Windows build from:

```text
https://ollama.com/download/windows
```
 or in powershell run:
```powershell

 irm https://ollama.com/install.ps1 | iex
 ```

 if in gitbash, after doing this install add this into your stuff:
 
# Make Ollama available in Git Bash if it is installed under the default Windows path.
ask gpt to walk you through this step, or just use powershell...

### 2. Pull the local models

Using `uv`:

```powershell
uv run localchat-models
```

Without `uv`:

```powershell
python -m localchat.setup_models
```

This pulls:

- `qwen2.5:7b`
- `deepseek-r1`

### 3. Confirm Ollama is running

If Ollama is installed normally on Windows, the backend expects:

```text
http://127.0.0.1:11434
```

If your Ollama server runs somewhere else, update `OLLAMA_BASE_URL` in `.env`.

## Run The App

### Option A: run with `uv`

```powershell
uv run localchat
```

### Option B: run with `uvicorn`

```powershell
python -m uvicorn localchat.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000
```

If you changed `HOST` or `PORT`, use that address instead.

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

### `GET /api/models`

Returns model metadata for the frontend.

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
