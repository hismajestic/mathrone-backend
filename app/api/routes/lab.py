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
    if current_user.get("role") not in ("admin", "tutor", "institution_admin"):
        raise HTTPException(403, "Only admins, tutors, or institution admins can generate lab links")
    
    sb = get_supabase_admin()

    # ─── INSTITUTION ADMIN: Can only generate links for their own institution ───
    if current_user.get("role") == "institution_admin":
        # Fetch which institution this admin belongs to
        inst_membership = sb.table("institution_admins").select("institution_id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data

        if not inst_membership:
            raise HTTPException(403, "You are not linked to any institution.")

        their_inst_id = inst_membership["institution_id"]

        # Verify the institution's subscription is still valid
        inst = sb.table("lab_institutions").select("id, name, licenses, expires_at").eq(
            "id", their_inst_id
        ).single().execute().data
        if not inst:
            raise HTTPException(404, "Institution not found.")

        if inst.get("expires_at"):
            from datetime import datetime, timezone
            inst_expires = datetime.fromisoformat(inst["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > inst_expires:
                raise HTTPException(403, f"Your institution's subscription has expired. Contact Mathrone to renew.")

        # Force the institution_id to be their own — they cannot generate links for other institutions
        payload.institution_id = their_inst_id

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

    # 1. Fetch token and check fundamental status
    try:
        record = sb.table("lab_tokens").select(
            "*, lab_institutions(id, name, licenses, expires_at)"
        ).eq("token", token).single().execute().data
    except Exception:
        raise HTTPException(404, "Invalid or unrecognized access link.")

    if record["is_revoked"]:
        raise HTTPException(403, "This access link has been revoked by Mathrone Admin.")

    # 2. Check Expiry (Token Level)
    expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(403, "Your access period has expired. Please renew your subscription.")

    # 3. INDIVIDUAL PROTECTION (Device Locking)
    # If no institution is linked, this is a private purchase. Lock it to the first device.
    if not record["institution_id"]:
        if record["device_fingerprint"] and record["device_fingerprint"] != payload.device_fingerprint:
            raise HTTPException(403, "Security Alert: This link is already registered to a different device. Sharing is prohibited.")
        
        if not record["device_fingerprint"]:
            sb.table("lab_tokens").update({"device_fingerprint": payload.device_fingerprint}).eq("token", token).execute()

    # 4. INSTITUTION PROTECTION (License Seat Management)
    if record["institution_id"]:
        inst = record["lab_institutions"]
        
        # Check if school subscription itself is expired
        if inst["expires_at"]:
            inst_expires = datetime.fromisoformat(inst["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > inst_expires:
                raise HTTPException(403, f"The subscription for {inst['name']} has expired. Please contact your administrator.")

        # Clean stale sessions before checking limits
        sb.rpc("cleanup_stale_lab_sessions").execute()

        # Count active seats for this school
        active_res = sb.table("lab_active_sessions").select("id", count="exact").eq("institution_id", inst["id"]).execute()
        active_count = active_res.count or 0

        # Check if THIS specific device is already counted (Allow re-entry/refresh)
        my_session = sb.table("lab_active_sessions").select("id").eq("token", token).eq("device_fingerprint", payload.device_fingerprint).execute().data

        if not my_session and active_count >= inst["licenses"]:
            raise HTTPException(403, f"License Limit Reached: {inst['name']} is allowed {inst['licenses']} concurrent session(s). All seats are currently full.")

    # Determine if this user should have Host privileges
    # A host is either the person who created the token or anyone using an Institutional link 
    # that is recognized as the 'Primary Device'.
    is_host_privilege = False
    if not record["institution_id"]:
        # Individual B2C: Only the first locked device is the Host
        if record["device_fingerprint"] == payload.device_fingerprint:
            is_host_privilege = True
    else:
        # B2B Institution: For simplicity in classrooms, we check if they 
        # opened it with the intent to host (this can be expanded later)
        is_host_privilege = True 

    return {
        "valid": True,
        "buyer_name": record["buyer_name"],
        "institution_id": record["institution_id"],
        "institution_name": record["lab_institutions"]["name"] if record["institution_id"] else "Mathrone Business Partner",
        "session_id": record.get("session_id"),
        "is_host": is_host_privilege 
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


# ─── INSTITUTION ADMIN: Self-service portal endpoints ─────────────────────────

@router.get("/my-institution")
async def get_my_institution(current_user: dict = Depends(get_current_user)):
    """Institution admin sees their own institution + active session count."""
    if current_user.get("role") not in ("admin", "institution_admin"):
        raise HTTPException(403, "Not authorized")
    sb = get_supabase_admin()

    if current_user.get("role") == "institution_admin":
        membership_res = sb.table("institution_admins").select("institution_id").eq(
            "profile_id", current_user["id"]
        ).execute()
        
        if not membership_res.data:
            raise HTTPException(403, "Access Denied: Your account is not linked to any School/Institution yet. Please contact Mathrone Admin.")
            
        inst_id = membership_res.data[0]["institution_id"]
    else:
        # Admin can pass ?institution_id= query param — handled via tokens list
        raise HTTPException(400, "Use /lab/institutions for admin access")

    inst = sb.table("lab_institutions").select("*").eq("id", inst_id).single().execute().data
    if not inst:
        raise HTTPException(404, "Institution not found")

    sb.rpc("cleanup_stale_lab_sessions").execute()
    active_res = sb.table("lab_active_sessions").select("id", count="exact").eq("institution_id", inst_id).execute()
    inst["active_sessions"] = active_res.count or 0
    return inst


@router.get("/my-institution/tokens")
async def get_my_institution_tokens(current_user: dict = Depends(get_current_user)):
    """Institution admin sees all tokens they've generated."""
    if current_user.get("role") not in ("admin", "institution_admin"):
        raise HTTPException(403, "Not authorized")
    sb = get_supabase_admin()

    membership = sb.table("institution_admins").select("institution_id").eq(
        "profile_id", current_user["id"]
    ).single().execute().data
    if not membership:
        raise HTTPException(404, "Not linked to any institution.")

    tokens = sb.table("lab_tokens").select("*").eq(
        "institution_id", membership["institution_id"]
    ).order("created_at", desc=True).execute().data or []
    return tokens


@router.delete("/my-institution/tokens/{token_id}")
async def revoke_my_token(token_id: str, current_user: dict = Depends(get_current_user)):
    """Institution admin can revoke their own tokens only."""
    if current_user.get("role") not in ("admin", "institution_admin"):
        raise HTTPException(403, "Not authorized")
    sb = get_supabase_admin()

    if current_user.get("role") == "institution_admin":
        membership = sb.table("institution_admins").select("institution_id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
        # Verify this token belongs to their institution before revoking
        token_rec = sb.table("lab_tokens").select("institution_id").eq("id", token_id).single().execute().data
        if not token_rec or token_rec["institution_id"] != membership["institution_id"]:
            raise HTTPException(403, "This token does not belong to your institution.")

    sb.table("lab_tokens").update({"is_revoked": True}).eq("id", token_id).execute()
    return {"message": "Token revoked"}
class LinkInstAdminRequest(BaseModel):
    email: str
    password: str
    full_name: str
    institution_id: str

@router.post("/admin/create-institution-admin", tags=["Admin"])
async def create_inst_admin(payload: LinkInstAdminRequest, admin: dict = Depends(require_admin)):
    from app.api.routes.auth import _create_user_via_supabase, _wait_for_profile
    sb = get_supabase_admin()
    
    # 1. Create the Auth User
    auth_resp = _create_user_via_supabase(payload.email, payload.password, payload.full_name, "institution_admin")
    user_id = auth_resp.user.id
    
    # 2. Ensure profile exists and has the correct role
    _wait_for_profile(sb, user_id)
    sb.table("profiles").update({"role": "institution_admin", "is_verified": True}).eq("id", user_id).execute()
    
    # 3. Link them to the school
    sb.table("institution_admins").insert({
        "profile_id": user_id,
        "institution_id": payload.institution_id
    }).execute()
    
    return {"message": f"Institution Admin {payload.full_name} created successfully!"}