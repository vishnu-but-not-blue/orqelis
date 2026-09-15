from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Orqelis"
    environment: str = "local"
    database_url: str = "sqlite:///./var/orqelis.db"
    base_url: str = "http://127.0.0.1:8000"
    secret_key: str = ""
    storage_path: Path = Path("var/objects")
    auth_provider: str = "local"
    storage_provider: str = "local"
    max_upload_bytes: int = 10 * 1024 * 1024
    document_uploads_enabled: bool = True
    document_processing_enabled: bool = True
    session_hours: int = 12
    ted_enabled: bool = True
    ted_requests_per_minute: int = 12
    ted_concurrency: int = 2
    ted_query: str = "publication-date >= 20260901"
    malware_command: str = ""
    legal_entity: str = ""
    legal_address: str = ""
    legal_contact: str = ""
    legal_jurisdiction: str = ""
    legal_review_complete: bool = False
    backups_verified: bool = False
    billing_provider: str = "disabled"
    billing_api_key: str = ""
    billing_webhook_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = ""
    retention_days: int = 30
    internal_token: str = ""
    backup_key: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_project_ref: str = ""
    supabase_region: str = ""
    supabase_storage_bucket: str = "documents"
    plans_json: str = '{"FREE":{"analyses":20,"documents":20,"members":3},"SME":{"analyses":300,"documents":200,"members":10},"PRO":{"analyses":1000,"documents":1000,"members":30},"ADVISOR":{"analyses":2000,"documents":2000,"members":50}}'

    def validate_deployment(self):
        if self.auth_provider not in {"local", "supabase"} or self.storage_provider not in {
            "local",
            "supabase",
        }:
            raise RuntimeError("Unsupported identity or storage provider")
        if self.environment == "production":
            required = [
                "secret_key",
                "legal_entity",
                "legal_address",
                "legal_contact",
                "legal_jurisdiction",
                "malware_command",
            ]
            missing = [key for key in required if not getattr(self, key)]
            if len(self.secret_key) < 32:
                missing.append("secret_key (at least 32 characters)")
            if self.auth_provider == "local":
                missing.append("production identity provider (local auth is development only)")
            elif self.auth_provider == "supabase" and not (
                self.supabase_url and self.supabase_anon_key
            ):
                missing.append("Supabase Auth configuration (supabase_url, supabase_anon_key)")
            if self.storage_provider == "supabase" and not (
                self.supabase_url and self.supabase_service_role_key
            ):
                missing.append(
                    "Supabase Storage configuration (supabase_url, supabase_service_role_key)"
                )
            if not self.database_url.startswith("postgresql"):
                missing.append("PostgreSQL database_url")
            if not self.base_url.startswith("https://"):
                missing.append("HTTPS base_url")
            if not self.legal_review_complete or not self.backups_verified:
                missing.append("legal review and restore-tested backups")
            if missing:
                raise RuntimeError("Production release blocked: " + ", ".join(missing))


@lru_cache
def settings():
    return Settings()
