#!/usr/bin/env python3
"""Local Hugging Face TTS setup and verification helper for LocalChat."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


DEFAULT_MODELS = [
    "microsoft/speecht5_tts",
    "facebook/mms-tts-eng",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configure and verify Hugging Face TTS access for LocalChat.")
    parser.add_argument(
        "--env-file",
        default="localchat/.env",
        help="Path to .env file (default: localchat/.env)",
    )
    parser.add_argument(
        "--set-key",
        action="store_true",
        help="Prompt for HUGGINGFACE_API_KEY and write it to the env file.",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help="One or more model ids to probe.",
    )
    parser.add_argument(
        "--text",
        default="LocalChat voice reader setup test.",
        help="Probe text to synthesize.",
    )
    return parser.parse_args()


def read_env_lines(env_path: Path) -> list[str]:
    if not env_path.exists():
        return []
    return env_path.read_text(encoding="utf-8").splitlines()


def write_env_key(env_path: Path, key: str, value: str) -> None:
    lines = read_env_lines(env_path)
    output: list[str] = []
    replaced = False
    pattern = re.compile(rf"^{re.escape(key)}=")
    for line in lines:
        if pattern.match(line):
            output.append(f"{key}={value}")
            replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(f"{key}={value}")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(output) + "\n", encoding="utf-8")


def mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:5]}...{value[-4:]}"


def run_probe(api_key: str, model_id: str, text: str) -> dict[str, Any]:
    sys.path.insert(0, str(Path("localchat").resolve()))
    from localchat.main import request_huggingface_tts_audio  # pylint: disable=import-outside-toplevel

    try:
        audio_bytes, media_type = request_huggingface_tts_audio(
            api_key=api_key,
            model_id=model_id,
            text=text,
            voice="",
        )
        return {
            "model": model_id,
            "ok": True,
            "mediaType": media_type,
            "bytes": len(audio_bytes),
        }
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        hint = ""
        lower_message = message.lower()
        if "sufficient permissions to call inference providers" in lower_message:
            hint = (
                "Your HF token is missing Inference Providers permission. "
                "Create a user access token with Inference Providers enabled and replace HUGGINGFACE_API_KEY."
            )
        return {
            "model": model_id,
            "ok": False,
            "error": message,
            "hint": hint,
        }


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)

    if args.set_key:
        entered = getpass.getpass("Enter HUGGINGFACE_API_KEY (input hidden): ").strip()
        if not entered:
            print("No key entered. Aborting.", file=sys.stderr)
            return 1
        write_env_key(env_path, "HUGGINGFACE_API_KEY", entered)
        print(f"Updated {env_path} with HUGGINGFACE_API_KEY={mask_key(entered)}")

    load_dotenv(env_path)
    api_key = os.getenv("HUGGINGFACE_API_KEY", "").strip()
    if not api_key:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "missing_key",
                    "detail": f"HUGGINGFACE_API_KEY was not found in {env_path}",
                },
                indent=2,
            )
        )
        return 1

    print(f"Using HUGGINGFACE_API_KEY={mask_key(api_key)} from {env_path}")
    results = [run_probe(api_key=api_key, model_id=model, text=args.text) for model in args.models]
    success = any(item.get("ok") for item in results)

    print(json.dumps({"ok": success, "results": results}, indent=2))
    if success:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
