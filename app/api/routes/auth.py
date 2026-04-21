import secrets
from app.services.email_service import EmailService
from fastapi import APIRouter, HTTPException, Depends
from gotrue.errors import AuthApiError
from pydantic import EmailStr, BaseModel
from app.schemas.schemas import (
    RegisterStudentRequest, RegisterTutorRequest,
    LoginRequest, TokenResponse, RefreshRequest, MessageResponse,
)
from app.core.security import (
    create_access_token, create_refresh_token,
    decode_token, get_current_user, require_admin,
)
from app.db.supabase import get_supabase, get_supabase_admin
from app.services.notification_service import NotificationService
import time

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _wait_for_profile(sb, user_id: str, retries: int = 5) -> dict:
    """The handle_new_user trigger creates the profile asynchronously.
    Retry a few times to make sure it exists before we continue."""
    for _ in range(retries):
        try:
            result = sb.table("profiles").select("*").eq("id", user_id).single().execute()
            if result.data:
                return result.data
        except Exception:
            pass
        time.sleep(0.4)
    raise HTTPException(500, "Profile creation timed out. Please try again.")


def _ensure_profile(sb, user_id: str, full_name: str, email: str, role: str) -> dict:
    """Ensure a profile row exists (handles cases where the Supabase trigger is missing)."""
    try:
        result = sb.table("profiles").select("*").eq("id", user_id).single().execute()
        if result.data:
            return result.data
    except Exception:
        pass

    try:
        sb.table("profiles").insert({
            "id": user_id,
            "full_name": full_name,
            "email": email,
            "role": role,
        }).execute()
        return {"id": user_id, "full_name": full_name, "email": email, "role": role}
    except Exception:
        # If insertion fails, fall back to waiting for the trigger
        return _wait_for_profile(sb, user_id)


def _create_user_via_supabase(email: str, password: str, full_name: str, role: str):
    """Try creating a Supabase user (admin API), with a fallback to public signup."""
    import httpx
    sb_admin = get_supabase_admin()
    sb_anon  = get_supabase()

    try:
        return sb_admin.auth.admin.create_user({
            "email":         email,
            "password":      password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name, "role": role},
        })
    except AuthApiError as e:
        err_msg = e.message.lower()
        # Email already registered — surface a clean message immediately
        if "already" in err_msg or "exists" in err_msg or "registered" in err_msg:
            raise HTTPException(400, "An account with this email already exists. Please log in instead.")
        # Try the public signup endpoint as a fallback
        try:
            result = sb_anon.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"full_name": full_name, "role": role}},
            })
            # sign_up returns a user even for existing emails (Supabase behaviour) — check it's real
            if not result.user or not result.user.id:
                raise HTTPException(400, "Registration failed: could not create account. Please try again.")
            return result
        except HTTPException:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError, Exception) as e2:
            raise HTTPException(400, f"Registration failed: {e.message}. Please check your connection and try again.")
        
