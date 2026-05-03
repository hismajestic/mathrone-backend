from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from typing import Optional, List
from pydantic import BaseModel
from datetime import datetime, timedelta
from app.schemas.schemas import (
    SessionCreate, SessionUpdate, SessionReview, StudentSessionBooking,
    StudentUpdate, AssignmentCreate, TutoringRequestCreate,
    TutoringRequestAssign, MessageCreate, InvoiceCreate, MessageResponse,
)
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from app.services.notification_service import NotificationService
from app.services.storage_service import StorageService


# ============================================================
# STUDENTS ROUTER
# ============================================================
students_router = APIRouter(prefix="/students", tags=["Students"])


@students_router.get("/me")
async def get_my_student_profile(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    try:
        student = sb.table("students").select("*").eq(
            "profile_id", current_user["id"]
        ).single().execute()
    except Exception:
        raise HTTPException(404, "Student profile not found")
    if not student.data:
        raise HTTPException(404, "Student profile not found")
    return {**student.data, "profile": current_user}


@students_router.patch("/me", response_model=MessageResponse)
async def update_student_profile(
    payload: StudentUpdate,
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    data = payload.model_dump(exclude_none=True)
    if data:
        sb.table("students").update(data).eq("profile_id", current_user["id"]).execute()
    return MessageResponse(message="Profile updated")


@students_router.post("/requests", status_code=201)
async def create_tutoring_request(
    payload: TutoringRequestCreate,
    current_user: dict = Depends(get_current_user),
):
    """Student submits a tutoring request; admin assigns a tutor."""
    sb = get_supabase_admin()
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
    except Exception:
        raise HTTPException(404, "Student profile not found")

    # Check if student already has an active assignment for this subject
    active_assignment = sb.table("assignments").select("id").eq(
        "student_id", student["id"]
    ).eq("subject", payload.subject).eq("is_active", True).execute().data
    if active_assignment:
        raise HTTPException(400, f"You already have an active tutor for {payload.subject}.")

    # Check if student already has a pending request for this subject
    pending_request = sb.table("tutoring_requests").select("id").eq(
        "student_id", student["id"]
    ).eq("subject", payload.subject).eq("status", "pending").execute().data
    if pending_request:
        raise HTTPException(400, f"You already have a pending request for {payload.subject}. Please wait for admin to assign a tutor.")

    result = sb.table("tutoring_requests").insert({
        "student_id":     student["id"],
        "subject":        payload.subject,
        "level":          payload.level,
        "mode":           payload.mode.value,
        "preferred_days": payload.preferred_days,
        "preferred_time": payload.preferred_time,
        "home_location":  payload.home_location,
        "notes":          payload.notes,
    }).execute()

    # Notify admins
    admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
    for admin in admins:
        await NotificationService.create(
            admin["id"], "general",
            "New Tutoring Request",
            f"{current_user['full_name']} needs a {payload.subject} tutor "
            f"({payload.level}, {payload.mode.value})",
            sb,
        )

    return result.data[0]

@students_router.get("/requests")
async def get_my_requests(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
    except Exception:
        return []
    return sb.table("tutoring_requests").select(
        "*, tutors(id, profiles!tutors_profile_id_fkey(full_name, avatar_url))"
    ).eq("student_id", student["id"]).order("created_at", desc=True).execute().data


@students_router.get("/assignments")
async def get_my_assignments(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
    except Exception:
        return []
    return sb.table("assignments").select(
        "*, tutors!inner(id, subjects, hourly_rate, agreement_accepted, profiles:profile_id(id, full_name, avatar_url, phone))"
    ).eq("student_id", student["id"]).eq("is_active", True).execute().data


# ── Admin student endpoints ────────────────────────────────────────────────────

@students_router.get("/admin/all", tags=["Admin"])
async def list_all_students(admin = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("students").select(
       "*, profiles!students_profile_id_fkey(id, full_name, email, phone), "
        "assignments(id, is_active, tutors(id, profiles!tutors_profile_id_fkey(full_name)))"
    ).order("created_at", desc=True).execute().data


@students_router.post("/admin/assign", tags=["Admin"], status_code=201)
async def assign_tutor(payload: AssignmentCreate, admin = Depends(require_admin)):
    """Admin manually assigns a tutor to a student for a subject."""
    sb = get_supabase_admin()

    # Deactivate all previous assignments for same student+subject
    sb.table("assignments").update({"is_active": False}).eq(
        "student_id", payload.student_id
    ).eq("subject", payload.subject).execute()

    # Check if this exact combination already exists and update it
    existing = sb.table("assignments").select("id").eq(
        "student_id", payload.student_id
    ).eq("tutor_id", payload.tutor_id).eq(
        "subject", payload.subject
    ).execute().data

    if existing:
        # Reactivate existing assignment
        result = sb.table("assignments").update({
            "is_active":   True,
            "mode":        payload.mode.value,
            "notes":       payload.notes,
            "assigned_by": admin["id"],
        }).eq("id", existing[0]["id"]).execute()
    else:
        # Create new assignment
        result = sb.table("assignments").insert({
            "student_id":  payload.student_id,
            "tutor_id":    payload.tutor_id,
            "subject":     payload.subject,
            "mode":        payload.mode.value,
            "notes":       payload.notes,
            "assigned_by": admin["id"],
            "is_active":   payload.is_active  # Use the flag from the admin modal
        }).execute()

    # Notify both parties
    try:
        student      = sb.table("students").select("profile_id").eq("id", payload.student_id).single().execute().data
        tutor        = sb.table("tutors").select("profile_id").eq("id", payload.tutor_id).single().execute().data
        tutor_name   = sb.table("profiles").select("full_name").eq("id", tutor["profile_id"]).single().execute().data["full_name"]
        student_name = sb.table("profiles").select("full_name").eq("id", student["profile_id"]).single().execute().data["full_name"]

        await NotificationService.create(
            student["profile_id"], "tutor_assigned",
            "Tutor Assigned! 🎓",
            f"Great news! {tutor_name} has been assigned as your {payload.subject} tutor.",
            sb,
        )
        await NotificationService.create(
            tutor["profile_id"], "tutor_assigned",
            "New Student Assigned 👨‍🎓",
            f"You have a new student: {student_name} for {payload.subject}.",
            sb,
        )
    except Exception:
        pass

    return result.data[0]

@students_router.get("/admin/requests", tags=["Admin"])
async def list_all_requests(
    status: Optional[str] = Query(None),
    admin  = Depends(require_admin),
):
    sb = get_supabase_admin()
    q  = sb.table("tutoring_requests").select(
        "*, students(id, school_level, profiles!students_profile_id_fkey(full_name, email))"
    )
    if status:
        q = q.eq("status", status)
    return q.order("created_at", desc=True).execute().data


@students_router.patch("/admin/requests/{request_id}/assign", tags=["Admin"])
async def assign_request(
    request_id: str,
    payload:    TutoringRequestAssign,
    admin       = Depends(require_admin),
):
    sb = get_supabase_admin()
    sb.table("tutoring_requests").update({
        "status":         "assigned",
        "assigned_tutor": payload.tutor_id,
        "handled_by":     admin["id"],
    }).eq("id", request_id).execute()
    return MessageResponse(message="Tutor assigned to request")


# ============================================================
# SESSIONS ROUTER
# ============================================================
sessions_router = APIRouter(prefix="/sessions", tags=["Sessions"])


@sessions_router.get("/admin/all", tags=["Admin"])
async def list_all_sessions(
    status: Optional[str] = Query(None),
    admin  = Depends(require_admin),
):
    """Admin: list all sessions with student and tutor profiles."""
    sb = get_supabase_admin()
    # We use a broad select to ensure profiles for both roles are returned
    q  = sb.table("sessions").select(
        "*, students(*, profiles!students_profile_id_fkey(full_name)), tutors(*, profiles!tutors_profile_id_fkey(full_name))"
    )
    if status:
        q = q.eq("status", status)
    return q.order("scheduled_at", desc=True).execute().data


@sessions_router.post("/", status_code=201)
async def create_session(
    payload:      SessionCreate,
    current_user: dict = Depends(require_admin),
):
    """Admin creates and schedules a session."""
    sb = get_supabase_admin()

    # Calculate session end time
    from datetime import timedelta
    session_start = payload.scheduled_at
    session_end   = session_start + timedelta(minutes=payload.duration_mins)

    # Check tutor conflicts
    tutor_sessions = sb.table("sessions").select(
        "id, scheduled_at, duration_mins, students(profiles!students_profile_id_fkey(full_name))"
    ).eq("tutor_id", payload.tutor_id).in_(
        "status", ["scheduled", "pending", "in_progress"]
    ).execute().data or []

    for s in tutor_sessions:
        from datetime import datetime
        existing_start = datetime.fromisoformat(s["scheduled_at"].replace("Z", "+00:00"))
        existing_end   = existing_start + timedelta(minutes=s["duration_mins"])
        if session_start < existing_end and session_end > existing_start:
            student_name = s.get("students", {}).get("profiles!students_profile_id_fkey", {}).get("full_name", "another student")
            raise HTTPException(409, 
                f"Tutor already has a session from "
                f"{existing_start.strftime('%b %d at %I:%M %p')} to "
                f"{existing_end.strftime('%I:%M %p')} with {student_name}."
            )

    # Check student conflicts
    student_sessions = sb.table("sessions").select(
        "id, scheduled_at, duration_mins, tutors(profiles!tutors_profile_id_fkey(full_name))"
    ).eq("student_id", payload.student_id).in_(
        "status", ["scheduled", "pending", "in_progress"]
    ).execute().data or []

    for s in student_sessions:
        existing_start = datetime.fromisoformat(s["scheduled_at"].replace("Z", "+00:00"))
        existing_end   = existing_start + timedelta(minutes=s["duration_mins"])
        if session_start < existing_end and session_end > existing_start:
            tutor_name = s.get("tutors", {}).get("profiles!tutors_profile_id_fkey", {}).get("full_name", "another tutor")
            raise HTTPException(409,
                f"Student already has a session from "
                f"{existing_start.strftime('%b %d at %I:%M %p')} to "
                f"{existing_end.strftime('%I:%M %p')} with {tutor_name}."
            )

    # Auto-generate Jitsi link for online or blended sessions
    meeting_link = payload.meeting_link
    platform     = payload.platform
    if payload.mode.value in ["online", "blended"] and not meeting_link:
        import uuid
        room_name    = f"Mathrone-{uuid.uuid4().hex[:10]}"
        meeting_link = f"https://meet.jit.si/{room_name}"
        platform     = "jitsi"

    result = sb.table("sessions").insert({
        "student_id":    payload.student_id,
        "tutor_id":      payload.tutor_id,
        "subject":       payload.subject,
        "mode":          payload.mode.value,
        "scheduled_at":  payload.scheduled_at.isoformat(),
        "duration_mins": payload.duration_mins,
        "meeting_link":  meeting_link,
        "platform":      platform,
        "location":      payload.location,
        "notes":         payload.notes,
        "assignment_id": payload.assignment_id,
    }).execute()

    session  = result.data[0]
    time_str = payload.scheduled_at.strftime("%b %d at %I:%M %p")

    try:
        student = sb.table("students").select("profile_id").eq("id", payload.student_id).single().execute().data
        tutor   = sb.table("tutors").select("profile_id").eq("id", payload.tutor_id).single().execute().data
        for uid in [student["profile_id"], tutor["profile_id"]]:
            await NotificationService.create(
                uid, "session_reminder",
                "Session Scheduled 📅",
                f"Your {payload.subject} session is on {time_str}." + (f" Join here: {meeting_link}" if meeting_link else ""),
                sb,
            )
    except Exception:
        pass

    return session
@sessions_router.get("/my")
async def get_my_sessions(
    status:       Optional[str] = Query(None),
    current_user: dict          = Depends(get_current_user),
):
    """Get all sessions for the authenticated user (student or tutor)."""
    sb = get_supabase_admin()

    if current_user["role"] == "student":
        try:
            student = sb.table("students").select("id").eq(
                "profile_id", current_user["id"]
            ).single().execute().data
        except Exception:
            return []
        q = sb.table("sessions").select(
            "*, tutors(id, profiles!tutors_profile_id_fkey(full_name, avatar_url))"
        ).eq("student_id", student["id"])

    elif current_user["role"] == "tutor":
        try:
            tutor = sb.table("tutors").select("id").eq(
                "profile_id", current_user["id"]
            ).single().execute().data
        except Exception:
            return []
        q = sb.table("sessions").select(
            "*, students(id, profiles!students_profile_id_fkey(full_name, avatar_url))"
        ).eq("tutor_id", tutor["id"])

    else:
        q = sb.table("sessions").select("*")

    if status:
        q = q.eq("status", status)
    return q.order("scheduled_at", desc=True).execute().data


@sessions_router.patch("/{session_id}", response_model=MessageResponse)
async def update_session(
    session_id:   str,
    payload:      SessionUpdate,
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    data = payload.model_dump(exclude_none=True)
    # Convert datetime fields to ISO strings
    for key in ("scheduled_at", "actual_start", "actual_end"):
        if key in data and data[key] is not None:
            data[key] = data[key].isoformat()
    if data:
        sb.table("sessions").update(data).eq("id", session_id).execute()
    return MessageResponse(message="Session updated")


@sessions_router.post("/{session_id}/webhook")
async def session_webhook(
    session_id: str,
    payload: dict,  # {event: 'started'|'ended', timestamp: ISO string}
):
    """
    Webhook endpoint for Jitsi or other meeting platforms to notify of session start/end.
    Automatically captures actual_start and actual_end times.
    """
    sb = get_supabase_admin()
    from datetime import datetime
    
    try:
        session = sb.table("sessions").select("*").eq("id", session_id).single().execute().data
    except Exception:
        raise HTTPException(404, "Session not found")
    
    event = payload.get("event")  # 'started' or 'ended'
    timestamp = payload.get("timestamp") or datetime.utcnow().isoformat()
    
    update_data = {}
    
    if event == "started":
        # Session has started - capture actual_start
        update_data["actual_start"] = timestamp
        update_data["status"] = "in_progress"
        
        # Notify participants
        try:
            student = sb.table("students").select("profile_id").eq("id", session["student_id"]).single().execute().data
            tutor = sb.table("tutors").select("profile_id").eq("id", session["tutor_id"]).single().execute().data
            
            await NotificationService.create(
                student["profile_id"], "session_reminder",
                "Session Started 🎓",
                f"Your {session['subject']} session has started. Join the meeting now!",
                sb,
            )
            await NotificationService.create(
                tutor["profile_id"], "session_reminder",
                "Session Started 🎓",
                f"Your session with student has started.",
                sb,
            )
        except Exception:
            pass
    
    elif event == "ended":
        # Session has ended - capture actual_end
        update_data["actual_end"] = timestamp
        update_data["status"] = "completed"
        
        # Notify admin and participants
        try:
            student = sb.table("students").select("profile_id").eq("id", session["student_id"]).single().execute().data
            tutor = sb.table("tutors").select("profile_id").eq("id", session["tutor_id"]).single().execute().data
            
            # Notify admin
            admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
            tutor_name = sb.table("profiles").select("full_name").eq("id", tutor["profile_id"]).single().execute().data["full_name"]
            student_name = sb.table("profiles").select("full_name").eq("id", student["profile_id"]).single().execute().data["full_name"]
            
            for admin in admins:
                await NotificationService.create(
                    admin["id"], "general",
                    "Session Completed ✓",
                    f"{tutor_name}'s session with {student_name} ({session['subject']}) has ended.",
                    sb,
                )
            
            # Notify participants
            await NotificationService.create(
                student["profile_id"], "general",
                "Session Ended 📝",
                f"Your {session['subject']} session has ended. Please rate your tutor!",
                sb,
            )
        except Exception as e:
            print(f"Notification error: {e}")
    
    if update_data:
        sb.table("sessions").update(update_data).eq("id", session_id).execute()
    
    return {"message": f"Session {event} recorded", "session_id": session_id}


@sessions_router.post("/my/book", status_code=201)
async def book_session_student(
    payload: StudentSessionBooking,
    current_user: dict = Depends(get_current_user),
):
    """
    Student books a tutor from available time slots.
    Student can only book from their assigned tutors.
    """
    sb = get_supabase_admin()
    
    # Get student ID
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
    except Exception:
        raise HTTPException(404, "Student profile not found")
    
    # Get the assignment
    try:
        assignment = sb.table("assignments").select("*, tutors(id, availability)").eq(
            "id", payload.assignment_id
        ).eq("is_active", True).single().execute().data
    except Exception:
        raise HTTPException(404, "Assignment not found or inactive")
    
    if assignment["student_id"] != student["id"]:
        raise HTTPException(403, "You can only book sessions with your assigned tutors")
    
    tutor_id = assignment["tutor_id"]
    
    # Check tutor availability
    tutor_availability = assignment["tutors"]["availability"] or {}
    slots = tutor_availability.get("slots", [])
    
    if not slots:
        raise HTTPException(400, "This tutor has not set their availability yet")
    
    # Check if the requested time matches a tutor availability slot
    scheduled_at = payload.scheduled_at
    slot_day = scheduled_at.strftime("%A")  # 'Monday', 'Tuesday', etc.
    slot_start = scheduled_at.strftime("%H:%M")  # '14:00'
    slot_end = (scheduled_at + timedelta(minutes=payload.duration_mins)).strftime("%H:%M")
    
    matching_slot = None
    for slot in slots:
        if slot["day"] == slot_day:
            if slot["start"] <= slot_start and slot_end <= slot["end"]:
                matching_slot = slot
                break
    
    if not matching_slot:
        slot_times = ', '.join([f"{s['day']} {s['start']}-{s['end']}" for s in slots])
        raise HTTPException(
            400,
            f"Requested time ({slot_day} {slot_start}-{slot_end}) doesn't match tutor's availability. "
            f"Available: {slot_times}"
        )
    
    # Calculate session end time
    session_start = payload.scheduled_at
    session_end = session_start + timedelta(minutes=payload.duration_mins)
    
    # Check for tutor conflicts (already existing sessions)
    tutor_sessions = sb.table("sessions").select(
        "id, scheduled_at, duration_mins"
    ).eq("tutor_id", tutor_id).in_(
        "status", ["scheduled", "pending", "in_progress"]
    ).execute().data or []
    
    for s in tutor_sessions:
        existing_start = datetime.fromisoformat(s["scheduled_at"].replace("Z", "+00:00"))
        existing_end = existing_start + timedelta(minutes=s["duration_mins"])
        if session_start < existing_end and session_end > existing_start:
            raise HTTPException(409, "This tutor is already booked for this time slot")
    
    # Check for student conflicts
    student_sessions = sb.table("sessions").select(
        "id, scheduled_at, duration_mins"
    ).eq("student_id", student["id"]).in_(
        "status", ["scheduled", "pending", "in_progress"]
    ).execute().data or []
    
    for s in student_sessions:
        existing_start = datetime.fromisoformat(s["scheduled_at"].replace("Z", "+00:00"))
        existing_end = existing_start + timedelta(minutes=s["duration_mins"])
        if session_start < existing_end and session_end > existing_start:
            raise HTTPException(409, "You already have a session at this time")
    
    # Auto-generate Jitsi link for online sessions
    meeting_link = None
    platform = None
    if payload.mode.value in ["online", "blended"]:
        import uuid
        room_name = f"Mathrone-{uuid.uuid4().hex[:10]}"
        meeting_link = f"https://meet.jit.si/{room_name}"
        platform = "jitsi"
    
    # Create the session
    result = sb.table("sessions").insert({
        "student_id": student["id"],
        "tutor_id": tutor_id,
        "assignment_id": payload.assignment_id,
        "subject": assignment["subject"],
        "mode": payload.mode.value,
        "scheduled_at": payload.scheduled_at.isoformat(),
        "duration_mins": payload.duration_mins,
        "meeting_link": meeting_link,
        "platform": platform,
        "location": payload.location,
        "notes": payload.notes,
        "status": "scheduled",
    }).execute()
    
    session = result.data[0]
    time_str = payload.scheduled_at.strftime("%b %d at %I:%M %p")
    
    try:
        tutor_profile = sb.table("tutors").select("profile_id").eq("id", tutor_id).single().execute().data
        
        # Notify both parties
        await NotificationService.create(
            current_user["id"], "session_reminder",
            "Session Booked ✓",
            f"You have booked a session for {time_str}." + (f" Join: {meeting_link}" if meeting_link else ""),
            sb,
        )
        await NotificationService.create(
            tutor_profile["profile_id"], "general",
            "New Session Booking 📅",
            f"Student has booked a {assignment['subject']} session for {time_str}.",
            sb,
        )
    except Exception:
        pass
    
    return session


# ── Student booking endpoint with conflict checking ──────────────────────────────

@sessions_router.post("/{session_id}/review", response_model=MessageResponse)
async def review_session(
    session_id:   str,
    payload:      SessionReview,
    current_user: dict = Depends(get_current_user),
):
    """Student submits a star rating for a completed session."""
    sb = get_supabase_admin()
    try:
        session = sb.table("sessions").select("*").eq("id", session_id).single().execute().data
    except Exception:
        raise HTTPException(404, "Session not found")

    if session["status"] != "completed":
        raise HTTPException(400, "Can only review completed sessions")

    sb.table("sessions").update({
        "student_rating": payload.rating,
        "student_review": payload.review_text,
    }).eq("id", session_id).execute()

    # Insert review record (triggers tutor rating recalculation)
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
        sb.table("reviews").insert({
            "session_id":  session_id,
            "student_id":  student["id"],
            "tutor_id":    session["tutor_id"],
            "rating":      payload.rating,
            "review_text": payload.review_text,
        }).execute()
    except Exception:
        pass  # Review may already exist (unique constraint)

    return MessageResponse(message="Review submitted successfully")


@sessions_router.post("/{session_id}/materials", response_model=MessageResponse)
async def upload_session_material(
    session_id:   str,
    file:         UploadFile = File(...),
    current_user: dict       = Depends(get_current_user),
):
    """Upload a file attached to a session."""
    sb  = get_supabase_admin()
    url = await StorageService.upload_material(file, session_id)

    try:
        session  = sb.table("sessions").select("materials_urls").eq("id", session_id).single().execute().data
        existing = session.get("materials_urls") or []
        sb.table("sessions").update({"materials_urls": existing + [url]}).eq("id", session_id).execute()
    except Exception:
        pass

    return MessageResponse(message="Material uploaded successfully")


# ============================================================
# MESSAGES ROUTER
# ============================================================
messages_router = APIRouter(prefix="/messages", tags=["Messaging"])


def _get_or_create_conversation(sb, user_a: str, user_b: str) -> str:
    """Return the conversation ID between two users, creating it if needed."""
    # Search for existing conversation in both participant orderings
    try:
        result = sb.table("conversations").select("id").or_(
            f"and(participant_a.eq.{user_a},participant_b.eq.{user_b}),"
            f"and(participant_a.eq.{user_b},participant_b.eq.{user_a})"
        ).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception:
        pass

    # Create new
    new_conv = sb.table("conversations").insert({
        "participant_a": user_a,
        "participant_b": user_b,
    }).execute()
    return new_conv.data[0]["id"]


@messages_router.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """List all conversations for the current user, enriched with the other participant."""
    sb  = get_supabase_admin()
    uid = current_user["id"]

    result = sb.table("conversations").select("*").or_(
        f"participant_a.eq.{uid},participant_b.eq.{uid}"
    ).order("last_message_at", desc=True).execute()

    conversations = []
    for conv in result.data:
        other_id = conv["participant_b"] if conv["participant_a"] == uid else conv["participant_a"]
        try:
            other = sb.table("profiles").select(
                "id, full_name, avatar_url, role"
            ).eq("id", other_id).single().execute().data
        except Exception:
            other = None
        conversations.append({**conv, "other_user": other})

    return conversations


@messages_router.get("/conversations/{other_user_id}")
async def get_messages(
    other_user_id: str,
    current_user:  dict = Depends(get_current_user),
):
    """Fetch (or start) a conversation with another user and return all messages."""
    sb      = get_supabase_admin()
    uid     = current_user["id"]
    conv_id = _get_or_create_conversation(sb, uid, other_user_id)

    msgs = sb.table("messages").select("*").eq(
        "conversation_id", conv_id
    ).order("created_at").execute()

    # Mark incoming messages as read
    try:
        sb.table("messages").update({"status": "read"}).eq(
            "conversation_id", conv_id
        ).neq("sender_id", uid).execute()
    except Exception:
        pass

    return {"conversation_id": conv_id, "messages": msgs.data}


@messages_router.post("/send", status_code=201)
async def send_message(
    payload:      MessageCreate,
    current_user: dict = Depends(get_current_user),
):
    sb      = get_supabase_admin()
    uid     = current_user["id"]
    
    # Ensure communication is only allowed between assigned pairs
    if current_user["role"] != "admin":
        is_assigned = False
        if current_user["role"] == "student":
            # Check: Does this student have an active assignment with this tutor?
            res = sb.table("assignments").select("id").eq("student_id", sb.table("students").select("id").eq("profile_id", uid).single().execute().data["id"]).eq("tutor_id", sb.table("tutors").select("id").eq("profile_id", payload.recipient_id).single().execute().data["id"]).eq("is_active", True).execute()
            if res.data: is_assigned = True
        else:
            # Check: Does this tutor have an active assignment with this student?
            res = sb.table("assignments").select("id").eq("tutor_id", sb.table("tutors").select("id").eq("profile_id", uid).single().execute().data["id"]).eq("student_id", sb.table("students").select("id").eq("profile_id", payload.recipient_id).single().execute().data["id"]).eq("is_active", True).execute()
            if res.data: is_assigned = True
        
        if not is_assigned:
            raise HTTPException(403, "Access denied. You can only message users you are assigned to.")

    conv_id = _get_or_create_conversation(sb, uid, payload.recipient_id)

    # LEAKAGE PROTECTION: Flag numbers or external payment requests
    leak_flag = False
    content_lower = payload.content.lower()
    patterns = ["+250", "078", "079", "072", "073", "whatsapp", "pay me", "private", "number is", "contact me"]
    if any(p in content_lower for p in patterns):
        leak_flag = True

    msg = sb.table("messages").insert({
        "conversation_id": conv_id,
        "sender_id":       uid,
        "content":         payload.content,
        "attachment_url":  payload.attachment_url,
        "flagged":         leak_flag
    }).execute().data[0]

    sb.table("conversations").update({"last_message": payload.content[:80], "last_message_at": "now()"}).eq("id", conv_id).execute()

    # Alert admin of leakage in real-time
    if leak_flag:
        admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
        for admin in admins:
            await NotificationService.create(admin["id"], "general", "⚠️ Leakage Alert", f"{current_user['full_name']} sent contact/payment info.", sb)

    await NotificationService.create(payload.recipient_id, "new_message", f"New message from {current_user['full_name']}", payload.content[:100], sb)
    return msg


# ============================================================
# NOTIFICATIONS ROUTER
# ============================================================
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])


@notifications_router.get("/")
async def get_notifications(
    unread_only:  bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    q  = sb.table("notifications").select("*").eq("user_id", current_user["id"])
    if unread_only:
        q = q.eq("is_read", False)
    return q.order("created_at", desc=True).limit(50).execute().data


@notifications_router.patch("/read-all", response_model=MessageResponse)
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    sb.table("notifications").update({"is_read": True}).eq(
        "user_id", current_user["id"]
    ).execute()
    return MessageResponse(message="All notifications marked as read")


@notifications_router.patch("/{notif_id}/read", response_model=MessageResponse)
async def mark_read(
    notif_id:     str,
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    sb.table("notifications").update({"is_read": True}).eq(
        "id", notif_id
    ).eq("user_id", current_user["id"]).execute()
    return MessageResponse(message="Notification marked as read")


# ============================================================
# PAYMENTS ROUTER
# ============================================================
payments_router = APIRouter(prefix="/payments", tags=["Payments"])


@payments_router.get("/packages")
async def get_packages():
    """Public: list active payment packages."""
    sb = get_supabase_admin()
    return sb.table("payment_packages").select("*").eq("is_active", True).order("price").execute().data


@payments_router.post("/invoices", status_code=201, tags=["Admin"])
async def create_invoice(
    payload: InvoiceCreate,
    admin    = Depends(require_admin),
):
    sb = get_supabase_admin()
    result = sb.table("invoices").insert({
        "student_id": payload.student_id,
        "package_id": payload.package_id,
        "amount":     payload.amount,
        "due_date":   payload.due_date.isoformat() if payload.due_date else None,
        "notes":      payload.notes,
        "issued_by":  admin["id"],
    }).execute()

    try:
        student = sb.table("students").select("profile_id").eq(
            "id", payload.student_id
        ).single().execute().data
        await NotificationService.create(
            student["profile_id"], "payment_due",
            "New Invoice 💳",
            f"An invoice of ${payload.amount:.2f} has been issued. Please pay by the due date.",
            sb,
        )
    except Exception:
        pass

    return result.data[0]


@payments_router.get("/invoices/my")
async def get_my_invoices(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    try:
        student = sb.table("students").select("id").eq(
            "profile_id", current_user["id"]
        ).single().execute().data
    except Exception:
        return []
    return sb.table("invoices").select(
        "*, payment_packages(name)"
    ).eq("student_id", student["id"]).order("created_at", desc=True).execute().data


@payments_router.get("/invoices/admin", tags=["Admin"])
async def get_all_invoices(admin = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("invoices").select(
        "*, students(profiles!students_profile_id_fkey(full_name, email)), payment_packages(name)"
    ).order("created_at", desc=True).execute().data


@payments_router.get("/salaries/admin", tags=["Admin"])
async def get_tutor_salaries(admin = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("tutor_salaries").select(
       "*, tutors(profiles!tutors_profile_id_fkey(full_name))"
    ).order("created_at", desc=True).execute().data


@payments_router.get("/summary/admin", tags=["Admin"])
async def payment_summary(admin = Depends(require_admin)):
    """Admin dashboard revenue summary."""
    sb       = get_supabase_admin()
    invoices = sb.table("invoices").select("amount, status").execute().data or []
    salaries = sb.table("tutor_salaries").select("amount, status").execute().data or []

    total_revenue  = sum(float(i["amount"]) for i in invoices if i["status"] == "paid")
    pending_fees   = sum(float(i["amount"]) for i in invoices if i["status"] == "pending")
    salary_paid    = sum(float(s["amount"]) for s in salaries if s["status"] == "paid")
    salary_pending = sum(float(s["amount"]) for s in salaries if s["status"] == "pending")

    return {
        "total_revenue":   total_revenue,
        "pending_fees":    pending_fees,
        "salary_paid":     salary_paid,
        "salary_pending":  salary_pending,
        "net_income":      total_revenue - salary_paid,
    }
@payments_router.patch("/invoices/{invoice_id}/paid")
async def mark_invoice_paid(
    invoice_id: str,
    admin = Depends(require_admin),
):
    sb = get_supabase_admin()

    # 1. Get detailed invoice and student info
    invoice = sb.table("invoices").select(
        "*, students(id, profile_id, profiles!students_profile_id_fkey(full_name))"
    ).eq("id", invoice_id).single().execute().data

    if not invoice:
        raise HTTPException(404, "Invoice not found")

    # 2. Update Invoice Status
    sb.table("invoices").update({
        "status":  "paid",
        "paid_at": "now()"
    }).eq("id", invoice_id).execute()

    # 3. THE BRIDGE: Automatically activate any inactive deals for this student
    # This assumes the invoice was for their tutoring package.
    sb.table("assignments").update({"is_active": True}).eq("student_id", invoice["student_id"]).execute()

    # 4. Notify student and trigger "Book Now" availability
    try:
        await NotificationService.create(
            invoice["students"]["profile_id"], "general",
            "👑 Deal Activated!",
            f"Payment confirmed. Your tutoring sessions are now active! You can now book your first session.",
            sb,
        )
    except Exception:
        pass

    return {"message": "Invoice paid and tutoring deal activated! ✅"}
@notifications_router.delete("/{notification_id}")
async def delete_notification(
    notification_id: str,
    current_user: dict = Depends(get_current_user)
):
    sb = get_supabase_admin()
    sb.table("notifications").delete().eq("id", notification_id).eq("user_id", current_user["id"]).execute()
    return {"message": "Notification deleted"}

@messages_router.delete("/{message_id}")
async def delete_message(
    message_id: str,
    current_user: dict = Depends(get_current_user)
):
    sb = get_supabase_admin()
    sb.table("messages").delete().eq("id", message_id).execute()
    return {"message": "Message deleted"}
@students_router.delete("/admin/{student_id}")
async def delete_student(
    student_id: str,
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    student = sb.table("students").select("profile_id").eq("id", student_id).single().execute().data
    if not student:
        raise HTTPException(404, "Student not found")
    sb.table("assignments").delete().eq("student_id", student_id).execute()
    sb.table("students").delete().eq("id", student_id).execute()
    sb.auth.admin.delete_user(student["profile_id"])
    return {"message": "Student deleted successfully"}

class BookingRequest(BaseModel):
    tutor_id: str
    subject: str
    scheduled_at: datetime

@sessions_router.post("/book")
async def book_session(payload: BookingRequest, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    
    # 1. Fetch Student ID
    student_res = sb.table("students").select("id").eq("profile_id", current_user["id"]).single().execute()
    if not student_res.data: raise HTTPException(404, "Student profile not found")
    student_id = student_res.data["id"]

    # 2. STRICT ASSIGNMENT CHECK: Has Admin authorized this student to work with THIS specific tutor?
    assignment_check = sb.table("assignments").select("id, is_active").eq("student_id", student_id).eq("tutor_id", payload.tutor_id).eq("is_active", True).execute()
    
    if not assignment_check.data:
        raise HTTPException(403, "You cannot book this tutor. Please click 'Request this Tutor' first and wait for Admin assignment.")

    # 3. DEAL CHECK: Has Admin activated this pairing?
    assignment_check = sb.table("assignments").select("is_active").eq("student_id", student_id).eq("tutor_id", payload.tutor_id).eq("subject", payload.subject).eq("is_active", True).execute()
    if not assignment_check.data:
        raise HTTPException(403, "This tutoring deal is not yet active. Please contact Admin to finalize payment and activate your sessions.")

    # 4. CONFLICT CHECK: Is the tutor already busy?
    if not student_res.data: raise HTTPException(404, "Student profile not found")
    student_id = student_res.data["id"]

    # 2. CONFLICT CHECK: Is the tutor already busy?
    # Check for any session (scheduled or pending) within 1 hour of the requested time
    start_buffer = (payload.scheduled_at - timedelta(minutes=59)).isoformat()
    end_buffer = (payload.scheduled_at + timedelta(minutes=59)).isoformat()
    
    conflicts = sb.table("sessions").select("id").eq("tutor_id", payload.tutor_id).in_("status", ["scheduled", "pending"]).gte("scheduled_at", start_buffer).lte("scheduled_at", end_buffer).execute()
    
    if conflicts.data:
        raise HTTPException(409, "The tutor has another session around this time. Please pick a different slot.")

    # 3. Create session as PENDING
    result = sb.table("sessions").insert({
        "student_id": student_id,
        "tutor_id": payload.tutor_id,
        "subject": payload.subject,
        "scheduled_at": payload.scheduled_at.isoformat(),
        "status": "pending",
        "mode": "online",
        "duration_mins": 60
    }).execute()
    
    if not result.data: raise HTTPException(500, "Failed to create booking")
    session = result.data[0]
    
    # 4. Notify Tutor
    tutor_info = sb.table("tutors").select("profile_id").eq("id", payload.tutor_id).single().execute().data
    if tutor_info:
        await NotificationService.create(
            tutor_info["profile_id"], 
            "general", 
            "New Booking Request 📅", 
            f"{current_user['full_name']} requested {payload.subject} for {payload.scheduled_at.strftime('%b %d at %I:%M %p')}.", 
            sb
        )
    
    return session