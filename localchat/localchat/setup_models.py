from __future__ import annotations

import shutil
import subprocess
import sys


MODELS = ("qwen2.5:7b", "deepseek-r1", "gemma3:7b", "gemma3:12b")


def main() -> int:
    ollama_path = shutil.which("ollama")
    if not ollama_path:
        print("Ollama is not installed or not on PATH.", file=sys.stderr)
        print("Install it from https://ollama.com/download/windows and rerun this command.", file=sys.stderr)
        return 1

    for model in MODELS:
        print(f"Pulling {model} ...")
        completed = subprocess.run([ollama_path, "pull", model], check=False)
        if completed.returncode != 0:
            return completed.returncode

    print("Model download complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
