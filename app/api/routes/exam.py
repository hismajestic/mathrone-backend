from fastapi import APIRouter, HTTPException, Depends
from app.core.security import get_current_user, require_admin
from app.core.config import settings
from app.db.supabase import get_supabase_admin
from pydantic import BaseModel
from typing import Optional, List, Any
import uuid
from datetime import datetime, timezone, timedelta
import httpx
import json
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

router = APIRouter(prefix="/exam", tags=["exam"])

# ─── AI grading helper ─────────────────────────────────

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()

async def _groq(messages: list) -> str:
    """Call Groq API and return the assistant text response."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL, 
                "messages": messages, 
                "temperature": 0.2, 
                "max_tokens": 1024,
                "response_format": {"type": "json_object"}
            }
        )
        if r.status_code == 429:
            raise Exception("AI service is busy. Please wait a moment and try again.")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

async def ai_grade_answer(question: str, model_answer: str, student_answer: str, max_marks: int, context: str = "") -> dict:
    if not settings.groq_api_key or settings.groq_api_key.startswith("gsk_your"):
        return {"marks_awarded": None, "feedback": "AI grading not configured — grade manually.", "confidence": "none", "key_points_hit": [], "key_points_missed": []}

    if not student_answer or not student_answer.strip():
        return {"marks_awarded": 0, "feedback": "No answer provided.", "confidence": "high", "key_points_hit": [], "key_points_missed": []}

    messages = [
        {"role": "system", "content": "You are a strict but fair exam grader. Respond with valid JSON only."},
        {"role": "user", "content": f"""Grade this exam answer for Mathrone Academy Rwanda.

Question: {question}
{f'Subject area: {context}' if context else ''}
Model answer: {model_answer}
Student's answer: {student_answer}
Maximum marks: {max_marks}

Criteria: full marks for covering all key points accurately, partial marks proportional to correctness, 0 for blank/irrelevant/wrong. Be strict.

