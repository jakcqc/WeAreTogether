from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any
from urllib import error, request as urllib_request

from .config import get_settings
from .main import LOCAL_TTS_DEFAULT_MODEL, request_local_hf_tts_audio

DEFAULT_OLLAMA_MODELS = ("qwen2.5:7b", "deepseek-r1", "gemma3:7b", "gemma3:12b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap local client setup for LocalChat.")
    parser.add_argument("--skip-ollama-check", action="store_true", help="Skip Ollama binary/runtime checks.")
    parser.add_argument("--skip-ollama-pull", action="store_true", help="Skip pulling default Ollama models.")
    parser.add_argument("--skip-tts-probe", action="store_true", help="Skip local TTS synthesis probe.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_OLLAMA_MODELS),
        help="Ollama models to pull when pull is enabled.",
    )
    parser.add_argument("--tts-model", default=LOCAL_TTS_DEFAULT_MODEL, help="Local Qwen TTS model id.")
    parser.add_argument("--tts-voice", default="Chelsie", help="Speaker hint for local TTS probe.")
    parser.add_argument("--tts-text", default="LocalChat startup local voice probe.", help="TTS probe text.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary JSON.")
    return parser.parse_args()


def check_ollama_binary() -> tuple[bool, str]:
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        return False, "Ollama is not on PATH."
    return True, ollama_path


def check_ollama_runtime() -> tuple[bool, str]:
    base_url = get_settings().ollama_base_url
    tags_url = f"{base_url}/api/tags"
    try:
        with urllib_request.urlopen(tags_url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, error.URLError) as exc:
        return False, f"Ollama runtime check failed at {tags_url}: {exc}"
    models = payload.get("models") if isinstance(payload, dict) else []
    count = len(models) if isinstance(models, list) else 0
    return True, f"Ollama reachable at {base_url} ({count} model(s) listed)."


def pull_ollama_models(models: list[str]) -> tuple[bool, str]:
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        return False, "Cannot pull models because ollama is not on PATH."
    for model in models:
        candidate = str(model or "").strip()
        if not candidate:
            continue
        completed = subprocess.run([ollama_path, "pull", candidate], check=False)  # noqa: S603
        if completed.returncode != 0:
            return False, f"ollama pull failed for {candidate} (exit {completed.returncode})."
    return True, f"Pulled {len(models)} Ollama model(s)."


def torch_cuda_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "torchInstalled": False,
        "torchVersion": "",
        "cudaAvailable": False,
        "cudaDeviceCount": 0,
        "cudaDeviceName": "",
        "cudaVersion": "",
    }
    try:
        import torch  # pylint: disable=import-outside-toplevel
    except Exception as exc:  # noqa: BLE001
        summary["error"] = f"torch import failed: {exc}"
        return summary
    summary["torchInstalled"] = True
    summary["torchVersion"] = str(getattr(torch, "__version__", ""))
    summary["cudaVersion"] = str(getattr(torch.version, "cuda", "") or "")
    summary["cudaAvailable"] = bool(torch.cuda.is_available())
    if summary["cudaAvailable"]:
        summary["cudaDeviceCount"] = int(torch.cuda.device_count())
        if summary["cudaDeviceCount"] > 0:
            summary["cudaDeviceName"] = str(torch.cuda.get_device_name(0) or "")
    return summary


def probe_local_tts(model_id: str, text: str, voice: str) -> tuple[bool, str]:
    try:
        audio_bytes, media_type = request_local_hf_tts_audio(
            model_id=model_id,
            text=text,
            voice=voice,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"Local TTS probe failed: {exc}"
    return True, f"Local TTS probe passed ({len(audio_bytes)} bytes, {media_type})."


def main() -> int:
    args = parse_args()
    results: list[dict[str, Any]] = []
    has_error = False

    if not args.skip_ollama_check:
        ok_path, path_detail = check_ollama_binary()
        results.append({"step": "ollama_binary", "ok": ok_path, "detail": path_detail})
        if not ok_path:
            has_error = True
        else:
            ok_runtime, runtime_detail = check_ollama_runtime()
            results.append({"step": "ollama_runtime", "ok": ok_runtime, "detail": runtime_detail})
            if not ok_runtime:
                has_error = True

    if not args.skip_ollama_pull and not has_error:
        ok_pull, pull_detail = pull_ollama_models(args.models)
        results.append({"step": "ollama_pull", "ok": ok_pull, "detail": pull_detail, "models": args.models})
        if not ok_pull:
            has_error = True

    cuda = torch_cuda_summary()
    results.append({"step": "torch_cuda", "ok": bool(cuda.get("torchInstalled")), "detail": cuda})
    if not bool(cuda.get("torchInstalled")):
        has_error = True

    if not args.skip_tts_probe:
        ok_tts, tts_detail = probe_local_tts(args.tts_model, args.tts_text, args.tts_voice)
        results.append({"step": "local_tts_probe", "ok": ok_tts, "detail": tts_detail, "model": args.tts_model})
        if not ok_tts:
            has_error = True

    summary = {"ok": not has_error, "results": results}
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for item in results:
            status = "OK" if item.get("ok") else "FAIL"
            print(f"[{status}] {item.get('step')}: {item.get('detail')}")
        print("Bootstrap complete." if not has_error else "Bootstrap finished with failures.")

    return 0 if not has_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
