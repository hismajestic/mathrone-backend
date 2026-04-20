from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
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

# GZip compression — reduces API response size by ~70%
from fastapi.middleware.gzip import GZipMiddleware
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
