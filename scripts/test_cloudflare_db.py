"""Run rollback-only Worker integration tests without putting a DB password on the command line."""

import os
import subprocess
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import Settings


def main():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["CF_TEST_DATABASE_URL"] = (
        make_url(Settings().database_url)
        .set(drivername="postgresql")
        .render_as_string(hide_password=False)
    )
    result = subprocess.run(
        ["node", "--test", "test/integration.test.mjs"],
        cwd=root / "cloudflare",
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    # Node assertions concern synthetic data only; redact the URL if a driver includes it.
    output = (result.stdout + result.stderr).replace(env["CF_TEST_DATABASE_URL"], "[REDACTED]")
    password = make_url(Settings().database_url).password
    if password:
        output = output.replace(password, "[REDACTED]")
    (root / "var" / "cloudflare-integration-results.txt").write_text(output, encoding="utf-8")
    print(output.encode("ascii", "backslashreplace").decode("ascii"))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