async def send_recruitment_email(email: str, name: str, status: str, score: int = None, reason: str = None):
    from app.services.email_service import EmailService
    # Score-based messaging
    score_msg = ""
    score_grade = ""
    if score is not None:
        if score >= 80:
            score_msg = f"Your score was <strong>{score}/100</strong> — Excellent work! 🌟"
            score_grade = "excellent"
        elif score >= 65:
            score_msg = f"Your score was <strong>{score}/100</strong> — Good performance! 👍"
            score_grade = "good"
        elif score >= 50:
            score_msg = f"Your score was <strong>{score}/100</strong> — Satisfactory. Keep improving! 📚"
            score_grade = "satisfactory"
        else:
            score_msg = f"Your score was <strong>{score}/100</strong>."
            score_grade = "low"

    emails = {
        "applicant": (
            "We received your application — Mathrone Academy",
            EmailService.template(
                f"Application Received, {name}! 📋",
                f"Thank you for applying to become a tutor at Mathrone Academy.<br><br>We have received your application and our team will review your CV and certificates shortly. You will hear from us within 3-5 business days.<br><br>In the meantime, make sure your profile is complete and your documents are up to date.",
                "https://mathroneacademy.com/#login",
                "View My Application →"
            )
        ),
        "under_review": (
            "Your application is under review — Mathrone Academy",
            EmailService.template(
                f"Good news, {name}! Your application is being reviewed 🔍",
                f"Our admin team is currently reviewing your application, CV, and certificates.<br><br>We will contact you soon with the next steps. Thank you for your patience.",
                "https://mathroneacademy.com/#login",
                "View My Profile →"
            )
        ),
        "written_exam": (
            "You are invited to take a written exam — Mathrone Academy",
            EmailService.template(
                f"Congratulations {name}! You passed the review stage 🎉",
                f"You have been invited to complete a written examination as part of our tutor vetting process.<br><br>Please log in to your Mathrone Academy account to access your exam. The exam is timed — <strong>60 minutes</strong> — and must be completed in one sitting.<br><br><strong>Important rules:</strong><br>• Do not switch tabs during the exam<br>• Stay in fullscreen mode<br>• Do not copy or paste answers<br>• Submit before the timer runs out",
                "https://mathroneacademy.com/#login",
                "Take My Exam Now →"
            )
        ),
        "interview": (
            "You are invited for an interview — Mathrone Academy",
            EmailService.template(
                f"{'Well done' if score_grade in ('excellent','good') else 'Thank you'}, {name}! You are invited for an interview 🌟",
                f"{score_msg + '<br><br>' if score_msg else ''}You have been selected for an interview with our team. We will contact you shortly to schedule a convenient time.<br><br>{'Your strong performance shows great potential as a Mathrone tutor.' if score_grade == 'excellent' else 'Please prepare to discuss your teaching experience and methodology.' if score_grade in ('good','satisfactory') else 'Please prepare to discuss how you plan to improve your subject knowledge.'}<br><br>Make sure your profile bio and documents are complete before the interview.",
                "https://mathroneacademy.com/#login",
                "Prepare for Interview →"
            )
        ),
        "approved": (
            "Welcome to Mathrone Academy! You are approved 👑",
            EmailService.template(
                f"Welcome aboard, {name}! 🎓",
                f"We are thrilled to inform you that you have successfully passed all stages of our vetting process and are now an <strong>approved tutor</strong> on Mathrone Academy.<br><br>{score_msg + '<br><br>' if score_msg else ''}You will be assigned to students shortly. Please make sure your profile, bio, and payment preferences are complete before your first session.<br><br>Welcome to the Mathrone family — let's change education in Rwanda together! 👑",
                "https://mathroneacademy.com/#login",
                "Go to My Dashboard →"
            )
        ),
        "rejected": (
            "Update on your Mathrone Academy application",
            EmailService.template(
                f"Thank you for applying, {name}",
                f"After careful review of your application{'and exam results' if score else ''}, we regret to inform you that we are unable to move forward at this time.<br><br>{score_msg + '<br><br>' if score_msg else ''}{'<strong>Reason:</strong> ' + reason + '<br><br>' if reason else ''}We encourage you to continue developing your skills and reapply in the future. We appreciate the time and effort you put into your application.",
                "https://mathroneacademy.com",
                "Visit Mathrone Academy →"
            )
        ),
        "suspended": (
            "Your Mathrone Academy account has been suspended",
            EmailService.template(
                f"Account Suspended, {name}",
                f"Your tutor account on Mathrone Academy has been temporarily suspended.<br><br>{'<strong>Reason:</strong> ' + reason + '<br><br>' if reason else ''}Please contact our admin team for more information.",
                "https://mathroneacademy.com",
                "Contact Support →"
            )
        ),
    }
    if status in emails:
        subject, body = emails[status]
        try:
            await EmailService.send(email, subject, body)
        except Exception as e:
            print(f"Recruitment email error ({status}): {e}")


@router.post("/register/student", response_model=TokenResponse, status_code=201)
async def register_student(payload: RegisterStudentRequest):
    """Register a new student / parent account."""
    sb = get_supabase_admin()

    auth_resp = _create_user_via_supabase(
        payload.email, payload.password, payload.full_name, "student"
    )

    user_id = getattr(auth_resp.user, "id", None)
    if not user_id:
        raise HTTPException(500, "Failed to create user account")

    # Ensure profile exists
    profile = _ensure_profile(sb, user_id, payload.full_name, payload.email, "student")
    sb.table("profiles").update({"role": "student"}).eq("id", user_id).execute()

    # Create student record
    try:
        sb.table("students").insert({
            "profile_id":      user_id,
            "school_level":    payload.school_level,
            "subjects_needed": payload.subjects_needed,
            "preferred_mode":  payload.preferred_mode.value,
            "home_location":   payload.home_location,
            "parent_name":     payload.parent_name,
            "parent_phone":    payload.parent_phone,
            "category":        payload.category or 'academic',
        }).execute()
    except Exception as e:
        raise HTTPException(400, f"Failed to create student record: {str(e)}")

