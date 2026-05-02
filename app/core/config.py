from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Mathrone Academy"
    app_version: str = "1.0.0"
    debug: bool = True
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5500,http://localhost:5500,http://localhost:8080,http://127.0.0.1:8080,http://localhost:8000,http://127.0.0.1:8000"

    # Supabase — REQUIRED (must be in .env)
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # JWT
    secret_key: str = "change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Email — Using Resend API for 100% Reliability
    resend_api_key: str = "" # Set this in your .env file
    from_email: str = "contact.mathroneacademy.com" # Change to your domain email after verifying DNS
    from_name: str = "Mathrone Academy"

    # Storage buckets — must match bucket names you created in Supabase
    storage_bucket_cvs: str = "tutor-cvs"
    storage_bucket_certs: str = "tutor-certificates"
    storage_bucket_avatars: str = "avatars"
    storage_bucket_materials: str = "session-materials"
    max_upload_size_mb: int = 10

    # AI — Groq (free tier)
    gemini_api_key: str = ""  # kept for backwards compat
    groq_api_key: str = ""

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()