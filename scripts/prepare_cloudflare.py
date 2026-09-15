"""Prepare private Worker configuration and optionally provision a free Hyperdrive binding."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hyperdrive", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = Settings()
    private = root / "var" / "cloudflare-secrets.json"
    private.parent.mkdir(exist_ok=True)
    previous = json.loads(private.read_text()) if private.exists() else {}
    values = {
        "SUPABASE_URL": config.supabase_url,
        "SUPABASE_ANON_KEY": config.supabase_anon_key,
        "SUPABASE_SERVICE_ROLE_KEY": config.supabase_service_role_key,
        "PREVIEW_ALLOWED_EMAILS": previous.get(
            "PREVIEW_ALLOWED_EMAILS", "srivishnupriyan24@gmail.com"
        ),
    }
    for key in ("BASE_URL", "INTERNAL_TOKEN"):
        if previous.get(key):
            values[key] = previous[key]
    private.write_text(json.dumps(values), encoding="utf-8")
    print("Prepared ignored var/cloudflare-secrets.json; no secrets printed.")
    if args.hyperdrive:
        wrangler = root / "cloudflare" / "wrangler.jsonc"
        deployment = json.loads(wrangler.read_text())
        if deployment.get("hyperdrive"):
            print("Existing Hyperdrive binding retained.")
            return
        url = make_url(config.database_url).set(drivername="postgresql")
        process = subprocess.run(
            [
                "node",
                "node_modules/wrangler/bin/wrangler.js",
                "hyperdrive",
                "create",
                "orqelis-supabase",
                "--connection-string",
                url.render_as_string(hide_password=False),
                "--caching-disabled",
                "--origin-connection-limit",
                "5",
                "--sslmode",
                "require",
            ],
            cwd=root / "cloudflare",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        if process.returncode:
            print("Hyperdrive creation failed; provider output withheld to protect credentials.")
            raise SystemExit(1)
        match = re.search(r'"id"\s*:\s*"([a-f0-9]{32})"', process.stdout)
        if not match:
            print(
                "Creation returned without a parsable binding ID; inspect Hyperdrive list before retrying."
            )
            raise SystemExit(1)
        deployment["hyperdrive"] = [{"binding": "DB", "id": match[1]}]
        wrangler.write_text(json.dumps(deployment, indent=2) + "\n", encoding="utf-8")
        print(
            "Created free Hyperdrive configuration pointing to existing Supabase; no database created."
        )


if __name__ == "__main__":
    main()
