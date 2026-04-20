#!/usr/bin/env python3
"""Run LocalChat client bootstrap checks/setup."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    command = [sys.executable, "-m", "localchat.bootstrap", *sys.argv[1:]]
    completed = subprocess.run(command, check=False)  # noqa: S603
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
