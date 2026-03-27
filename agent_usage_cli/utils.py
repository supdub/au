from __future__ import annotations

import json
import os
import re
import select
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import tomllib


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return None


def read_toml(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError:
        return None
    except (OSError, tomllib.TOMLDecodeError):
        return None


def env_flag(name: str, env: dict[str, str] | None = None) -> bool:
    env_map = env if env is not None else os.environ
    value = env_map.get(name)
    return bool(value and value.strip())


def expand(path: str) -> Path:
    return Path(path).expanduser()


def iter_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    items.append(obj)
    except FileNotFoundError:
        return []
    except OSError:
        return []
    return items


def latest_matching_file(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    latest: Path | None = None
    latest_mtime = -1.0
    for path in root.rglob(pattern):
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        if stat.st_mtime > latest_mtime:
            latest = path
            latest_mtime = stat.st_mtime
    return latest


def run_json_command(argv: list[str], timeout: float = 1.5) -> dict[str, Any] | None:
    if not argv:
        return None
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        obj = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def run_json_lines_command(argv: list[str], timeout: float = 3.0) -> list[dict[str, Any]]:
    if not argv:
        return []
    if shutil.which(argv[0]) is None:
        return []
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    items: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            items.append(obj)
    return items


def run_json_stream_command(
    argv: list[str],
    *,
    timeout: float = 5.0,
    stop_types: set[str] | None = None,
    max_events: int = 50,
) -> list[dict[str, Any]]:
    if not argv:
        return []
    if shutil.which(argv[0]) is None:
        return []
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    items: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    try:
        stdout = proc.stdout
        if stdout is None:
            return []
        while len(items) < max_events:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([stdout], [], [], remaining)
            if not ready:
                break
            line = stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            items.append(obj)
            if stop_types and obj.get("type") in stop_types:
                break
        return items
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=0.5)


ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def run_text_command(argv: list[str], timeout: float = 1.5) -> str | None:
    if not argv:
        return None
    if shutil.which(argv[0]) is None:
        return None
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    stdout = strip_ansi(proc.stdout).strip()
    return stdout or None
