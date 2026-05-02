from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # App
    app_name: str = "Mathrone Academy"
    app_version: str = "1.0.0"
    debug: bool = True
    allowed_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:8000"

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

   # JWT
    secret_key: str = "temporary-dev-secret-key-change-this-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    # Email Settings (Pulled from .env)
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    from_email: str
    from_name: str

    # AI
    groq_api_key: str

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()