from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.core.security import get_current_user, require_admin, require_tutor
from app.db.supabase import get_supabase_admin
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/progress", tags=["Progress"])

class ProgressCreate(BaseModel):
    session_id:   str
    marks:        Optional[int] = None
    feedback:     Optional[str] = None
    strengths:    Optional[str] = None
    improvements: Optional[str] = None

class ReportLinkCreate(BaseModel):
    student_id: str


# ── Tutor submits progress after session ──────────────────────────────────────
@router.post("/", status_code=201)
async def submit_progress(
    payload: ProgressCreate,
    current_user: dict = Depends(require_tutor),
):
    sb = get_supabase_admin()

    # Get session details
    try:
        session = sb.table("sessions").select(
            "*, students(id, profile_id), tutors(id)"
        ).eq("id", payload.session_id).single().execute().data
    except Exception:
        raise HTTPException(404, "Session not found")

    if session["status"] != "completed":
        raise HTTPException(400, "Can only submit progress for completed sessions")

    # Get tutor id
    tutor = sb.table("tutors").select("id").eq(
        "profile_id", current_user["id"]
    ).single().execute().data

    # Check if progress already submitted for this session
    existing = sb.table("progress").select("id").eq(
        "session_id", payload.session_id
    ).execute().data
    if existing:
        # Update existing
        result = sb.table("progress").update({
            "marks":        payload.marks,
            "feedback":     payload.feedback,
            "strengths":    payload.strengths,
            "improvements": payload.improvements,
        }).eq("session_id", payload.session_id).execute()
    else:
        # Insert new
        result = sb.table("progress").insert({
            "student_id":   session["students"]["id"],
            "session_id":   payload.session_id,
            "tutor_id":     tutor["id"],
            "subject":      session["subject"],
            "marks":        payload.marks,
            "feedback":     payload.feedback,
            "strengths":    payload.strengths,
            "improvements": payload.improvements,
        }).execute()

    # Notify student
    try:
        await NotificationService.create(
            session["students"]["profile_id"], "general",
            "Session Feedback Available 📝",
            f"Your tutor has submitted feedback for your {session['subject']} session.",
            sb,
        )
    except Exception:
        pass

    return result.data[0]


# ── Get progress for a student ────────────────────────────────────────────────
@router.get("/student/{student_id}")
async def get_student_progress(
    student_id: str,
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    progress = sb.table("progress").select(
        "*, sessions(scheduled_at, duration_mins, mode)"
    ).eq("student_id", student_id).order(
        "recorded_at", desc=False
    ).execute().data
    return progress or []


# ── Admin generates shareable report link ─────────────────────────────────────
@router.post("/report-link", status_code=201)
async def generate_report_link(
    payload: ReportLinkCreate,
    current_user: dict = Depends(require_admin),
):
    sb = get_supabase_admin()

    # Check if link already exists for this student
    existing = sb.table("report_links").select("*").eq(
        "student_id", payload.student_id
    ).execute().data

    if existing:
        # Refresh expiry
       
        result = sb.table("report_links").update({
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        }).eq("student_id", payload.student_id).execute()
        token = existing[0]["token"]
    else:
        
        result = sb.table("report_links").insert({
            "student_id": payload.student_id,
            "created_by": current_user["id"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        }).execute()
        token = result.data[0]["token"]

    return {"token": token, "url": f"/report/{token}"}


# ── Public report via token ───────────────────────────────────────────────────
@router.get("/report/{token}")
async def get_report_by_token(token: str):
    sb = get_supabase_admin()

    # Validate token
    try:
        link = sb.table("report_links").select("*").eq(
            "token", token
        ).single().execute().data
    except Exception:
        raise HTTPException(404, "Report link not found or expired")

    # Get student info
    student = sb.table("students").select(
        "*, profiles!students_profile_id_fkey(full_name, email)"
    ).eq("id", link["student_id"]).single().execute().data

    # Get progress records
    progress = sb.table("progress").select(
        "*, sessions(scheduled_at, duration_mins, mode)"
    ).eq("student_id", link["student_id"]).order(
        "recorded_at", desc=False
    ).execute().data or []

    # Get sessions
    sessions = sb.table("sessions").select(
        "*, tutors(profiles!tutors_profile_id_fkey(full_name))"
    ).eq("student_id", link["student_id"]).order(
        "scheduled_at", desc=False
    ).execute().data or []

    # Get invoices
    invoices = sb.table("invoices").select("*").eq(
        "student_id", link["student_id"]
    ).order("created_at", desc=True).execute().data or []

    return {
        "student":  student,
        "progress": progress,
        "sessions": sessions,
        "invoices": invoices,
    }