# Send verification email
    token = secrets.token_urlsafe(32)
    sb.table("profiles").update({"verify_token": token}).eq("id", user_id).execute()
    verify_url = f"https://mathroneacademy.com/verify/{token}"
    await EmailService.send(
        payload.email,
        "Verify your Mathrone Academy account ✅",
        EmailService.template(
            "Welcome to Mathrone Academy! 👑",
            f"Hi {payload.full_name},<br><br>Thank you for joining Mathrone Academy! Please verify your email address to activate your account.",
            verify_url,
            "Verify My Email →"
        )
    )
    # Welcome notification
    await NotificationService.create(
        user_id, "general",
        "Welcome to TutorConnect Academy! 🎓",
        "Your account is ready. Our team will assign you a tutor shortly.",
        sb,
    )

    # Re-fetch profile after role update
    profile = sb.table("profiles").select("*").eq("id", user_id).single().execute().data

    access_token  = create_access_token({"sub": user_id, "role": "student"})
    refresh_token = create_refresh_token({"sub": user_id})
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=profile)


@router.post("/register/tutor", response_model=TokenResponse, status_code=201)
async def register_tutor(payload: RegisterTutorRequest):
    """Register a tutor application (status starts as 'applicant')."""
    sb = get_supabase_admin()

    auth_resp = _create_user_via_supabase(
        payload.email, payload.password, payload.full_name, "tutor"
    )

    user_id = getattr(auth_resp.user, "id", None)
    if not user_id:
        raise HTTPException(500, "Failed to create user account")

    # Ensure profile exists
    _ensure_profile(sb, user_id, payload.full_name, payload.email, "tutor")
    sb.table("profiles").update({
        "role":  "tutor",
        "phone": payload.phone
    }).eq("id", user_id).execute()

    # Create tutor record
    try:
        sb.table("tutors").insert({
            "profile_id":        user_id,
            "status":            "applicant",
            "subjects":          payload.subjects,
            "levels":            payload.levels,
            "teaching_modes":    payload.teaching_modes,
            "experience_years":  payload.experience_years,
            "experience_desc":   payload.experience_desc,
            "qualification":     payload.qualification,
            "education_details": payload.education_details,
            "languages":         payload.languages,
            "bio":               payload.bio,
            "location":          payload.location,
        }).execute()
    except Exception as e:
        raise HTTPException(400, f"Failed to create tutor record: {str(e)}")
# Send verification email
    token = secrets.token_urlsafe(32)
    sb.table("profiles").update({"verify_token": token}).eq("id", user_id).execute()
    verify_url = f"https://mathroneacademy.com/verify/{token}"
    await EmailService.send(
        payload.email,
        "Verify your Mathrone Academy account ✅",
        EmailService.template(
            "Welcome to Mathrone Academy! 👑",
            f"Hi {payload.full_name},<br><br>Thank you for joining Mathrone Academy! Please verify your email address to activate your account.",
            verify_url,
            "Verify My Email →"
        )
    )
    # Notify all admins
    admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
    for admin in admins:
        await NotificationService.create(
            admin["id"], "application_update",
            f"New Tutor Application: {payload.full_name}",
            f"Application for {', '.join(payload.subjects)} has been submitted.",
            sb,
        )

    # Notify applicant
    await NotificationService.create(
        user_id, "application_update",
        "Application Received ✅",
        "Your application has been received. We'll review it within 2–3 business days.",
        sb,
    )

    # Re-fetch profile after role update
    profile = sb.table("profiles").select("*").eq("id", user_id).single().execute().data

    access_token  = create_access_token({"sub": user_id, "role": "tutor"})
    refresh_token = create_refresh_token({"sub": user_id})
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=profile)

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """Login with email and password."""
    sb = get_supabase()
    try:
        resp = sb.auth.sign_in_with_password({
            "email":    payload.email,
            "password": payload.password,
        })
    except Exception:
        raise HTTPException(401, "Invalid email or password")

    user_id = resp.user.id
    sb_admin = get_supabase_admin()

    try:
        profile = sb_admin.table("profiles").select("*").eq("id", user_id).single().execute().data
    except Exception:
        raise HTTPException(401, "Profile not found")

    if not profile:
        raise HTTPException(401, "Profile not found")
    if not profile.get("is_active"):
        raise HTTPException(403, "Account is deactivated. Contact support.")

    access_token  = create_access_token({"sub": user_id, "role": profile["role"]})
    refresh_token = create_refresh_token({"sub": user_id})
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user=profile)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(payload: RefreshRequest):
    """Get a new access token using a refresh token."""
    token_data = decode_token(payload.refresh_token)
    if token_data.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token type")

    user_id = token_data["sub"]
    sb = get_supabase_admin()

    try:
        profile = sb.table("profiles").select("*").eq("id", user_id).single().execute().data
    except Exception:
        raise HTTPException(401, "User not found")

    if not profile:
        raise HTTPException(401, "User not found")

    access_token = create_access_token({"sub": user_id, "role": profile["role"]})
    new_refresh  = create_refresh_token({"sub": user_id})
    return TokenResponse(access_token=access_token, refresh_token=new_refresh, user=profile)


