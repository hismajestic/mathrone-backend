from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from app.schemas.schemas import (
    TutorUpdate, TutorStatusUpdate,
    PaginatedResponse, MessageResponse,
)
from app.core.security import get_current_user, require_admin, require_tutor
from app.db.supabase import get_supabase_admin
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService
import math

from fastapi import UploadFile, File
from typing import List
router = APIRouter(prefix="/tutors", tags=["Tutors"])


# ── Public / tutor-facing ──────────────────────────────────────────────────────

@router.get("/search", response_model=PaginatedResponse)
async def search_tutors(
    subject:    Optional[str]   = Query(None),
    level:      Optional[str]   = Query(None),
    mode:       Optional[str]   = Query(None),
    location:   Optional[str]   = Query(None),
    min_rating: Optional[float] = Query(None),
    max_rate:   Optional[float] = Query(None),
    page:       int             = Query(1, ge=1),
    limit:      int             = Query(12, ge=1, le=50),
    current_user: dict          = Depends(get_current_user),
):
    """Search approved, available tutors with optional filters."""
    sb = get_supabase_admin()
    q  = sb.table("tutors").select(
        "*, profiles!tutors_profile_id_fkey(id, full_name, email, avatar_url, phone)"
    ).eq("status", "approved").eq("is_available", True)

    if subject:
        q = q.contains("subjects", [subject])
    if level:
        q = q.contains("levels", [level])
    if mode:
        q = q.contains("teaching_modes", [mode])
    if min_rating:
        q = q.gte("rating", min_rating)
    if max_rate:
        q = q.lte("hourly_rate", max_rate)

    all_results = q.order("rating", desc=True).execute().data

    # Filter out already assigned tutors for students
    if current_user.get("role") == "student":
        try:
            student = sb.table("students").select("id").eq(
                "profile_id", current_user["id"]
            ).single().execute().data
            if student:
                assignments = sb.table("assignments").select("tutor_id").eq(
                    "student_id", student["id"]
                ).eq("is_active", True).execute().data
                assigned_tutor_ids = [a["tutor_id"] for a in assignments]
                all_results = [t for t in all_results if t["id"] not in assigned_tutor_ids]
        except Exception:
            pass

    total  = len(all_results)
    offset = (page - 1) * limit
    paged  = all_results[offset: offset + limit]

    return PaginatedResponse(
        data=paged,
        total=total,
        page=page,
        limit=limit,
        pages=math.ceil(total / limit) if total else 1,
    )


@router.get("/me")
async def get_my_tutor_profile(current_user: dict = Depends(require_tutor)):
    """Authenticated tutor: get own full profile."""
    sb = get_supabase_admin()
    try:
        tutor = sb.table("tutors").select("*").eq("profile_id", current_user["id"]).single().execute()
    except Exception:
        raise HTTPException(404, "Tutor profile not found")
    if not tutor.data:
        raise HTTPException(404, "Tutor profile not found")
    return {**tutor.data, "profile": current_user}


@router.patch("/me", response_model=MessageResponse)
async def update_my_profile(
    payload: TutorUpdate,
    current_user: dict = Depends(require_tutor),
):
    """Tutor updates their own profile fields."""
    sb = get_supabase_admin()
    update_data = payload.model_dump(exclude_none=True)
    if update_data:
        sb.table("tutors").update(update_data).eq("profile_id", current_user["id"]).execute()
    return MessageResponse(message="Profile updated successfully")


@router.post("/me/upload-cv", response_model=MessageResponse)
async def upload_cv(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_tutor),
):
    """Upload or replace tutor CV in Supabase Storage."""
    url = await StorageService.upload_cv(file, current_user["id"])
    sb  = get_supabase_admin()
    sb.table("tutors").update({"cv_url": url}).eq("profile_id", current_user["id"]).execute()
    return MessageResponse(message="CV uploaded successfully")


@router.post("/me/upload-certificate", response_model=MessageResponse)
async def upload_certificate(
    file: UploadFile = File(...),
    current_user: dict = Depends(require_tutor),
):
    """Upload a certificate and append its URL to the tutor's list."""
    url = await StorageService.upload_certificate(file, current_user["id"])
    sb  = get_supabase_admin()
    try:
        tutor = sb.table("tutors").select("certificate_urls").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
        existing = tutor.get("certificate_urls") or []
    except Exception:
        existing = []
    sb.table("tutors").update({"certificate_urls": existing + [url]}).eq(
        "profile_id", current_user["id"]
    ).execute()
    return MessageResponse(message="Certificate uploaded successfully")



