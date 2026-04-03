from supabase import create_client, Client
from app.core.config import settings

# Module-level singletons — created once on first import
_supabase_client: Client | None = None
_supabase_admin_client: Client | None = None


def get_supabase() -> Client:
    """Anon client — respects RLS. Used for user-facing auth operations."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_anon_key,
        )
    return _supabase_client


def get_supabase_admin() -> Client:
    """Service-role client — bypasses RLS. Used for all DB operations in routes."""
    global _supabase_admin_client
    if _supabase_admin_client is None:
        _supabase_admin_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _supabase_admin_client


# FastAPI dependency aliases
def get_db() -> Client:
    return get_supabase()


def get_admin_db() -> Client:
    return get_supabase_admin()