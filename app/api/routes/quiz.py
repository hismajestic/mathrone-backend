import json
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from app.core.security import get_current_user
from app.core.config import settings
import httpx

router = APIRouter(prefix="/quiz", tags=["AI Tutor"])

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


async def _groq(messages: list, temperature: float = 0.7, max_tokens: int = 1024) -> str:
    """Call Groq API and return the assistant text response."""
    if not settings.groq_api_key or settings.groq_api_key.startswith("gsk_your"):
        raise Exception("AI tutor is not configured. Please contact admin.")
    async with httpx.AsyncClient(timeout=40) as client:
        r = await client.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {settings.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model":       GROQ_MODEL,
                "messages":    messages,
                "temperature": temperature,
                "max_tokens":  max_tokens,
            },
        )
        if r.status_code == 429:
            raise Exception("AI service is busy — please wait a moment and try again.")
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# ─── Schemas ───────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    str   # "user" | "assistant"
    content: str

class ChatPayload(BaseModel):
    subject:  str
    topic:    Optional[str] = ""
    message:  str
    history:  List[ChatMessage] = []


# ─── System prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(subject: str, topic: str) -> str:
    topic_line = f" focusing specifically on **{topic}**" if topic else ""
    return f"""You are an expert, friendly AI study tutor at Mathrone Academy Rwanda, specialising in **{subject}**{topic_line}.

Your teaching philosophy:
- Explain concepts clearly, building from fundamentals to deeper understanding
- Use real-world examples relevant to Rwanda and East Africa when helpful
- Encourage curiosity and critical thinking — never just give answers without explanation
- Adapt your language to the student's apparent level based on how they write
- Be warm, patient, and encouraging — make learning feel accessible and exciting

You have two response modes. Decide which to use based on context:

**MODE 1 — EXPLANATION / CONVERSATION** (most responses):
Respond naturally in Markdown. Use clear structure when helpful (headers, bullet points, bold key terms).
Keep responses focused and digestible — not too long. End with an open question or invitation to go deeper when appropriate.

**MODE 2 — QUIZ QUESTION** (when the student asks to be tested, quizzed, or wants to check their understanding):
You MUST respond ONLY with this exact JSON (no extra text, no markdown fences):
{{
  "type": "quiz",
  "content": "<the question text — clear and concise>",
  "options": ["A. <option>", "B. <option>", "C. <option>", "D. <option>"],
  "correct_index": <0-3, integer index of the correct option>,
  "explanation": "<2-3 sentences explaining why the correct answer is right and why the others are wrong>"
}}

For all other responses (explanations, conversation), respond in plain Markdown text — NOT JSON.
Never mention that you are an AI language model or reference your training."""


# ─── Main chat endpoint ────────────────────────────────────────────────────────

@router.post("/chat")
async def ai_tutor_chat(
    payload: ChatPayload,
    current_user: dict = Depends(get_current_user),
):
    """
    Conversational AI tutor endpoint consumed by the student dashboard.
    Returns either:
      - { type: "message", content: "<markdown>" }
      - { type: "quiz", content, options, correct_index, explanation }
    """
    if not payload.subject.strip():
        raise HTTPException(400, "Subject is required.")

    system_prompt = _build_system_prompt(
        payload.subject.strip(),
        (payload.topic or "").strip(),
    )

    # Build message list — cap history at last 20 turns to stay within context window
    history_messages = [
        {"role": msg.role, "content": msg.content}
        for msg in payload.history[-20:]
        if msg.role in ("user", "assistant") and msg.content.strip()
    ]

    messages = [
        {"role": "system", "content": system_prompt},
        *history_messages,
        {"role": "user", "content": payload.message},
    ]

    try:
        raw = await _groq(messages, temperature=0.7, max_tokens=1024)
    except Exception as e:
        raise HTTPException(503, str(e))

    # Detect if the AI returned a quiz JSON response
    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(_strip_fences(stripped))
            if data.get("type") == "quiz" and "options" in data:
                correct = data.get("correct_index", 0)
                # Validate correct_index is a valid integer within options range
                if not isinstance(correct, int) or correct < 0 or correct >= len(data["options"]):
                    correct = 0
                return {
                    "type":          "quiz",
                    "content":       data.get("content", ""),
                    "options":       data.get("options", []),
                    "correct_index": correct,
                    "explanation":   data.get("explanation", ""),
                }
        except (json.JSONDecodeError, KeyError):
            pass  # Not valid quiz JSON — fall through to plain message

    # Plain conversational / explanation response
    return {
        "type":    "message",
        "content": raw.strip(),
    }