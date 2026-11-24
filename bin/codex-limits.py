"""Read Codex account limits and emit window, used percent, and reset epoch."""

import fcntl
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time


def receive(server, request_id, deadline):
    pending = b""
    with selectors.DefaultSelector() as ready:
        ready.register(server.stdout, selectors.EVENT_READ)
        while ready.select(max(0, deadline - time.monotonic())):
            chunk = os.read(server.stdout.fileno(), 65536)
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                response = json.loads(line)
                if response.get("id") == request_id:
                    return response["result"]
            if time.monotonic() >= deadline:
                break
    raise TimeoutError("Codex app server did not return rate limits")


def send(server, method, request_id=None, params=None):
    message = {"method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    server.stdin.write(json.dumps(message).encode() + b"\n")
    server.stdin.flush()


def fetch_limits():
    with subprocess.Popen(
        [os.environ.get("CODEX_BIN", "codex"), "app-server", "--listen", "stdio://"],
        cwd=Path(__file__).resolve().parent,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as server:
        try:
            deadline = time.monotonic() + 5
            send(server, "initialize", 1, {"clientInfo": {
                "name": "herdr-agent-usage", "version": "0.1.0"
            }})
            receive(server, 1, deadline)
            send(server, "initialized")
            send(server, "account/rateLimits/read", 2)
            response = receive(server, 2, deadline)
        finally:
            if server.poll() is None:
                server.kill()

    buckets = response.get("rateLimitsByLimitId") or {}
    limits = buckets.get("codex") or response.get("rateLimits") or {}
    windows = []
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        minutes = window.get("windowDurationMins")
        used = window.get("usedPercent")
        reset = window.get("resetsAt")
        if not isinstance(used, (int, float)) or not 0 <= used <= 100:
            continue
        if minutes == 300:
            label = "five_hour"
        elif minutes == 10080:
            label = "seven_day"
        elif isinstance(minutes, int) and minutes > 0:
            label = f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"
        else:
            label = key
        windows.append((label, round(used), reset if isinstance(reset, int) else 0))
    return windows


def cached_limits(state):
    cache = state / "codex-windows.json"
    lock = state / "codex-refresh.lock"
    try:
        with lock.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            now = time.time()
            stamp = os.fstat(handle.fileno())
            if stamp.st_size == 0 or now - stamp.st_mtime >= 120:
                handle.write(".")
                handle.flush()
                handle.truncate(1)
                windows = fetch_limits()
                pending = cache.with_suffix(".tmp")
                pending.write_text(json.dumps(windows), encoding="utf-8")
                pending.replace(cache)
    except (OSError, KeyError, ValueError):
        pass

    try:
        if time.time() - cache.stat().st_mtime < 900:
            return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return []


if __name__ == "__main__":
    now = int(time.time())
    for window, used, reset in cached_limits(Path(sys.argv[1])):
        if not reset or reset > now:
            print(window, used, reset, sep="\t")