# ── Admin routes — MUST come before /{tutor_id} to avoid route shadowing ──────

@router.get("/admin/applications", tags=["Admin"])
async def list_applications(
    status: Optional[str] = Query(None),
    admin  = Depends(require_admin),
):
    """Admin: list tutor applications filtered by pipeline stage."""
    sb = get_supabase_admin()
    q  = sb.table("tutors").select("*, profiles!tutors_profile_id_fkey(id, full_name, email, phone)")
    if status:
        q = q.eq("status", status)
    else:
        q = q.in_("status", ["applicant", "under_review", "written_exam", "interview"])
    return q.order("created_at", desc=True).execute().data


class TutorStatusUpdate(BaseModel):
    status: str
    written_exam_score: Optional[int] = None
    interview_score: Optional[int] = None
    rejection_reason: Optional[str] = None
    salary_amount: Optional[float] = None
    salary_frequency: Optional[str] = None
    admin_notes: Optional[str] = None
    exam_code: Optional[str] = None
    exam_time_minutes: Optional[int] = None

@router.patch("/admin/{tutor_id}/status")
async def update_tutor_status(
    tutor_id: str,
    payload: TutorStatusUpdate,
    
    admin: dict = Depends(require_admin)
):
    from app.api.routes.auth import send_recruitment_email
    sb = get_supabase_admin()

    # Get tutor profile
    tutor = sb.table("tutors").select("*, profiles!tutors_profile_id_fkey(full_name, email)").eq("id", tutor_id).single().execute().data
    if not tutor:
        raise HTTPException(404, "Tutor not found")

    name  = tutor["profiles"]["full_name"]
    email = tutor["profiles"]["email"]

    # Build update data
    update_data = { "status": payload.status }
    if payload.written_exam_score is not None:
        update_data["written_exam_score"] = payload.written_exam_score
    if payload.interview_score is not None:
        update_data["interview_score"] = payload.interview_score
    if payload.rejection_reason is not None:
        update_data["rejection_reason"] = payload.rejection_reason
    if payload.salary_amount is not None:
        update_data["salary_amount"] = payload.salary_amount
    if payload.salary_frequency is not None:
        update_data["salary_frequency"] = payload.salary_frequency
    if payload.admin_notes is not None:
        update_data["admin_notes"] = payload.admin_notes
    if payload.exam_code is not None:
        update_data["exam_code"] = payload.exam_code.upper()
    if payload.exam_time_minutes is not None:
        update_data["exam_time_minutes"] = payload.exam_time_minutes

    sb.table("tutors").update(update_data).eq("id", tutor_id).execute()

    # Send recruitment email
    score = payload.written_exam_score or payload.interview_score
    await send_recruitment_email(email, name, payload.status, score, payload.rejection_reason)

    # Send in-app notification
    try:
        from app.services.notification_service import NotificationService
        messages = {
            "under_review":  "Your application is now under review",
            "written_exam":  "You have been invited to take a written exam — log in to start",
            "interview":     "Congratulations! You are invited for an interview",
            "approved":      "You are approved as a Mathrone Academy tutor!",
            "rejected":      "Update on your Mathrone Academy application",
        }
        if payload.status in messages:
            await NotificationService.create(
                tutor["profile_id"], "recruitment",
                f"Application Update: {payload.status.replace('_',' ').title()}",
                messages[payload.status], sb
            )
    except Exception as e:
        print(f"Notification error: {e}")

    return { "message": f"Status updated to {payload.status} and email sent" }

@router.get("/admin/all", tags=["Admin"])
async def list_all_tutors(admin = Depends(require_admin)):
    """Admin: list all tutors (all statuses)."""
    sb = get_supabase_admin()
    return sb.table("tutors").select(
        "id, profile_id, status, subjects, levels, rating, total_sessions, created_at, "
        "profiles!tutors_profile_id_fkey(id, full_name, email, phone)"
    ).order("created_at", desc=True).execute().data


# ── Public profile by ID — keep LAST to avoid shadowing /admin/* routes ───────

@router.get("/{tutor_id}")
async def get_tutor(tutor_id: str):
    """Public: get an approved tutor's profile by ID."""
    sb = get_supabase_admin()
    try:
        result = sb.table("tutors").select(
            "*, profiles!tutors_profile_id_fkey(id, full_name, email, avatar_url)"
        ).eq("id", tutor_id).eq("status", "approved").single().execute()
    except Exception:
        raise HTTPException(404, "Tutor not found")
    if not result.data:
        raise HTTPException(404, "Tutor not found")
    return result.data