@router.get("/stats")
async def get_platform_stats():
    sb = get_supabase_admin()
    tutors   = sb.table("tutors").select("id", count="exact").eq("status", "approved").execute()
    students = sb.table("students").select("id", count="exact").execute()
    rating   = sb.table("tutors").select("rating").eq("status", "approved").execute()
    ratings  = [t["rating"] for t in rating.data if t.get("rating")]
    avg      = round(sum(ratings) / len(ratings), 1) if ratings else 4.8
    return {
        "tutors":   tutors.count or 0,
        "students": students.count or 0,
        "rating":   avg,
        "sat":      96
    }
@router.post("/logout", response_model=MessageResponse)
async def logout(current_user: dict = Depends(get_current_user)):
    """Sign out — client must discard tokens."""
    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass
    return MessageResponse(message="Logged out successfully")


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get the current user's profile plus their role-specific record."""
    sb = get_supabase_admin()
    profile = dict(current_user)

    if profile["role"] == "student":
        try:
            extra = sb.table("students").select("*").eq("profile_id", profile["id"]).single().execute().data
            profile["student"] = extra
        except Exception:
            profile["student"] = None
    elif profile["role"] == "tutor":
        try:
            extra = sb.table("tutors").select("*").eq("profile_id", profile["id"]).single().execute().data
            profile["tutor"] = extra
        except Exception:
            profile["tutor"] = None

    return profile