Respond ONLY with JSON:
{{
  "marks_awarded": <integer 0 to {max_marks}>,
  "feedback": "<2-3 sentences: what was correct, what was missing, how to improve>",
  "confidence": "<high|medium|low>",
  "key_points_hit": ["<point>"],
  "key_points_missed": ["<point>"]
}}"""}
    ]

    try:
        raw = await _groq(messages)
        result = json.loads(_strip_fences(raw))
        try:
            awarded = int(result.get("marks_awarded", 0))
        except (TypeError, ValueError):
            awarded = 0
        marks = max(0, min(awarded, max_marks))
        return {
            "marks_awarded": marks,
            "feedback": result.get("feedback", ""),
            "confidence": result.get("confidence", "medium"),
            "key_points_hit": result.get("key_points_hit", []) if isinstance(result.get("key_points_hit"), list) else [],
            "key_points_missed": result.get("key_points_missed", []) if isinstance(result.get("key_points_missed"), list) else []
        }
    except json.JSONDecodeError:
        return {"marks_awarded": None, "feedback": "AI returned invalid response — grade manually.", "confidence": "none", "key_points_hit": [], "key_points_missed": []}
    except Exception as e:
        return {"marks_awarded": None, "feedback": f"AI grading error: {str(e)} — grade manually.", "confidence": "none", "key_points_hit": [], "key_points_missed": []}


def grade_matching(pairs: list, user_answer: str) -> tuple[int, int]:
    """Returns (earned_marks, total_marks) for a matching question."""
    if not pairs:
        return 0, 0
    # Use a fixed-size list based on pairs length to prevent index shifting
    user_parts = user_answer.split("||") if user_answer else []
    correct = 0
    for i, pair in enumerate(pairs):
        if i < len(user_parts):
            given = user_parts[i].strip().lower()
            target = pair.get("answer", "").strip().lower()
            if given == target and target != "":
                correct += 1
    return correct, len(pairs)


# ─── ADMIN: manage questions ───────────────────────────

class QuestionCreate(BaseModel):
    question: str
    type: str
    subject: Optional[str] = "general"
    level: Optional[str] = "All Levels" 
    difficulty: str = "medium"
    image_url: Optional[str] = None    
    options: Optional[List[str]] = None
    correct_answer: Optional[str] = None
    model_answer: Optional[str] = None
    pairs: Optional[List[Any]] = None
    marks: int = 1
    order_num: int = 0

@router.get("/questions/admin")
async def get_all_questions(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("exam_questions").select("*").order("order_num").execute().data or []

@router.post("/questions/admin")
async def create_question(payload: QuestionCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    # For matching questions, marks = number of pairs if not explicitly set
    marks = payload.marks
    if payload.type == "matching" and payload.pairs and payload.marks == 1:
        marks = len(payload.pairs)
    data = {
        "question": payload.question,
        "type": payload.type,
        "subject": payload.subject or "general",
        "image_url": payload.image_url,  # <--- Added this
        "marks": marks,
        "order_num": payload.order_num,
        "options": payload.options,
        "correct_answer": payload.correct_answer,
        "model_answer": payload.model_answer,
        "pairs": payload.pairs,
    }
    result = sb.table("exam_questions").insert(data).execute().data
    return result[0] if result else {}

@router.patch("/questions/admin/{question_id}")
async def update_question(question_id: str, payload: QuestionCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    marks = payload.marks
    if payload.type == "matching" and payload.pairs and payload.marks == 1:
        marks = len(payload.pairs)
    data = {
        "question": payload.question,
        "type": payload.type,
        "subject": payload.subject or "general",
        "image_url": payload.image_url,  # <--- Added this
        "marks": marks,
        "order_num": payload.order_num,
        "options": payload.options,
        "correct_answer": payload.correct_answer,
        "model_answer": payload.model_answer,
        "pairs": payload.pairs,
    }
    sb.table("exam_questions").update(data).eq("id", question_id).execute()
    return {"message": "Question updated"}

@router.delete("/questions/admin/{question_id}")
async def delete_question(question_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    try:
        # First, delete any answers associated with this question to satisfy DB constraints
        sb.table("exam_answers").delete().eq("question_id", question_id).execute()
        # Then delete the question
        sb.table("exam_questions").delete().eq("id", question_id).execute()
        return {"message": "Question deleted"}
    except Exception as e:
        raise HTTPException(500, f"Deletion failed: {str(e)}")

@router.post("/questions/admin/bulk-delete")
async def bulk_delete_questions(payload: dict, admin: dict = Depends(require_admin)):
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "No IDs provided")
    sb = get_supabase_admin()
    try:
        # Delete answers first
        sb.table("exam_answers").delete().in_("question_id", ids).execute()
        # Delete questions
        sb.table("exam_questions").delete().in_("id", ids).execute()
        return {"message": f"Deleted {len(ids)} questions successfully"}
    except Exception as e:
        raise HTTPException(500, f"Bulk deletion failed: {str(e)}")

# ─── TUTOR: take exam ──────────────────────────────────

class StartExamPayload(BaseModel):
    exam_code: str


def _select_questions_for_subject(all_questions: list, subjects: list, target_marks: int = 100, tutor_levels: list = None) -> list:
    import random
    
    # 1. Normalize and Expand Subjects
    synonym_groups = [
        {"mathematics", "maths", "math"},
        {"physics", "phys"},
        {"chemistry", "chem"},
        {"biology", "bio"},
        {"computer science", "ict", "coding", "programming", "computer"},
        {"social and religious studies", "srs", "social studies", "religion"},
        {"science and elementary technologies", "set", "science and technology", "elementary technology"}
    ]
    tutor_subs = [s.strip().lower() for s in (subjects or [])]
    t_levels = [l.strip().lower() for l in (tutor_levels or [])]
    
    expanded_subs = set(tutor_subs)
    for sub in tutor_subs:
        for group in synonym_groups:
            if sub in group: expanded_subs.update(group)

    # 2. Filter questions by BOTH Subject AND Level
    # We want questions that match the subject AND (match the tutor's level OR are "All Levels")
    matched = []
    general = []
    
    for q in all_questions:
        q_sub = (q.get("subject") or "general").strip().lower()
        q_lvl = (q.get("level") or "all levels").strip().lower()
        
        # Logic: Subject matches AND (Level matches OR Question is for everyone)
        subject_match = q_sub in expanded_subs
        level_match = q_lvl in t_levels or q_lvl == "all levels"
        
        if subject_match and level_match:
            matched.append(q)
        elif q_sub == "general":
            general.append(q)

    # 3. Shuffle and Select
    random.shuffle(matched)
    random.shuffle(general)
    
    pool = matched + general
    selected = []
    total = 0
    
    for q in pool:
        q_marks = q.get("marks", 1)
        if total + q_marks <= target_marks:
            selected.append(q)
            total += q_marks
        if total >= target_marks: break
            
    selected.sort(key=lambda q: q.get("order_num", 0))
    return selected

@router.post("/start")
async def start_exam(payload: StartExamPayload, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()

    tutor = sb.table("tutors").select("id, status, exam_code, subjects").eq("profile_id", current_user["id"]).single().execute().data
    if not tutor:
        raise HTTPException(403, "Tutor profile not found")
    if tutor["status"] != "written_exam":
        raise HTTPException(403, "You are not invited to take the exam yet")
    if not tutor.get("exam_code"):
        raise HTTPException(403, "No exam code has been set for you. Please contact admin.")
    if payload.exam_code.strip().upper() != tutor["exam_code"].strip().upper():
        raise HTTPException(403, "Invalid exam code. Please check your email for the correct code.")

    settings_row = sb.table("exam_settings").select("default_time_minutes", "instructions").eq("id", 1).single().execute().data
    
    # Use tutor-specific time if set, otherwise use global default
    global_minutes = settings_row["default_time_minutes"] if settings_row else 60
    exam_minutes = tutor.get("exam_time_minutes") or global_minutes
    instructions = settings_row["instructions"] if settings_row else "Please read carefully before starting"

    existing = sb.table("exam_attempts").select("id, status, started_at, time_limit_minutes, answers, question_ids").eq("tutor_id", tutor["id"]).execute().data
    if existing:
        attempt = existing[0]
        if attempt["status"] == "in_progress":
            started = datetime.fromisoformat(attempt["started_at"].replace("Z", "+00:00"))
            limit = timedelta(minutes=attempt["time_limit_minutes"])
            if datetime.now(timezone.utc) > started + limit:
                sb.table("exam_attempts").update({"status": "expired"}).eq("id", attempt["id"]).execute()
            else:
                # Resume: return the same questions that were assigned (by stored question_ids)
                stored_ids = attempt.get("question_ids") or []
                if stored_ids:
                    questions = sb.table("exam_questions").select(
                        "id, question, type, options, marks, order_num, pairs, subject, image_url, difficulty"
                    ).in_("id", stored_ids).order("order_num").execute().data or []
                else:
                    # Legacy fallback — no stored ids
                    questions = sb.table("exam_questions").select(
                        "id, question, type, options, marks, order_num, pairs, subject, image_url, difficulty"
                    ).eq("is_active", True).order("order_num").execute().data or []
                elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
                remaining = max(0, attempt["time_limit_minutes"] * 60 - elapsed)
                return {
                    "attempt_id": attempt["id"],
                    "time_limit_minutes": attempt["time_limit_minutes"],
                    "time_remaining_seconds": remaining,
                    "questions": questions,
                    "answers": attempt.get("answers") or {},
                    "resumed": True,
                    "instructions": instructions
                }
        else:
            raise HTTPException(403, "You have already attempted the exam and cannot retake it.")

    # Fetch full question library (admin fields stripped for security)
    all_questions = sb.table("exam_questions").select(
        "id, question, type, options, marks, order_num, pairs, subject, image_url, difficulty"
    ).eq("is_active", True).execute().data or []

    if not all_questions:
        raise HTTPException(400, "No exam questions available. Please contact admin.")

    # Select 100-mark subject-specific question set
    tutor_subjects = tutor.get("subjects") or []
    tutor_levels = tutor.get("levels") or [] # Get levels from tutor profile
    questions = _select_questions_for_subject(all_questions, tutor_subjects, target_marks=100, tutor_levels=tutor_levels)

    if not questions:
        raise HTTPException(400, "No questions available for your subjects. Please contact admin.")

    total_marks = sum(q.get("marks", 1) for q in questions)
    question_ids = [q["id"] for q in questions]

    attempt = sb.table("exam_attempts").insert({
        "tutor_id": tutor["id"],
        "profile_id": current_user["id"],
        "time_limit_minutes": exam_minutes,
        "status": "in_progress",
        "answers": {},
        "question_ids": question_ids,   # Store which questions this tutor got
        "total_marks": total_marks,
    }).execute().data[0]

    return {
        "attempt_id": attempt["id"],
        "time_limit_minutes": exam_minutes,
        "time_remaining_seconds": exam_minutes * 60,
        "questions": questions,
        "total_marks": total_marks,
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
    questions = sb.table("exam_questions").select(
        "id, question, type, options, marks, order_num, pairs"
    ).eq("is_active", True).order("order_num").execute().data or []
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

    # Fetch only the questions assigned to THIS attempt (by stored question_ids)
    stored_ids = attempt.get("question_ids") or []
    if stored_ids:
        questions = sb.table("exam_questions").select("*").in_("id", stored_ids).execute().data or []
    else:
        # Legacy fallback
        questions = sb.table("exam_questions").select("*").eq("is_active", True).execute().data or []
    answers = attempt["answers"] or {}

    total_marks = 0
    earned_marks = 0
    ai_feedback = {}   # { question_id: { marks_awarded, feedback, confidence } }

    for q in questions:
        qid = q["id"]
        user_answer = answers.get(qid, "")
        q_marks = q.get("marks", 1)
        total_marks += q_marks
        qtype = q.get("type", "text")

        if qtype in ("multiple_choice", "multiple_select"):
            correct_ans = q.get("correct_answer", "")
            if not correct_ans:
                # No correct answer configured — auto-award 0 so score isn't blocked
                earned_marks += 0
                ai_feedback[qid] = {
                    "marks_awarded": 0,
                    "feedback": "No correct answer set — awarded 0 (admin can override).",
                    "confidence": "none",
                    "auto": True
                }
            else:
                if "," in correct_ans:
                    correct_set = set(a.strip().lower() for a in correct_ans.split(","))
                    user_set = set(a.strip().lower() for a in user_answer.split(",")) if user_answer else set()
                    is_correct = correct_set == user_set
                else:
                    is_correct = user_answer.strip().lower() == correct_ans.strip().lower()
                awarded = q_marks if is_correct else 0
                earned_marks += awarded
                ai_feedback[qid] = {
                    "marks_awarded": awarded,
                    "feedback": "Correct ✅" if is_correct else f"Incorrect ❌ — correct answer: {correct_ans}",
                    "confidence": "high",
                    "auto": True
                }

        elif qtype == "matching":
            pairs = q.get("pairs") or []
            awarded, pair_total = grade_matching(pairs, user_answer)
            # Recalculate marks proportionally if question marks != pair count
            if pair_total > 0:
                awarded_scaled = round(awarded / pair_total * q_marks)
            else:
                awarded_scaled = 0
            earned_marks += awarded_scaled
            ai_feedback[qid] = {
                "marks_awarded": awarded_scaled,
                "feedback": f"{awarded}/{pair_total} pairs matched correctly.",
                "confidence": "high",
                "auto": True
            }

        elif qtype == "text":
            model_ans = q.get("model_answer", "")
            if not user_answer or not user_answer.strip():
                # Blank answer
                ai_feedback[qid] = {
                    "marks_awarded": 0,
                    "feedback": "No answer provided.",
                    "confidence": "high",
                    "auto": True
                }
            elif model_ans:
                result = await ai_grade_answer(
                    question=q["question"],
                    model_answer=model_ans,
                    student_answer=user_answer,
                    max_marks=q_marks,
                    context=q.get("subject_context", "")
                )
                if result["marks_awarded"] is not None:
                    earned_marks += result["marks_awarded"]
                ai_feedback[qid] = {**result, "auto": True}
            else:
                # No model answer set — flag for manual grading
                ai_feedback[qid] = {
                    "marks_awarded": None,
                    "feedback": "No model answer set — requires manual grading.",
                    "confidence": "none",
                    "auto": False
                }

    # Score based on auto-graded questions only
    # Count all questions that were graded (marks_awarded is not None)
    auto_graded_total = sum(
        q.get("marks", 1) for q in questions
        if ai_feedback.get(q["id"], {}).get("marks_awarded") is not None
    )
    auto_earned = sum(
        v["marks_awarded"] for v in ai_feedback.values()
        if v.get("marks_awarded") is not None
    )
    # Fallback: if nothing was graded at all (e.g. all AI calls failed), use earned_marks
    if auto_graded_total == 0 and total_marks > 0:
        auto_graded_total = total_marks
        auto_earned = earned_marks
    score_pct = round(auto_earned / auto_graded_total * 100) if auto_graded_total > 0 else 0

    has_pending = any(v.get("marks_awarded") is None for v in ai_feedback.values())
    final_status = "pending_review" if has_pending else "graded"

    # Save per-answer records with AI feedback
    answer_records = []
    for q in questions:
        qid = q["id"]
        fb = ai_feedback.get(qid, {})
        answer_records.append({
            "attempt_id": payload.attempt_id,
            "question_id": qid,
            "answer": answers.get(qid, ""),
            "is_correct": fb.get("marks_awarded") == q.get("marks", 1) if fb.get("marks_awarded") is not None else None,
            "marks_awarded": fb.get("marks_awarded"),
            "ai_feedback": fb.get("feedback", ""),
            "ai_confidence": fb.get("confidence", "none"),
            "key_points_hit": fb.get("key_points_hit", []),
            "key_points_missed": fb.get("key_points_missed", []),
        })
    if answer_records:
        # Upsert to avoid duplicates on re-grade
        try:
            sb.table("exam_answers").upsert(answer_records, on_conflict="attempt_id,question_id").execute()
        except Exception as e:
            print(f"Error saving exam_answers: {e}")

    sb.table("exam_attempts").update({
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "status": final_status,
        "score": score_pct,
        "auto_submitted": payload.auto_submitted,
        "ai_feedback": ai_feedback,
        "total_marks": total_marks,
        "earned_marks": auto_earned,
    }).eq("id", payload.attempt_id).execute()

    # Safely get tutor_id
    tutor_obj = attempt.get("tutors")
    tutor_id = tutor_obj.get("id") if isinstance(tutor_obj, dict) else (tutor_obj[0].get("id") if isinstance(tutor_obj, list) else None)
    
    if tutor_id:
        sb.table("tutors").update({"written_exam_score": score_pct}).eq("id", tutor_id).execute()

    return {
        "score": score_pct,
        "total_marks": auto_graded_total,
        "earned_marks": auto_earned,
        "has_pending_review": has_pending,
        "status": final_status
    }

# ─── ADMIN: view & grade attempts ─────────────────────

@router.get("/attempts/admin")
async def get_all_attempts(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("exam_attempts").select("*, profiles(full_name, email), tutors(id)").order("started_at", desc=True).execute().data or []

@router.get("/attempt/admin/{attempt_id}")
async def admin_get_attempt(attempt_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("*").eq("id", attempt_id).single().execute().data
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    # Admin gets full questions including model_answer
    questions = sb.table("exam_questions").select("*").eq("is_active", True).order("order_num").execute().data or []
    # Get per-answer AI feedback
    answer_rows = sb.table("exam_answers").select("*").eq("attempt_id", attempt_id).execute().data or []
    answer_map = {r["question_id"]: r for r in answer_rows}
    return {"attempt": attempt, "questions": questions, "answer_map": answer_map}

@router.post("/attempts/admin/{attempt_id}/ai-grade")
async def ai_regrade_attempt(attempt_id: str, admin: dict = Depends(require_admin)):
    """Re-run AI grading on all text questions for an attempt."""
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("*, tutors(id)").eq("id", attempt_id).single().execute().data
    if not attempt:
        raise HTTPException(404, "Attempt not found")

    questions = sb.table("exam_questions").select("*").eq("is_active", True).execute().data or []
    answers = attempt.get("answers") or {}
    ai_feedback = attempt.get("ai_feedback") or {}

    total_auto = 0
    total_earned = 0

    for q in questions:
        qid = q["id"]
        qtype = q.get("type", "text")
        q_marks = q.get("marks", 1)
        user_answer = answers.get(qid, "")

        if qtype == "text" and q.get("model_answer"):
            total_auto += q_marks
            result = await ai_grade_answer(
                question=q["question"],
                model_answer=q["model_answer"],
                student_answer=user_answer,
                max_marks=q_marks
            )
            ai_feedback[qid] = {**result, "auto": True}
            if result["marks_awarded"] is not None:
                total_earned += result["marks_awarded"]
                sb.table("exam_answers").update({
                    "marks_awarded": result["marks_awarded"],
                    "ai_feedback": result["feedback"],
                    "ai_confidence": result["confidence"],
                }).eq("attempt_id", attempt_id).eq("question_id", qid).execute()
        elif qtype in ("multiple_choice", "multiple_select", "matching"):
            existing = ai_feedback.get(str(qid), ai_feedback.get(qid, {}))
            if existing.get("marks_awarded") is not None:
                total_auto += q_marks
                total_earned += existing["marks_awarded"]

    score_pct = round(total_earned / total_auto * 100) if total_auto > 0 else 0
    has_pending = any(
        v.get("marks_awarded") is None
        for q in questions if q.get("type") == "text"
        for v in [ai_feedback.get(q["id"], {})]
    )

    sb.table("exam_attempts").update({
        "score": score_pct,
        "ai_feedback": ai_feedback,
        "earned_marks": total_earned,
        "status": "pending_review" if has_pending else "graded"
    }).eq("id", attempt_id).execute()
    sb.table("tutors").update({"written_exam_score": score_pct}).eq("id", attempt["tutors"]["id"]).execute()

    return {"score": score_pct, "earned_marks": total_earned, "has_pending": has_pending}

@router.patch("/attempts/admin/{attempt_id}/grade")
async def grade_attempt(attempt_id: str, payload: dict, admin: dict = Depends(require_admin)):
    """Manual override — set final score."""
    sb = get_supabase_admin()
    attempt = sb.table("exam_attempts").select("tutors(id)").eq("id", attempt_id).single().execute().data
    if not attempt:
        raise HTTPException(404, "Attempt not found")
    final_score = payload.get("score")
    sb.table("exam_attempts").update({"score": final_score, "status": "graded"}).eq("id", attempt_id).execute()
    sb.table("tutors").update({"written_exam_score": final_score}).eq("id", attempt["tutors"]["id"]).execute()
    return {"message": "Score updated"}

@router.patch("/attempts/admin/{attempt_id}/grade-answer")
async def grade_single_answer(attempt_id: str, payload: dict, admin: dict = Depends(require_admin)):
    """Admin manually grades a single text answer and updates the total score."""
    sb = get_supabase_admin()
    question_id = payload.get("question_id")
    marks = payload.get("marks_awarded")
    feedback = payload.get("feedback", "Manually graded by admin")
    if question_id is None or marks is None:
        raise HTTPException(400, "question_id and marks_awarded required")

    sb.table("exam_answers").update({
        "marks_awarded": marks,
        "ai_feedback": feedback,
        "ai_confidence": "manual",
    }).eq("attempt_id", attempt_id).eq("question_id", question_id).execute()

    # Recalculate total score from all answer rows
    attempt = sb.table("exam_attempts").select("*, tutors(id)").eq("id", attempt_id).single().execute().data
    all_answers = sb.table("exam_answers").select("marks_awarded, question_id").eq("attempt_id", attempt_id).execute().data or []
    questions = sb.table("exam_questions").select("id, marks").eq("is_active", True).execute().data or []
    q_marks_map = {q["id"]: q["marks"] for q in questions}

    total_auto = sum(q_marks_map.get(a["question_id"], 0) for a in all_answers if a["marks_awarded"] is not None)
    total_earned = sum(a["marks_awarded"] for a in all_answers if a["marks_awarded"] is not None)
    score_pct = round(total_earned / total_auto * 100) if total_auto > 0 else 0

    has_pending = any(a["marks_awarded"] is None for a in all_answers)
    sb.table("exam_attempts").update({
        "score": score_pct,
        "earned_marks": total_earned,
        "status": "pending_review" if has_pending else "graded"
    }).eq("id", attempt_id).execute()
    sb.table("tutors").update({"written_exam_score": score_pct}).eq("id", attempt["tutors"]["id"]).execute()

    return {"score": score_pct, "earned_marks": total_earned, "has_pending": has_pending}

@router.delete("/attempts/admin/{attempt_id}")
async def delete_attempt(attempt_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("exam_attempts").delete().eq("id", attempt_id).execute()
    return {"message": "Attempt deleted"}

@router.get("/settings/admin")
async def get_exam_settings(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    s = sb.table("exam_settings").select("*").eq("id", 1).single().execute().data
    return s or {"default_time_minutes": 60, "instructions": "Please read carefully before starting"}

@router.patch("/settings/admin")
async def update_exam_settings(payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("exam_settings").update({
        "default_time_minutes": payload.get("default_time_minutes", 60),
        "instructions": payload.get("instructions", "Please read carefully before starting"),
        "updated_by": admin["id"]
    }).eq("id", 1).execute()
    return {"message": "Settings updated"}