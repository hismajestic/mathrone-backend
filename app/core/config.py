from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Mathrone Academy"
    app_version: str = "1.0.0"
    debug: bool = True
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5500,http://localhost:5500"

    # Supabase — REQUIRED (must be in .env)
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # JWT
    secret_key: str = "change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Email (optional — leave blank to skip)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    from_email: str = "noreply@tutorconnect.academy"
    from_name: str = "Mathrone Academy"

    # Storage buckets — must match bucket names you created in Supabase
    storage_bucket_cvs: str = "tutor-cvs"
    storage_bucket_certs: str = "tutor-certificates"
    storage_bucket_avatars: str = "avatars"
    storage_bucket_materials: str = "session-materials"
    max_upload_size_mb: int = 10

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()