@router.get("/verify/{token}")
async def verify_email(token: str):
    sb = get_supabase_admin()
    try:
        profile = sb.table("profiles").select("id, full_name, email").eq("verify_token", token).single().execute().data
    except Exception:
        raise HTTPException(400, "Invalid or expired verification link")
    sb.table("profiles").update({
        "is_verified": True,
        "verify_token": None
    }).eq("id", profile["id"]).execute()
    return {"message": "Email verified successfully! You can now log in."}


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    new_password: str,
    current_user: dict = Depends(get_current_user),
):
    sb = get_supabase_admin()
    if len(new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    sb.auth.admin.update_user_by_id(current_user["id"], {"password": new_password})
    return MessageResponse(message="Password updated successfully")

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(payload: ForgotPasswordRequest):
    import secrets
    from datetime import datetime, timedelta
    from app.services.email_service import EmailService
    sb = get_supabase_admin()
    try:
        profile = sb.table("profiles").select("id, full_name, email").eq("email", payload.email).single().execute().data
    except Exception:
        return MessageResponse(message="If that email exists, a reset link has been sent.")
    token   = secrets.token_urlsafe(32)
    expires = (datetime.utcnow() + timedelta(hours=2)).isoformat()
    sb.table("profiles").update({
        "reset_token":         token,
        "reset_token_expires": expires
    }).eq("id", profile["id"]).execute()
    reset_url = f"https://mathroneacademy.com/reset/{token}"
    try:
        await EmailService.send(
            payload.email,
            "Reset your Mathrone Academy password 🔑",
            EmailService.template(
                "Password Reset Request 🔑",
                f"Hi {profile['full_name']},<br><br>We received a request to reset your password. Click the button below to set a new password. This link expires in 2 hours.<br><br>If you did not request this, ignore this email.",
                reset_url,
                "Reset My Password →"
            )
        )
    except Exception as e:
        print(f"❌ Email send failed: {e}")
        raise HTTPException(500, "Failed to send reset email. Please try again later.")
    
    return MessageResponse(message="If that email exists, a reset link has been sent.")

@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(payload: ResetPasswordRequest):
    from datetime import datetime
    sb = get_supabase_admin()
    try:
        profile = sb.table("profiles").select("id, reset_token_expires").eq("reset_token", payload.token).single().execute().data
    except Exception:
        raise HTTPException(400, "Invalid or expired reset link")
    if datetime.fromisoformat(profile["reset_token_expires"].replace('Z','+00:00')) < datetime.now(tz=__import__('datetime').timezone.utc):
        raise HTTPException(400, "Reset link has expired. Please request a new one.")
    sb.auth.admin.update_user_by_id(profile["id"], {"password": payload.new_password})
    sb.table("profiles").update({
        "reset_token":         None,
        "reset_token_expires": None
    }).eq("id", profile["id"]).execute()
    return MessageResponse(message="Password reset successfully!")

class ContactMessage(BaseModel):
    full_name: str
    email:     EmailStr
    subject:   str
    message:   str

@router.post("/contact", response_model=MessageResponse)
async def send_contact_message(payload: ContactMessage):
    from app.services.email_service import EmailService
    sb = get_supabase_admin()
    
    # Save to contact_messages table
    sb.table("contact_messages").insert({
        "full_name": payload.full_name,
        "email":     payload.email,
        "subject":   payload.subject,
        "message":   payload.message,
    }).execute()

    # Send notification to all admins
    try:
        admins = sb.table("profiles").select("id").eq("role","admin").execute().data or []
        for admin in admins:
            await NotificationService.create(
                admin["id"], "general",
                f"📬 New Contact: {payload.subject}",
                f"From {payload.full_name} ({payload.email}): {payload.message[:100]}",
                sb,
            )
    except Exception:
        pass

    # Send confirmation email to sender
    try:
        await EmailService.send(
            payload.email,
            "We received your message — Mathrone Academy",
            EmailService.template(
                f"Thanks for reaching out, {payload.full_name}! 👋",
                f"We received your message about <strong>{payload.subject}</strong>.<br><br>Our team will get back to you within 24 hours on business days.<br><br>Your message:<br><em>{payload.message}</em>",
            )
        )
    except Exception:
        pass

    return MessageResponse(message="Message sent successfully!")
@router.get("/contact-messages")
async def get_contact_messages(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("contact_messages").select("*").order("created_at", desc=True).execute().data or []

@router.delete("/contact-messages/{message_id}", response_model=MessageResponse)
async def delete_contact_message(
    message_id: str,
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    sb.table("contact_messages").delete().eq("id", message_id).execute()
    return MessageResponse(message="Message deleted")

class ContactReply(BaseModel):
    id:      str
    email:   EmailStr
    name:    str
    subject: str
    message: str

@router.post("/contact-reply", response_model=MessageResponse)
async def reply_contact_message(
    payload: ContactReply,
    admin: dict = Depends(require_admin)
):
    from app.services.email_service import EmailService
    sb = get_supabase_admin()

    # Mark as read
    sb.table("contact_messages").update({"is_read": True}).eq("id", payload.id).execute()

    # Send reply email
    await EmailService.send(
        payload.email,
        f"Re: {payload.subject} — Mathrone Academy",
        EmailService.template(
            f"Reply from Mathrone Academy",
            f"Hi {payload.name},<br><br>{payload.message}<br><br>Best regards,<br><strong>Mathrone Academy Team</strong>",
        )
    )

    return MessageResponse(message="Reply sent successfully!")

@router.get("/settings/recruiting")
async def get_recruiting_status():
    try:
        sb = get_supabase_admin()
        result = sb.table("platform_settings").select("value").eq("key", "is_recruiting").single().execute().data
        return { "is_recruiting": result["value"] == "true" if result else True }
    except Exception:
        return { "is_recruiting": True }

@router.patch("/settings/recruiting")
async def set_recruiting_status(
    payload: dict,
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    sb.table("platform_settings").upsert({
        "key": "is_recruiting",
        "value": "true" if payload.get("is_recruiting") else "false",
        "updated_at": "now()"
    }).execute()
    return { "message": "Recruiting status updated" }

@router.get("/settings/quiz")
async def get_quiz_status():
    sb = get_supabase_admin()
    result = sb.table("platform_settings").select("value").eq("key", "quiz_enabled").single().execute().data
    return { "quiz_enabled": result["value"] != "false" if result else True }

@router.patch("/settings/quiz")
async def set_quiz_status(
    payload: dict,
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    sb.table("platform_settings").upsert({
        "key": "quiz_enabled",
        "value": "true" if payload.get("quiz_enabled") else "false",
        "updated_at": "now()"
    }).execute()
    return { "message": "Quiz status updated" }
