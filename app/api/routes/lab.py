from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/lab", tags=["Majestic Lab"])


# ─── Schemas ───────────────────────────────────────────────────────────────────

class InstitutionCreate(BaseModel):
    name: str
    type: str = "Secondary School"
    contact: Optional[str] = None
    licenses: int = 1
    amount_paid: Optional[float] = None
    expires_at: Optional[str] = None   # ISO date string or None

class TokenCreate(BaseModel):
    buyer_name: str
    amount_paid: Optional[float] = None
    hours: int = 24
    institution_id: Optional[str] = None  # None = individual guest
    session_id: Optional[str] = None      # Tutor's active lab session ID for real-time sync
    assignment_id: Optional[str] = None   # Assignment ID (for tutor-student pair validation)

class ValidatePayload(BaseModel):
    device_fingerprint: str

class PingPayload(BaseModel):
    device_fingerprint: str
    institution_id: Optional[str] = None

class WhiteboardSavePayload(BaseModel):
    session_id: str
    page_index: int
    json_data: dict


# ─── ADMIN: Institutions ───────────────────────────────────────────────────────

@router.get("/institutions")
async def list_institutions(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("lab_institutions").select("*").order("created_at", desc=True).execute().data or []

@router.post("/institutions", status_code=201)
async def create_institution(payload: InstitutionCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    data = {
        "name":        payload.name,
        "type":        payload.type,
        "contact":     payload.contact,
        "licenses":    payload.licenses,
        "amount_paid": payload.amount_paid,
        "expires_at":  payload.expires_at,
        "created_by":  admin["id"],
    }
    result = sb.table("lab_institutions").insert(data).execute().data
    return result[0] if result else {}

@router.delete("/institutions/{institution_id}")
async def delete_institution(institution_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("lab_tokens").delete().eq("institution_id", institution_id).execute()
    sb.table("lab_active_sessions").delete().eq("institution_id", institution_id).execute()
    sb.table("lab_institutions").delete().eq("id", institution_id).execute()
    return {"message": "Institution deleted"}


# ─── ADMIN: Guest Tokens ───────────────────────────────────────────────────────

@router.get("/tokens")
async def list_tokens(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("lab_tokens").select("*, lab_institutions(name)").order("created_at", desc=True).execute().data or []

@router.post("/tokens", status_code=201)
async def create_token(payload: TokenCreate, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("admin", "tutor"):
        raise HTTPException(403, "Only tutors and admins can generate lab links")
    
    sb = get_supabase_admin()
    
    # ─── IMPORTANT: Tutors must have at least one active assignment ─────────────
    if current_user.get("role") == "tutor":
        tutor = sb.table("tutors").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
        
        if not tutor:
            raise HTTPException(404, "Tutor profile not found")
        
        # Check if tutor has active assignments
        active_assignments = sb.table("assignments").select("id").eq(
            "tutor_id", tutor["id"]
        ).eq("is_active", True).execute().data or []
        
        if not active_assignments:
            raise HTTPException(
                403,
                "You must be assigned to at least one student before accessing the lab. "
                "Contact an admin to get assigned to a student."
            )
        
        # If assignment_id is provided, verify it belongs to this tutor
        if payload.assignment_id:
            assignment = sb.table("assignments").select("tutor_id").eq(
                "id", payload.assignment_id
            ).single().execute().data
            
            if not assignment or assignment["tutor_id"] != tutor["id"]:
                raise HTTPException(
                    403,
                    "This assignment does not belong to you"
                )
    
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=payload.hours)).isoformat()
    data = {
        "buyer_name":      payload.buyer_name,
        "amount_paid":     payload.amount_paid,
        "expires_at":      expires_at,
        "institution_id":  payload.institution_id,
        "session_id":      payload.session_id,
        "assignment_id":   payload.assignment_id,  # Link token to assignment
        "created_by":      current_user["id"],
    }
    result = sb.table("lab_tokens").insert(data).execute().data
    if not result:
        raise HTTPException(500, "Failed to create token")
    return result[0]  # includes the auto-generated `token` UUID field

@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("lab_tokens").update({"is_revoked": True}).eq("id", token_id).execute()
    return {"message": "Token revoked"}


# ─── PUBLIC: Validate token (called when guest opens the link) ─────────────────

@router.post("/tokens/{token}/validate")
async def validate_token(token: str, payload: ValidatePayload):
    sb = get_supabase_admin()

    # Fetch token record
    try:
        record = sb.table("lab_tokens").select(
            "*, lab_institutions(id, name, licenses)"
        ).eq("token", token).single().execute().data
    except Exception:
        raise HTTPException(404, "This link is invalid or has been revoked.")

    if record["is_revoked"]:
        raise HTTPException(403, "This access link has been revoked. Please contact Mathrone Academy.")

    # Check expiry
    expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(403, "This access link has expired. Please contact Mathrone Academy.")

    # Device lock: only the FIRST device that calls this endpoint gets access
    if not record["device_fingerprint"]:
        # First device — lock it now
        sb.table("lab_tokens").update(
            {"device_fingerprint": payload.device_fingerprint}
        ).eq("token", token).execute()
    elif record["device_fingerprint"] != payload.device_fingerprint:
        raise HTTPException(403, "This link has already been activated on another device. Each link is single-device only.")

    # Concurrency check for institution tokens
    inst = record.get("lab_institutions")
    if inst:
        # Clean up stale pings first
        sb.rpc("cleanup_stale_lab_sessions").execute()

        active = sb.table("lab_active_sessions").select("id").eq(
            "institution_id", inst["id"]
        ).execute().data or []

        # Check if this device already has a session (re-join allowed)
        my_session = sb.table("lab_active_sessions").select("id").eq(
            "token", token
        ).eq("device_fingerprint", payload.device_fingerprint).execute().data

        if not my_session and len(active) >= inst["licenses"]:
            raise HTTPException(
                403,
                f"Your institution ({inst['name']}) has reached the limit of "
                f"{inst['licenses']} active lab(s). Please ask a colleague to "
                f"close their session, or contact Mathrone Academy to upgrade."
            )

    return {
        "valid": True,
        "buyer_name": record["buyer_name"],
        "institution_id": inst["id"] if inst else None,
        "institution_name": inst["name"] if inst else None,
        "session_id": record.get("session_id"),
    }


# ─── PUBLIC: Ping (keep-alive, called every 3 min while lab is open) ──────────

@router.post("/tokens/{token}/ping")
async def ping_session(token: str, payload: PingPayload):
    sb = get_supabase_admin()
    if not payload.institution_id:
        return {"ok": True}  # Individual guest — no concurrency tracking needed

    # Upsert the session ping
    sb.table("lab_active_sessions").upsert({
        "token":              token,
        "institution_id":     payload.institution_id,
        "device_fingerprint": payload.device_fingerprint,
        "last_ping":          datetime.now(timezone.utc).isoformat(),
    }, on_conflict="token,device_fingerprint").execute()

    return {"ok": True}


# ─── PUBLIC: End session (called when teacher clicks "Exit") ──────────────────

@router.delete("/tokens/{token}/session")
async def end_session(token: str, payload: PingPayload):
    sb = get_supabase_admin()
    sb.table("lab_active_sessions").delete().eq("token", token).eq(
        "device_fingerprint", payload.device_fingerprint
    ).execute()
    return {"ok": True}


# ─── ADMIN: View active sessions per institution ───────────────────────────────

@router.get("/institutions/{institution_id}/active")
async def get_active_sessions(institution_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.rpc("cleanup_stale_lab_sessions").execute()
    active = sb.table("lab_active_sessions").select("*").eq(
        "institution_id", institution_id
    ).execute().data or []
    return {"active_count": len(active), "sessions": active}
# ─── WHITEBOARD: Save and Load (Fixes the 404 errors) ──────────────────────────

@router.post("/whiteboard/save")
async def save_whiteboard(payload: WhiteboardSavePayload):
    sb = get_supabase_admin()
    data = {
        "session_id": payload.session_id,
        "page_index": payload.page_index,
        "json_data":  payload.json_data,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    # This matches the names used in your index.html fetch call
    sb.table("lab_whiteboard_pages").upsert(data, on_conflict="session_id,page_index").execute()
    return {"ok": True}

@router.get("/whiteboard/{session_id}")
async def get_whiteboard(session_id: str):
    sb = get_supabase_admin()
    # This fetches the saved drawings when you refresh the page
    result = sb.table("lab_whiteboard_pages").select("json_data").eq("session_id", session_id).order("page_index").execute()
    return result.data or []