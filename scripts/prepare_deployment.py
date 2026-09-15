"""Create private production configuration; never print secrets or invent approvals."""

import json
import secrets
from pathlib import Path

from dotenv import dotenv_values, set_key

from app.config import Settings


def main():
    destination = Path("var/deploy.env")
    destination.parent.mkdir(exist_ok=True)
    if destination.exists():
        print("Existing var/deploy.env retained.")
        return
    allowed = {name.upper() for name in Settings.model_fields}
    values = {k: v for k, v in dotenv_values(".env").items() if k in allowed and v}
    values.update(
        {
            "ENVIRONMENT": "production",
            "BASE_URL": "https://orqelis.pro",
            "AUTH_PROVIDER": "supabase",
            "STORAGE_PROVIDER": "supabase",
            "BILLING_PROVIDER": "disabled",
            "MALWARE_COMMAND": "clamscan --database=/app/var/clamav --no-summary --max-filesize=10M --max-scansize=50M --alert-exceeds-max=yes",
        }
    )
    for name in ["SECRET_KEY", "INTERNAL_TOKEN", "BACKUP_KEY"]:
        values.setdefault(name, secrets.token_hex(32))
    for name in ["LEGAL_REVIEW_COMPLETE", "BACKUPS_VERIFIED"]:
        values.setdefault(name, "false")
    for name in ["LEGAL_ENTITY", "LEGAL_ADDRESS", "LEGAL_CONTACT", "LEGAL_JURISDICTION"]:
        values.setdefault(name, "")
    destination.touch(mode=0o600)
    for name, value in values.items():
        set_key(destination, name, value)
    print(
        json.dumps(
            {
                "file": str(destination),
                "secrets_printed": False,
                "missing_operator_fields": [
                    k for k, v in values.items() if k.startswith("LEGAL_") and not v
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
