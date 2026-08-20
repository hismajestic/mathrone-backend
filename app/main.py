from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from collections import defaultdict
import time
from app.api.routes.news import router as news_router
from app.api.routes.exam import router as exam_router
from app.api.routes.shop import router as shop_router
from app.core.config import settings
from app.api.routes.auth   import router as auth_router
from app.api.routes.tutors import router as tutors_router
from app.api.routes.routes import (
    students_router,
    sessions_router,
    messages_router,
    notifications_router,
    payments_router,
)
from app.api.routes.progress import router as progress_router
from app.api.routes.forum import router as forum_router
from app.api.routes.lab import router as lab_router
from app.api.routes.quiz import router as quiz_router
from app.api.routes.courses import router as courses_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"🎓 {settings.app_name} v{settings.app_version} — starting")
    print(f"   Supabase: {settings.supabase_url}")
    print(f"   CORS:     {settings.allowed_origins_list}")
    yield
    print("Shutting down...")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## Mathrone Academy API

Full-featured tutoring platform built with **FastAPI** and **Supabase**.

### Roles
- **Student** — find tutors, view sessions, chat, pay invoices
- **Tutor**   — manage profile, view students, upload CV/certificates
- **Admin**   — manage recruitment pipeline, assign tutors, schedule sessions, invoicing

### Auth
All protected endpoints require `Authorization: Bearer <access_token>`.
""",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
origins = [
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

# ── CORS ───────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Simple in-memory rate limiter ─────────────────────────────────────────────
# Limits abusive IPs on public endpoints without requiring Redis
_rate_store: dict = defaultdict(list)
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX    = 20   # max requests per window per IP

RATE_LIMITED_PATHS = {
    "/api/v1/news/subscribe",
    "/api/v1/news/public/upload-proof",
    "/api/v1/auth/contact",
}

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in RATE_LIMITED_PATHS:
        ip = request.headers.get("CF-Connecting-IP") or request.client.host
        now = time.time()
        window_start = now - RATE_LIMIT_WINDOW
        hits = _rate_store[ip] = [t for t in _rate_store[ip] if t > window_start]
        if len(hits) >= RATE_LIMIT_MAX:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )
        _rate_store[ip].append(now)
    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=500)

# ── Routes ─────────────────────────────────────────────────────────────────────
V1 = "/api/v1"
app.include_router(auth_router,          prefix=V1)
app.include_router(tutors_router,        prefix=V1)
app.include_router(students_router,      prefix=V1)
app.include_router(sessions_router,      prefix=V1)
app.include_router(messages_router,      prefix=V1)
app.include_router(notifications_router, prefix=V1)
app.include_router(payments_router,      prefix=V1)
app.include_router(progress_router,      prefix=V1)
app.include_router(forum_router,         prefix=V1)
app.include_router(news_router, prefix=V1)
app.include_router(exam_router, prefix="/api/v1")
app.include_router(shop_router, prefix="/api/v1")
app.include_router(lab_router, prefix="/api/v1")
app.include_router(quiz_router, prefix="/api/v1")
app.include_router(courses_router, prefix=V1)


@app.get("/", tags=["Health"])
async def root():
    return {
        "name":    settings.app_name,
        "version": settings.app_version,
        "status":  "running",
        "docs":    "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}
@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "mathrone-backend"}
