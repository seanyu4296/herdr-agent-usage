"""Read Antigravity quota and emit window, used percent, reset epoch.

Verified on this machine: the CLI's print-mode JSON envelope, the authentication
and eligibility failure states, and the quota backend endpoint that Google's own
client calls:

    POST https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary

Not verified: the shape of a *successful* /usage response, because the signed-in
account is refused by location ("Your current account is not eligible for
Antigravity, because it is not currently available in your location"). parse_quota
handles the shape documented for the local language server
(quotaInfo.remainingFraction, quotaInfo.resetTime) and a text fallback, and must be
re-checked the first time an eligible account runs this.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REFRESH_SECS = 300   # how often to call the CLI
SERVE_SECS = 3600    # how long a cached answer stays usable
CALL_TIMEOUT = 90    # the CLI authenticates and hits the network per call


def classify(envelope):
    """Map a print-mode envelope to (state, detail)."""
    status = (envelope.get("status") or "").lower()
    error = envelope.get("error") or ""
    if status == "ok" or (status and not error):
        return "ok", ""
    low = error.lower()
    if "not eligible" in low or "not currently available in your location" in low:
        return "ineligible", error
    if "authentication" in low or "log in" in low or "sign in" in low:
        return "unauthenticated", error
    if "license" in low:
        return "unlicensed", error
    return "error", error or f"status={status or 'unknown'}"


def parse_quota(response):
    """Emit (key, used_percent, reset_epoch) rows from a /usage response.

    Keys reuse the shared vocabulary so the renderer needs no new labels:
    five_hour / seven_day for the first model group, week:<group> for the rest.
    """
    rows = []

    def add(label, remaining, reset):
        if not isinstance(remaining, (int, float)):
            return
        used = round((1 - float(remaining)) * 100) if 0 <= float(remaining) <= 1 else round(float(remaining))
        rows.append((label, max(0, min(100, used)), int(reset) if isinstance(reset, (int, float)) else 0))

    try:
        parsed = json.loads(response)
    except (TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        groups = parsed.get("quotaGroups") or parsed.get("groups") or []
        if isinstance(groups, list):
            for index, group in enumerate(groups):
                name = group.get("label") or group.get("name") or f"group{index + 1}"
                for window, key in (("fiveHour", "five_hour"), ("weekly", "seven_day"),
                                    ("five_hour", "five_hour"), ("seven_day", "seven_day")):
                    bucket = group.get(window)
                    if not isinstance(bucket, dict):
                        continue
                    label = key if index == 0 else f"week:{name}"
                    add(label, bucket.get("remainingFraction", bucket.get("remaining")),
                        bucket.get("resetTime", bucket.get("resetsAt", 0)))
        for bucket in parsed.get("quotaInfo") or []:
            if isinstance(bucket, dict):
                add(bucket.get("key", "five_hour"), bucket.get("remainingFraction"),
                    bucket.get("resetTime", 0))

    if not rows and response:
        # Fallback: "<label> ... 42% ... reset <iso|epoch>" lines in the panel text.
        for line in response.splitlines():
            pct = re.search(r"(\d{1,3})\s*%\s*(remaining|used)?", line, re.I)
            if not pct:
                continue
            value = int(pct.group(1))
            used = value if (pct.group(2) or "").lower() == "used" else 100 - value
            stamp = 0
            iso = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
            if iso:
                try:
                    stamp = int(time.mktime(time.strptime(iso.group(1), "%Y-%m-%dT%H:%M:%S")))
                except ValueError:
                    stamp = 0
            label = "five_hour" if re.search(r"5\s*h|five|session", line, re.I) else "seven_day"
            rows.append((label, max(0, min(100, used)), stamp))

    seen = set()
    unique = []
    for row in rows:
        if row[0] in seen:
            continue
        seen.add(row[0])
        unique.append(row)
    return unique


def call_cli():
    binary = os.environ.get("AGY_BIN", "agy")
    env = dict(os.environ, AGY_CLI_DISABLE_AUTO_UPDATE="true")
    try:
        done = subprocess.run(
            [binary, "-p", "/usage", "--output-format", "json"],
            capture_output=True, text=True, timeout=CALL_TIMEOUT, env=env,
            cwd=Path(__file__).resolve().parent,
        )
    except (OSError, subprocess.TimeoutExpired) as failure:
        return {"status": "ERROR", "error": f"{type(failure).__name__}: {failure}"}
    for candidate in (done.stdout, done.stderr):
        text = (candidate or "").strip()
        if text.startswith("{"):
            try:
                return json.loads(text.splitlines()[0])
            except ValueError:
                continue
    return {"status": "ERROR", "error": (done.stderr or done.stdout or "no output").strip()[:300]}


def refresh(state):
    envelope = call_cli()
    state_kind, detail = classify(envelope)
    payload = {
        "at": int(time.time()),
        "state": state_kind,
        "detail": detail[:300],
        "rows": parse_quota(envelope.get("response") or "") if state_kind == "ok" else [],
    }
    pending = state / "agy-usage.tmp"
    pending.write_text(json.dumps(payload), encoding="utf-8")
    pending.replace(state / "agy-usage.json")
    return payload


def read_cache(state):
    try:
        return json.loads((state / "agy-usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def spawn_refresh(state):
    """Start one detached refresh, at most every REFRESH_SECS."""
    lock = state / "agy-refresh.lock"
    try:
        with lock.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            stamp = os.fstat(handle.fileno())
            if stamp.st_size and time.time() - stamp.st_mtime < REFRESH_SECS:
                return
            handle.write(".")
            handle.flush()
            handle.truncate(1)
    except OSError:
        return
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(state), "--refresh"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def cached(state):
    """Cache-only read: the tab bar must never block on the CLI."""
    payload = read_cache(state)
    if payload and time.time() - payload.get("at", 0) < SERVE_SECS:
        return payload
    spawn_refresh(state)
    return payload or {"at": 0, "state": "pending", "detail": "reading quota", "rows": []}


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    result = refresh(directory) if "--refresh" in sys.argv else cached(directory)
    if result.get("state") == "ok":
        now = int(time.time())
        for key, used, reset in result.get("rows") or []:
            if not reset or reset > now:
                print(key, used, reset, sep="\t")
    else:
        print(result.get("state", "unknown"), result.get("detail", ""), sep="\t")