@router.post("/upload-docs")
async def upload_tutor_docs(
    cv: UploadFile = File(...),
    certificates: List[UploadFile] = File(default=[]),
    current_user: dict = Depends(get_current_user)
):
    sb = get_supabase_admin()
    uid = current_user["id"]

    # Get tutor record id
    tutor = sb.table("tutors").select("id").eq("profile_id", uid).single().execute().data
    if not tutor:
        raise HTTPException(404, "Tutor record not found")
    tutor_id = tutor["id"]

    # Upload CV to storage
    cv_bytes = await cv.read()
    cv_path = f"tutors/{uid}/cv_{cv.filename}"
    sb.storage.from_("documents").upload(cv_path, cv_bytes, {"content-type": cv.content_type, "upsert": "true"})
    cv_url = sb.storage.from_("documents").get_public_url(cv_path)

    # Save CV to documents table
    sb.table("documents").upsert({
        "tutor_id":  tutor_id,
        "file_name": cv.filename,
        "file_type": "cv",
        "file_url":  cv_url
    }, on_conflict="tutor_id,file_type" if False else None).execute()

    # Delete old CV record and insert new one
    sb.table("documents").delete().eq("tutor_id", tutor_id).eq("file_type", "cv").execute()
    sb.table("documents").insert({
        "tutor_id":  tutor_id,
        "file_name": cv.filename,
        "file_type": "cv",
        "file_url":  cv_url
    }).execute()

    # Upload certificates
    for cert in certificates:
        cert_bytes = await cert.read()
        cert_path = f"tutors/{uid}/cert_{cert.filename}"
        sb.storage.from_("documents").upload(cert_path, cert_bytes, {"content-type": cert.content_type, "upsert": "true"})
        cert_url = sb.storage.from_("documents").get_public_url(cert_path)
        sb.table("documents").insert({
            "tutor_id":  tutor_id,
            "file_name": cert.filename,
            "file_type": "certificate",
            "file_url":  cert_url
        }).execute()

    # Update cv_url on tutor record for quick access
    sb.table("tutors").update({"cv_url": cv_url}).eq("profile_id", uid).execute()

    return {"message": "Documents uploaded successfully ✅", "cv_url": cv_url}

@router.get("/{tutor_id}/documents")
async def get_tutor_documents(
    tutor_id: str,
    current_user: dict = Depends(get_current_user)
):
    sb = get_supabase_admin()
    docs = sb.table("documents").select("*").eq("tutor_id", tutor_id).order("uploaded_at", desc=True).execute().data
    return docs or []

class PaymentPreference(BaseModel):
    payment_method:  str
    payment_details: str

@router.patch("/me/payment-preference", response_model=MessageResponse)
async def update_payment_preference(
    payload: PaymentPreference,
    current_user: dict = Depends(require_tutor),
):
    sb = get_supabase_admin()
    sb.table("tutors").update({
        "payment_method":  payload.payment_method,
        "payment_details": payload.payment_details,
    }).eq("profile_id", current_user["id"]).execute()
    return MessageResponse(message="Payment preference updated")
@router.post("/upload-avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    contents = await file.read()
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['jpg','jpeg','png','webp']:
        raise HTTPException(400, "Only JPG, PNG or WebP images allowed")
    path = f"avatars/{current_user['id']}.{ext}"
    sb.storage.from_("avatars").upload(
        path, contents,
        file_options={"content-type": file.content_type, "upsert": "true"}
    )
    url = sb.storage.from_("avatars").get_public_url(path)
    sb.table("profiles").update({"avatar_url": url}).eq("id", current_user["id"]).execute()
    return {"avatar_url": url}
@router.delete("/admin/{tutor_id}")
async def delete_tutor(
    tutor_id: str,
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    tutor = sb.table("tutors").select("profile_id").eq("id", tutor_id).single().execute().data
    if not tutor:
        raise HTTPException(404, "Tutor not found")
    sb.table("assignments").delete().eq("tutor_id", tutor_id).execute()
    sb.table("documents").delete().eq("tutor_id", tutor_id).execute()
    sb.table("tutors").delete().eq("id", tutor_id).execute()
    sb.auth.admin.delete_user(tutor["profile_id"])
    return {"message": "Tutor deleted successfully"}