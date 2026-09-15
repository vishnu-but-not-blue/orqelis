"""Print only application log messages and timings, never request headers or tokens."""
import json
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.Popen(
        ["node", "node_modules/wrangler/bin/wrangler.js", "tail", "orqelis", "--format", "json"],
        cwd=root / "cloudflare", stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace",
    )
    buffer = ""
    try:
        for line in proc.stdout:
            if not buffer and not line.lstrip().startswith("{"):
                continue
            buffer += line
            try:
                event = json.loads(buffer)
            except json.JSONDecodeError:
                continue
            buffer = ""
            # Application deliberately logs only statuses, error codes and stack locations.
            safe = {k: event.get(k) for k in ("outcome", "cpuTime", "wallTime")}
            safe["messages"] = [entry.get("message") for entry in event.get("logs", [])]
            safe["status"] = event.get("event", {}).get("response", {}).get("status")
            print(json.dumps(safe), flush=True)
    finally:
        proc.terminate()


if __name__ == "__main__":
    main()
