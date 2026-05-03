from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Any
from datetime import datetime, date
from enum import Enum


# ── Enums ──────────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    student = "student"
    tutor   = "tutor"
    admin   = "admin"

class TutorStatus(str, Enum):
    applicant    = "applicant"
    under_review = "under_review"
    written_exam = "written_exam"
    interview    = "interview"
    approved     = "approved"
    rejected     = "rejected"
    suspended    = "suspended"

class SessionMode(str, Enum):
    online   = "online"
    home     = "home"
    blended  = "blended"

class SessionStatus(str, Enum):
    pending     = "pending"
    scheduled   = "scheduled"
    in_progress = "in_progress"
    completed   = "completed"
    cancelled   = "cancelled"

class PaymentStatus(str, Enum):
    pending  = "pending"
    paid     = "paid"
    overdue  = "overdue"
    refunded = "refunded"


# ── Auth ───────────────────────────────────────────────────────────────────────
class RegisterStudentRequest(BaseModel):
    full_name:       str
    email:           EmailStr
    phone:           Optional[str] = None
    password:        str
    school_level: Optional[str] = None
    subjects_needed: List[str] = []
    preferred_mode:  SessionMode = SessionMode.online
    home_location:   Optional[str] = None
    parent_name:     Optional[str] = None
    parent_phone:    Optional[str] = None
    category: Optional[str] = 'academic'


class RegisterTutorRequest(BaseModel):
    full_name:         str
    email:             EmailStr
    phone:             Optional[str] = None
    password:          str
    subjects:          List[str]
    levels:            List[str]
    teaching_modes:    List[str]        # ['online','home']
    experience_years:  int
    experience_desc:   Optional[str] = None
    qualification:     str
    education_details: List[dict] = []
    languages:         List[str] = ["English"]
    bio:               Optional[str] = None
    location:          Optional[str] = None


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    user:          dict


class RefreshRequest(BaseModel):
    refresh_token: str


# ── Profile ────────────────────────────────────────────────────────────────────
class ProfileUpdate(BaseModel):
    full_name:  Optional[str] = None
    phone:      Optional[str] = None
    avatar_url: Optional[str] = None


class ProfileOut(BaseModel):
    id:         str
    full_name:  str
    email:      str
    phone:      Optional[str] = None
    role:       UserRole
    avatar_url: Optional[str] = None
    is_active:  bool
    created_at: datetime


# ── Tutor ──────────────────────────────────────────────────────────────────────
class TutorUpdate(BaseModel):
    bio:              Optional[str] = None
    subjects:         Optional[List[str]] = None
    levels:           Optional[List[str]] = None
    teaching_modes:   Optional[List[str]] = None
    experience_years: Optional[int] = None
    qualification:    Optional[str] = None
    languages:        Optional[List[str]] = None
    hourly_rate:      Optional[float] = None
    location:         Optional[str] = None
    availability:     Optional[dict] = None
    is_available:     Optional[bool] = None


class TutorStatusUpdate(BaseModel):
    status:          TutorStatus
    admin_notes:     Optional[str] = None
    exam_score:      Optional[int] = None
    interview_notes: Optional[str] = None
    hourly_rate:     Optional[float] = None
    salary_frequency: Optional[str] = None


class AvailabilitySlot(BaseModel):
    """Represents a tutor's available time slot (e.g., Monday 3-5 PM)."""
    day:     str   # 'Monday', 'Tuesday', etc.
    start:   str   # '14:00' (24-hour format)
    end:     str   # '17:00'


class TutorAvailabilityUpdate(BaseModel):
    """Update tutor's available time slots."""
    availability: List[AvailabilitySlot] = []


class TutorAgreement(BaseModel):
    """Tutor signs agreement/terms of service."""
    agreed: bool
    timestamp: Optional[datetime] = None


# ── Student ────────────────────────────────────────────────────────────────────
class StudentUpdate(BaseModel):
    school_level:    Optional[str] = None
    subjects_needed: Optional[List[str]] = None
    preferred_mode:  Optional[SessionMode] = None
    home_location:   Optional[str] = None
    parent_name:     Optional[str] = None
    parent_phone:    Optional[str] = None
    category:        Optional[str] = None
    notes:           Optional[str] = None


# ── Tutoring Request ───────────────────────────────────────────────────────────
class TutoringRequestCreate(BaseModel):
    subject:        str
    level:          str
    mode:           SessionMode
    preferred_days: List[str] = []
    preferred_time: Optional[str] = None
    home_location:  Optional[str] = None
    notes:          Optional[str] = None


class TutoringRequestAssign(BaseModel):
    tutor_id: str
    notes:    Optional[str] = None


# ── Session ────────────────────────────────────────────────────────────────────
class SessionCreate(BaseModel):
    student_id:    str
    tutor_id:      str
    subject:       str
    mode:          SessionMode
    scheduled_at:  datetime
    duration_mins: int = 60
    meeting_link:  Optional[str] = None
    platform:      Optional[str] = None   # 'zoom' | 'google_meet'
    location:      Optional[str] = None
    notes:         Optional[str] = None
    assignment_id: Optional[str] = None


class StudentSessionBooking(BaseModel):
    """Student books a tutor for an available time slot."""
    assignment_id: str
    scheduled_at:  datetime
    duration_mins: int = 60
    mode:          SessionMode
    location:      Optional[str] = None
    notes:         Optional[str] = None


class SessionUpdate(BaseModel):
    status:       Optional[SessionStatus] = None
    scheduled_at: Optional[datetime] = None
    meeting_link: Optional[str] = None
    tutor_notes:  Optional[str] = None
    actual_start: Optional[datetime] = None
    actual_end:   Optional[datetime] = None


class SessionWebhookPayload(BaseModel):
    """Jitsi or meeting platform webhook for session start/end."""
    session_id:   str
    event:        str   # 'started' | 'ended'
    timestamp:    datetime
    room_name:    Optional[str] = None
    participants: Optional[int] = None


class SessionReview(BaseModel):
    rating:      int
    review_text: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return v


# ── Assignment ─────────────────────────────────────────────────────────────────
class AssignmentCreate(BaseModel):
    student_id: str
    tutor_id:   str
    subject:    str
    mode:       SessionMode
    notes:      Optional[str] = None
    start_date: Optional[date] = None


# ── Messaging ──────────────────────────────────────────────────────────────────
class MessageCreate(BaseModel):
    recipient_id:   str
    content:        str
    attachment_url: Optional[str] = None


# ── Notifications ──────────────────────────────────────────────────────────────
class NotificationOut(BaseModel):
    id:         str
    type:       str
    title:      str
    body:       str
    data:       dict
    is_read:    bool
    created_at: datetime


# ── Payments ───────────────────────────────────────────────────────────────────
class InvoiceCreate(BaseModel):
    student_id: str
    package_id: Optional[str] = None
    amount:     float
    due_date:   Optional[date] = None
    notes:      Optional[str] = None


# ── Pagination ─────────────────────────────────────────────────────────────────
class PaginatedResponse(BaseModel):
    data:  List[Any]
    total: int
    page:  int
    limit: int
    pages: int


# ── Generic ────────────────────────────────────────────────────────────────────
class MessageResponse(BaseModel):
    message: str
    success: bool = True