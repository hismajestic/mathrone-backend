from fastapi import APIRouter, HTTPException, Depends
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from pydantic import BaseModel
from typing import Optional, List
import uuid
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/exam", tags=["exam"])

# ─── ADMIN: manage questions ───────────────────────────

class QuestionCreate(BaseModel):
    question: str
    type: str
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    marks: int = 1
    order_num: int = 0

@router.get("/questions/admin")
async def get_all_questions(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("exam_questions").select("*").order("order_num").execute().data or []

@router.post("/questions/admin")
async def create_question(payload: QuestionCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    data = {
        "question": payload.question,
        "type": payload.type,
        "marks": payload.marks,
        "order_num": payload.order_num,
        "options": payload.options,
        "correct_answer": payload.correct_answer,
    }
    result = sb.table("exam_questions").insert(data).execute().data
    return result[0] if result else {}

@router.patch("/questions/admin/{question_id}")
async def update_question(question_id: str, payload: QuestionCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    data = {
        "question": payload.question,
        "type": payload.type,
        "marks": payload.marks,
        "order_num": payload.order_num,
        "options": payload.options,
        "correct_answer": payload.correct_answer,
    }
    sb.table("exam_questions").update(data).eq("id", question_id).execute()
    return {"message": "Question updated"}

@router.delete("/questions/admin/{question_id}")
async def delete_question(question_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("exam_questions").delete().eq("id", question_id).execute()
    return {"message": "Question deleted"}

# ─── TUTOR: take exam ──────────────────────────────────

class StartExamPayload(BaseModel):
    exam_code: str

@router.post("/start")
async def start_exam(payload: StartExamPayload, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()

    # Get tutor record
    tutor = sb.table("tutors").select("id, status, exam_code").eq("profile_id", current_user["id"]).single().execute().data
    if not tutor:
        raise HTTPException(403, "Tutor profile not found")
    if tutor["status"] != "written_exam":
        raise HTTPException(403, "You are not invited to take the exam yet")

    # Verify exam code
    if not tutor.get("exam_code"):
        raise HTTPException(403, "No exam code has been set for you. Please contact admin.")
    if payload.exam_code.strip().upper() != tutor["exam_code"].strip().upper():
        raise HTTPException(403, "Invalid exam code. Please check with admin.")

    # Get exam settings
    settings = sb.table("exam_settings").select("default_time_minutes", "instructions").eq("id", 1).single().execute().data
    exam_minutes = settings["default_time_minutes"] if settings else 60
    instructions = settings["instructions"] if settings else "Please read carefully before starting"

    # Check for any existing attempt
    existing = sb.table("exam_attempts").select("id, status, started_at, time_limit_minutes").eq("tutor_id", tutor["id"]).execute().data
    if existing:
        attempt = existing[0]
        if attempt["status"] == "in_progress":
            started = datetime.fromisoformat(attempt["started_at"].replace("Z", "+00:00"))
            limit = timedelta(minutes=attempt["time_limit_minutes"])
            if datetime.now(timezone.utc) > started + limit:
                sb.table("exam_attempts").update({"status": "expired"}).eq("id", attempt["id"]).execute()
                # Allow new attempt since expired
            else:
                questions = sb.table("exam_questions").select("id, question, type, options, marks, order_num").eq("is_active", True).order("order_num").execute().data or []
                elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
                remaining = max(0, attempt["time_limit_minutes"] * 60 - elapsed)
                return {
                    "attempt_id": attempt["id"],
                    "time_limit_minutes": attempt["time_limit_minutes"],
                    "time_remaining_seconds": remaining,
                    "questions": questions,
                    "answers": attempt.get("answers", {}),
                    "resumed": True,
                    "instructions": instructions
                }
        else:
            # Submitted, graded, or expired - prevent new attempt
            raise HTTPException(403, "You have already attempted the exam and cannot retake it.")

    # No existing attempt, create new

    # Get questions
    questions = sb.table("exam_questions").select("id, question, type, options, marks, order_num").eq("is_active", True).order("order_num").execute().data or []
    if not questions:
        raise HTTPException(400, "No exam questions available. Please contact admin.")

    # Create attempt
    attempt = sb.table("exam_attempts").insert({
        "tutor_id": tutor["id"],
        "profile_id": current_user["id"],
        "time_limit_minutes": exam_minutes,
        "status": "in_progress",
        "answers": {}
    }).execute().data[0]

    return {
        "attempt_id": attempt["id"],
        "time_limit_minutes": exam_minutes,
        "time_remaining_seconds": exam_minutes * 60,
        "questions": questions,
        "answers": {},
        "resumed": False,
        "instructions": instructions
    }

@router.get("/attempt/{attempt_id}")
async def get_attempt(attempt_id: str, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("*").eq("id", attempt_id).eq("profile_id", current_user["id"]).single().execute().data
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    questions = sb.table("exam_questions").select("id, question, type, options, marks, order_num").eq("is_active", True).order("order_num").execute().data or []
    return {"attempt": attempt, "questions": questions}

class SaveAnswerPayload(BaseModel):
    attempt_id: str
    question_id: str
    answer: str

@router.post("/save-answer")
async def save_answer(payload: SaveAnswerPayload, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("id, answers, status").eq("id", payload.attempt_id).eq("profile_id", current_user["id"]).single().execute().data
    if not attempt or attempt["status"] != "in_progress":
        raise HTTPException(400, "Invalid or expired attempt")
    answers = attempt["answers"] or {}
    answers[payload.question_id] = payload.answer
    sb.table("exam_attempts").update({"answers": answers}).eq("id", payload.attempt_id).execute()
    return {"saved": True}

class ReportCheatingPayload(BaseModel):
    attempt_id: str
    type: str

@router.post("/report-cheating")
async def report_cheating(payload: ReportCheatingPayload, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("tab_switches, fullscreen_exits").eq("id", payload.attempt_id).single().execute().data
    if not attempt:
        return {"ok": True}
    if payload.type == "tab_switch":
        sb.table("exam_attempts").update({"tab_switches": (attempt["tab_switches"] or 0) + 1}).eq("id", payload.attempt_id).execute()
    elif payload.type == "fullscreen_exit":
        sb.table("exam_attempts").update({"fullscreen_exits": (attempt["fullscreen_exits"] or 0) + 1}).eq("id", payload.attempt_id).execute()
    return {"ok": True}

class SubmitPayload(BaseModel):
    attempt_id: str
    auto_submitted: bool = False

@router.post("/submit")
async def submit_exam(payload: SubmitPayload, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
 
    attempt = sb.table("exam_attempts").select("*, tutors(id)").eq("id", payload.attempt_id).eq("profile_id", current_user["id"]).single().execute().data
    if not attempt or attempt["status"] != "in_progress":
        raise HTTPException(400, "Invalid attempt")
    
    questions = sb.table("exam_questions").select("*").eq("is_active", True).execute().data or []
    answers = attempt["answers"] or {}
    

    # Auto-grade multiple choice
   # Auto-grade multiple choice
    total_marks = sum(q["marks"] for q in questions)
    earned_marks = 0
    mcq_total = 0
    score_pct = 0
    answer_records = []

    for q in questions:
        user_answer = answers.get(q["id"], "")
        is_correct = False
        marks_awarded = 0

        if q.get("correct_answer"):
            mcq_total += q["marks"]
            if "," in q["correct_answer"]:
                # Multiple select
                correct_set = set(a.strip().lower() for a in q["correct_answer"].split(","))
                user_set = set(a.strip().lower() for a in user_answer.split(",")) if user_answer else set()
                is_correct = correct_set == user_set
            else:
                # Multiple choice
                is_correct = user_answer.strip().lower() == q["correct_answer"].strip().lower()
            marks_awarded = q["marks"] if is_correct else 0
            earned_marks += marks_awarded

        answer_records.append({
            "attempt_id": payload.attempt_id,
            "question_id": q["id"],
            "answer": user_answer,
            "is_correct": is_correct,
            "marks_awarded": marks_awarded
        })

    # Calculate score percentage
    score_pct = round((earned_marks / mcq_total * 100)) if mcq_total > 0 else 0
    # Insert answers
    if answer_records:
        sb.table("exam_answers").insert(answer_records).execute()

    # Update attempt
    sb.table("exam_attempts").update({
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": "submitted",
        "score": score_pct,
        "auto_submitted": payload.auto_submitted
    }).eq("id", payload.attempt_id).execute()

    # Update tutor written_exam_score
    sb.table("tutors").update({
        "written_exam_score": score_pct
    }).eq("id", attempt["tutors"]["id"]).execute()

    return {
        "score": score_pct,
        "total_marks": mcq_total,
        "earned_marks": earned_marks
    }

# ─── ADMIN: view attempts ──────────────────────────────

@router.get("/attempts/admin")
async def get_all_attempts(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("exam_attempts").select("*, profiles(full_name, email), tutors(id)").order("started_at", desc=True).execute().data or []

@router.patch("/attempts/admin/{attempt_id}/grade")
async def grade_attempt(attempt_id: str, payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("tutors(id)").eq("id", attempt_id).single().execute().data
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    final_score = payload.get("score")
    sb.table("exam_attempts").update({"score": final_score, "status": "graded"}).eq("id", attempt_id).execute()
    sb.table("tutors").update({"written_exam_score": final_score}).eq("id", attempt["tutors"]["id"]).execute()
    return {"message": "Score updated"}

@router.delete("/attempts/admin/{attempt_id}")
async def delete_attempt(attempt_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("exam_attempts").delete().eq("id", attempt_id).execute()
    return {"message": "Attempt deleted"}

@router.get("/settings/admin")
async def get_exam_settings(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    settings = sb.table("exam_settings").select("*").eq("id", 1).single().execute().data
    return settings or {"default_time_minutes": 60, "instructions": "Please read carefully before starting"}

@router.patch("/settings/admin")
async def update_exam_settings(payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    data = {
        "default_time_minutes": payload.get("default_time_minutes", 60),
        "instructions": payload.get("instructions", "Please read carefully before starting"),
        "updated_by": admin["id"]
    }
    sb.table("exam_settings").update(data).eq("id", 1).execute()
    return {"message": "Settings updated"}