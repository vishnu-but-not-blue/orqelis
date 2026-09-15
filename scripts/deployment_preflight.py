"""Read-only deployment diagnostics. Never print connection strings or credentials."""

import json
import socket

import httpx
from sqlalchemy import create_engine, text

from app.config import Settings


def main():
    config = Settings()
    report = {
        "domain": "orqelis.pro",
        "configured_auth": config.auth_provider,
        "configured_storage": config.storage_provider,
    }
    try:
        report["dns_addresses"] = sorted({r[4][0] for r in socket.getaddrinfo("orqelis.pro", 443)})
    except OSError:
        report["dns_addresses"] = []
    candidate = config.model_copy(
        update={
            "environment": "production",
            "base_url": "https://orqelis.pro",
            "auth_provider": "supabase",
            "storage_provider": "supabase",
        }
    )
    try:
        candidate.validate_deployment()
        report["production_config"] = "PASS"
    except RuntimeError as error:
        report["production_config"] = str(error)
    try:
        engine = create_engine(
            config.database_url, connect_args={"connect_timeout": 10}, pool_pre_ping=True
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            report["database_connection"] = "PASS"
            report["app_tables_without_rls"] = list(
                connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('users','organizations','documents','evidence','opportunity_analyses','sessions','memberships') AND NOT rowsecurity"
                    )
                ).scalars()
            )
            report["storage_policy_count"] = connection.execute(
                text(
                    "SELECT count(*) FROM pg_policies WHERE schemaname='storage' AND tablename='objects'"
                )
            ).scalar()
            report["migration_table_present"] = connection.execute(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            ).scalar()
        engine.dispose()
    except Exception as error:
        report["database_connection"] = type(error).__name__
    try:
        response = httpx.get(
            config.supabase_url.rstrip("/")
            + "/storage/v1/bucket/"
            + config.supabase_storage_bucket,
            headers={
                "apikey": config.supabase_service_role_key,
                "Authorization": "Bearer " + config.supabase_service_role_key,
            },
            timeout=15,
        )
        report["storage_bucket_status"] = response.status_code
        if response.status_code == 200:
            report["storage_bucket_private"] = response.json().get("public") is False
    except Exception as error:
        report["storage_bucket_status"] = type(error).__name__
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
