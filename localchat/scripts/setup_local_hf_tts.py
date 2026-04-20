#!/usr/bin/env python3
"""Download/load/test a local Hugging Face TTS model for LocalChat."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_TEXT = "LocalChat local Hugging Face TTS test."
DEFAULT_OUTPUT = "localchat/downloads/local_hf_tts_probe.wav"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Setup/test local Hugging Face TTS for LocalChat.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model id.")
    parser.add_argument("--text", default=DEFAULT_TEXT, help="Text to synthesize.")
    parser.add_argument("--voice", default="Chelsie", help="Optional speaker/voice hint.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output WAV path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(Path("localchat").resolve()))

    try:
        from localchat.main import request_local_hf_tts_audio  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Could not import LocalChat TTS runtime: {exc}",
                    "hint": "Run: uv pip install transformers torch",
                },
                indent=2,
            )
        )
        return 1

    try:
        audio_bytes, media_type = request_local_hf_tts_audio(
            model_id=args.model,
            text=args.text,
            voice=args.voice,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "model": args.model,
                    "error": str(exc),
                    "hint": "Ensure local deps are installed and model is available for transformers text-to-speech.",
                },
                indent=2,
            )
        )
        return 2

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    print(
        json.dumps(
            {
                "ok": True,
                "model": args.model,
                "mediaType": media_type,
                "bytes": len(audio_bytes),
                "output": str(output_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
