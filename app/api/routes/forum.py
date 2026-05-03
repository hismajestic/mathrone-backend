from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/forum", tags=["Forum"])

class PostCreate(BaseModel):
    title:    str
    content:  str
    category: str = "general"

class CommentCreate(BaseModel):
    content: str

# ── Get all approved posts ─────────────────────────────────────────────────────
@router.get("/posts")
async def get_posts(category: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    query = sb.table("forum_posts").select(
        "*, profiles!forum_posts_author_id_fkey(full_name, avatar_url, role)"
    ).eq("status", "approved").order("is_pinned", desc=True).order("created_at", desc=True)
    if category:
        query = query.eq("category", category)
    return query.execute().data or []

# ── Create post ────────────────────────────────────────────────────────────────
@router.post("/posts", status_code=201)
async def create_post(payload: PostCreate, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    result = sb.table("forum_posts").insert({
        "author_id": current_user["id"],
        "title":     payload.title,
        "content":   payload.content,
        "category":  payload.category,
        "status":    "pending",
    }).execute()

    # Notify admins
    admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
    for admin in admins:
        try:
            await NotificationService.create(
                admin["id"], "general",
                "New Forum Post Pending ✍️",
                f"A new post '{payload.title}' needs your approval.",
                sb,
            )
        except Exception:
            pass

    return {"message": "Post submitted for review! ✅"}

# ── Get comments for a post ────────────────────────────────────────────────────
@router.get("/posts/{post_id}/comments")
async def get_comments(post_id: str, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    return sb.table("forum_comments").select(
        "*, profiles!forum_comments_author_id_fkey(full_name, avatar_url, role)"
    ).eq("post_id", post_id).order("created_at").execute().data or []

# ── Add comment ────────────────────────────────────────────────────────────────
@router.post("/posts/{post_id}/comments", status_code=201)
async def add_comment(post_id: str, payload: CommentCreate, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    post = sb.table("forum_posts").select("author_id, title").eq("id", post_id).single().execute().data
    if not post:
        raise HTTPException(404, "Post not found")
    sb.table("forum_comments").insert({
        "post_id":   post_id,
        "author_id": current_user["id"],
        "content":   payload.content,
    }).execute()

    # Notify post author
    if post["author_id"] != current_user["id"]:
        try:
            await NotificationService.create(
                post["author_id"], "general",
                "New Comment on your post 💬",
                f"Someone commented on your post '{post['title']}'.",
                sb,
            )
        except Exception:
            pass

    return {"message": "Comment added! ✅"}

# ── Like/Unlike post ───────────────────────────────────────────────────────────
@router.post("/posts/{post_id}/like")
async def like_post(post_id: str, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    existing = sb.table("forum_likes").select("id").eq("post_id", post_id).eq("user_id", current_user["id"]).execute().data
    post = sb.table("forum_posts").select("likes").eq("id", post_id).single().execute().data
    current_likes = post.get("likes", 0) or 0
    if existing:
        sb.table("forum_likes").delete().eq("post_id", post_id).eq("user_id", current_user["id"]).execute()
        sb.table("forum_posts").update({"likes": max(0, current_likes - 1)}).eq("id", post_id).execute()
        return {"liked": False}
    else:
        sb.table("forum_likes").insert({"post_id": post_id, "user_id": current_user["id"]}).execute()
        sb.table("forum_posts").update({"likes": current_likes + 1}).eq("id", post_id).execute()
        return {"liked": True}

# ── Admin — get pending posts ──────────────────────────────────────────────────
@router.get("/admin/pending")
async def get_pending_posts(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("forum_posts").select(
        "*, profiles!forum_posts_author_id_fkey(full_name, avatar_url, role)"
    ).eq("status", "pending").order("created_at").execute().data or []

# ── Admin — approve/reject post ───────────────────────────────────────────────
@router.patch("/admin/posts/{post_id}")
async def moderate_post(post_id: str, action: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    if action not in ["approved", "rejected"]:
        raise HTTPException(400, "Action must be approved or rejected")
    post = sb.table("forum_posts").select("author_id, title").eq("id", post_id).single().execute().data
    sb.table("forum_posts").update({"status": action}).eq("id", post_id).execute()
    try:
        await NotificationService.create(
            post["author_id"], "general",
            f"Your post was {action} {'✅' if action == 'approved' else '❌'}",
            f"Your forum post '{post['title']}' has been {action} by admin.",
            sb,
        )
    except Exception:
        pass
    return {"message": f"Post {action}"}

# ── Admin — pin/unpin post ─────────────────────────────────────────────────────
@router.patch("/admin/posts/{post_id}/pin")
async def pin_post(post_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    post = sb.table("forum_posts").select("is_pinned").eq("id", post_id).single().execute().data
    sb.table("forum_posts").update({"is_pinned": not post["is_pinned"]}).eq("id", post_id).execute()
    return {"pinned": not post["is_pinned"]}
@router.delete("/admin/posts/{post_id}")
async def delete_post(post_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    post = sb.table("forum_posts").select("author_id, title").eq("id", post_id).single().execute().data
    if not post:
        raise HTTPException(404, "Post not found")
    sb.table("forum_posts").delete().eq("id", post_id).execute()
    try:
        await NotificationService.create(
            post["author_id"], "general",
            "Your post was removed ❌",
            f"Your forum post '{post['title']}' was removed by admin.",
            sb,
        )
    except Exception:
        pass
    return {"message": "Post deleted"}