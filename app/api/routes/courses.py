from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import random
import re
import string

from app.db.supabase import get_supabase, get_supabase_admin
from app.core.security import get_current_user, require_admin

router = APIRouter(prefix="/courses", tags=["Courses"])


# ── Pydantic models ────────────────────────────────────────────────────────────
class CourseCreate(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    price: float = 0.0
    image_url: Optional[str] = None
    level: Optional[str] = None
    subject: Optional[str] = None
    is_published: bool = False

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    level: Optional[str] = None
    subject: Optional[str] = None
    is_published: Optional[bool] = None

class LessonCreate(BaseModel):
    title: str
    video_url: Optional[str] = None
    duration_mins: int = 0
    order_num: int = 0
    is_free_preview: bool = False
    content: Optional[str] = None        # rich text explanation
    notes: Optional[str] = None          # downloadable notes / summary
    resources: Optional[list] = []       # [{label, url, type}]
    quiz: Optional[list] = []            # [{question, options, answer}]

class LessonProgressUpdate(BaseModel):
    lesson_id: str
    course_id: str
    completed: bool = True

class StudentOrderCreate(BaseModel):
    course_id: str


# ── Public endpoints ───────────────────────────────────────────────────────────
@router.get("/public")
def get_public_courses():
    sb = get_supabase_admin()
    res = sb.table("courses").select("*").eq("is_published", True).order("created_at", desc=True).execute()
    return res.data

@router.get("/public/{slug}")
def get_public_course_details(slug: str):
    sb = get_supabase_admin()
    res = sb.table("courses").select("*").eq("slug", slug).eq("is_published", True).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Course not found")
    course = res.data[0]
    lessons = sb.table("course_lessons").select(
        "id, title, duration_mins, order_num"
    ).eq("course_id", course["id"]).eq("is_free_preview", True).order("order_num").execute()
    course["preview_lessons"] = lessons.data
    return course

@router.post("/request-enrollment")
def request_enrollment(order: StudentOrderCreate, user=Depends(get_current_user)):
    """Free courses: auto-enroll. Paid courses: create pending order for admin approval."""
    sb = get_supabase_admin()

    # Check course exists and get price
    course_res = sb.table("courses").select("id, title, price").eq("id", order.course_id).eq("is_published", True).execute()
    if not course_res.data:
        raise HTTPException(status_code=404, detail="Course not found")
    course = course_res.data[0]

    # Check not already enrolled
    existing = sb.table("course_enrollments").select("id").eq("student_id", user["id"]).eq("course_id", order.course_id).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Already enrolled in this course")

    # FREE course — enroll immediately, no admin needed
    if course["price"] == 0:
        sb.table("course_enrollments").insert({
            "student_id": user["id"],
            "course_id": order.course_id
        }).execute()
        return {"message": "Enrolled successfully! You can start learning now.", "auto_enrolled": True}

    # PAID course — check no pending order already exists
    pending = sb.table("course_orders").select("id").eq("student_id", user["id"]).eq("course_id", order.course_id).eq("status", "pending").execute()
    if pending.data:
        raise HTTPException(status_code=400, detail="You already have a pending enrollment request for this course")

    res = sb.table("course_orders").insert({
        "course_id": order.course_id,
        "student_id": user["id"],
        "status": "pending"
    }).execute()
    return {"message": "Enrollment request submitted. Admin will grant access after payment.", "auto_enrolled": False, "order_id": res.data[0]["id"]}


# ── Student endpoints ──────────────────────────────────────────────────────────
@router.get("/my")
def get_my_courses(user=Depends(get_current_user)):
    sb = get_supabase_admin()
    res = sb.table("course_enrollments").select("course_id, courses(*)").eq("student_id", user["id"]).execute()
    return [item["courses"] for item in res.data if item.get("courses")]

@router.get("/my/{course_id}/lessons")
def get_course_lessons(course_id: str, user=Depends(get_current_user)):
    sb = get_supabase_admin()
    enrollment = sb.table("course_enrollments").select("id").eq("student_id", user["id"]).eq("course_id", course_id).execute()
    if not enrollment.data and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="You do not have access to this course")
    lessons = sb.table("course_lessons").select("*").eq("course_id", course_id).order("order_num").execute()
    return lessons.data


# ── Admin endpoints ────────────────────────────────────────────────────────────
@router.get("/admin/all")
def get_all_courses(admin=Depends(require_admin)):
    sb = get_supabase_admin()
    res = sb.table("courses").select("*").order("created_at", desc=True).execute()
    return res.data

@router.get("/admin/orders")
def get_all_orders(admin=Depends(require_admin)):
    sb = get_supabase_admin()
    res = sb.table("course_orders").select("*, courses(title, price)").order("created_at", desc=True).execute()
    return res.data

@router.post("/admin/orders/{order_id}/approve")
def approve_course_order(order_id: str, admin=Depends(require_admin)):
    sb = get_supabase_admin()

    # Fetch order
    order_res = sb.table("course_orders").select("*").eq("id", order_id).execute()
    if not order_res.data:
        raise HTTPException(status_code=404, detail="Order not found")
    order = order_res.data[0]
    if order["status"] == "approved":
        raise HTTPException(status_code=400, detail="Order already approved")

    student_id = order.get("student_id")
    if not student_id:
        raise HTTPException(
            status_code=400,
            detail="This order has no linked student account. The student must be registered and logged in when they place an order."
        )

    # Grant course access
    try:
        sb.table("course_enrollments").insert({
            "student_id": student_id,
            "course_id": order["course_id"]
        }).execute()
    except Exception:
        pass  # already enrolled — idempotent

    # Mark approved
    sb.table("course_orders").update({"status": "approved"}).eq("id", order_id).execute()

    return {
        "message": "Access granted!",
        "student_id": student_id
    }


@router.post("/admin/orders/{order_id}/reject")
def reject_course_order(order_id: str, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("course_orders").update({"status": "rejected"}).eq("id", order_id).execute()
    return {"message": "Order rejected"}

@router.post("/admin")
def create_course(course: CourseCreate, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    res = sb.table("courses").insert(course.dict()).execute()
    return res.data[0]

@router.patch("/admin/{course_id}")
def update_course(course_id: str, course: CourseUpdate, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    data = {k: v for k, v in course.dict().items() if v is not None}
    res = sb.table("courses").update(data).eq("id", course_id).execute()
    return res.data[0]

@router.delete("/admin/{course_id}")
def delete_course(course_id: str, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("course_lessons").delete().eq("course_id", course_id).execute()
    sb.table("course_enrollments").delete().eq("course_id", course_id).execute()
    sb.table("course_orders").delete().eq("course_id", course_id).execute()
    sb.table("courses").delete().eq("id", course_id).execute()
    return {"message": "Course deleted"}

@router.post("/admin/{course_id}/lessons")
def add_lesson(course_id: str, lesson: LessonCreate, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    data = lesson.dict()
    data["course_id"] = course_id
    res = sb.table("course_lessons").insert(data).execute()
    return res.data[0]

@router.patch("/admin/{course_id}/lessons/{lesson_id}")
def update_lesson(course_id: str, lesson_id: str, lesson: LessonCreate, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    data = {k: v for k, v in lesson.dict().items() if v is not None}
    res = sb.table("course_lessons").update(data).eq("id", lesson_id).eq("course_id", course_id).execute()
    return res.data[0]

@router.delete("/admin/{course_id}/lessons/{lesson_id}")
def delete_lesson(course_id: str, lesson_id: str, admin=Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("course_lessons").delete().eq("id", lesson_id).eq("course_id", course_id).execute()
    return {"message": "Lesson deleted"}

@router.post("/my/lessons/progress")
def update_lesson_progress(progress: LessonProgressUpdate, user=Depends(get_current_user)):
    """Mark a lesson as complete/incomplete for the logged-in student."""
    sb = get_supabase_admin()
    from datetime import datetime, timezone
    sb.table("lesson_progress").upsert({
        "student_id": user["id"],
        "lesson_id": progress.lesson_id,
        "course_id": progress.course_id,
        "completed": progress.completed,
        "completed_at": datetime.now(timezone.utc).isoformat() if progress.completed else None
    }).execute()
    return {"message": "Progress saved"}

@router.get("/my/{course_id}/progress")
def get_course_progress(course_id: str, user=Depends(get_current_user)):
    """Return completed lesson IDs for a course for the logged-in student."""
    sb = get_supabase_admin()
    res = sb.table("lesson_progress").select("lesson_id, completed, completed_at").eq("student_id", user["id"]).eq("course_id", course_id).eq("completed", True).execute()
    return {"completed_lesson_ids": [r["lesson_id"] for r in res.data]}



# ── Diagnostic: test auth user creation in isolation ─────────────────────────
# Call POST /courses/admin/test-auth?phone=+250788000000 to test if auth
# user creation works for a given phone without enrolling anyone.
@router.post("/admin/test-auth")
def test_auth_creation(phone: str, admin=Depends(require_admin)):
    """
    Diagnostic endpoint. Creates and immediately deletes a test auth user
    so you can see the exact error from Supabase without side effects.
    Remove this endpoint once the issue is resolved.
    """
    sb = get_supabase_admin()
    import traceback as tb

    digits_only = re.sub(r"[^0-9]", "", phone)[:20]
    dummy_email = f"u{digits_only}@student.mathrone.rw"
    test_pw = ''.join(random.choices(string.digits, k=6))

    result = {"email_attempted": dummy_email, "steps": []}

    # Step 1: try creating with no metadata
    try:
        u = sb.auth.admin.create_user({
            "email": dummy_email,
            "password": test_pw,
            "email_confirm": True,
        })
        uid = u.user.id
        result["steps"].append({"step": "create_user_no_metadata", "status": "ok", "user_id": uid})

        # Step 2: try upserting profile
        try:
            sb.table("profiles").upsert({
                "id": uid,
                "full_name": "Test User",
                "email": dummy_email,
                "phone": phone,
                "role": "student"
            }).execute()
            result["steps"].append({"step": "upsert_profile", "status": "ok"})
        except Exception as pe:
            result["steps"].append({"step": "upsert_profile", "status": "error", "detail": str(pe)})

        # Cleanup
        try:
            sb.auth.admin.delete_user(uid)
            result["steps"].append({"step": "cleanup_delete", "status": "ok"})
        except Exception:
            result["steps"].append({"step": "cleanup_delete", "status": "skipped"})

    except Exception as e:
        result["steps"].append({
            "step": "create_user_no_metadata",
            "status": "error",
            "detail": str(e),
            "full_error": tb.format_exc()
        })

    return result

# ── Course-guest account upgrade to full student ──────────────────────────────
class StudentUpgradeRequest(BaseModel):
    full_name: str
    school_level: str = "Unknown"
    preferred_mode: str = "online"

@router.post("/upgrade-to-student")
def upgrade_to_student(req: StudentUpgradeRequest, user=Depends(get_current_user)):
    sb = get_supabase_admin()
    # Update profile: set role to student and update name
    sb.table("profiles").update({
        "full_name": req.full_name,
        "role": "student"
    }).eq("id", user["id"]).execute()
    # Upsert student row so they appear in the students table
    sb.table("students").upsert({
        "profile_id": user["id"],
        "school_level": req.school_level,
        "preferred_mode": req.preferred_mode
    }).execute()
    return {"message": "Account upgraded to student successfully"}