from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel
from typing import Optional
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from app.services.email_service import EmailService
import asyncio
import re

def generate_slug(title: str) -> str:
    """Generate SEO-friendly slug from title"""
    # Convert to lowercase, replace spaces with hyphens, remove special chars
    slug = title.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)  # Remove special characters
    slug = re.sub(r'[\s_]+', '-', slug)   # Replace spaces/underscores with hyphens
    slug = re.sub(r'-+', '-', slug)       # Replace multiple hyphens with single
    return slug.strip('-')

def generate_description(content: str, max_length: int = 300) -> str:
    """Generate meta description from content (defaulting to 300 for flexibility)"""
    # Remove HTML tags and get first part of content
    clean_content = re.sub(r'<[^>]+>', '', content)
    description = clean_content.strip()
    if len(description) > max_length:
        description = description[:max_length-3] + '...'
    return description

def generate_tags(content: str, title: str = "", max_tags: int = 5) -> list[str]:
    """Generate relevant tags from article content and title"""
    try:
        # Remove HTML tags
        clean_content = re.sub(r'<[^>]+>', '', content)
        text = f"{title} {clean_content}".lower()
        
        # Remove special characters and numbers
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\d+', '', text)
        
        # Simple tokenization (split by spaces)
        words = text.split()
        
        # Remove stopwords (common words)
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 
            'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 
            'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 
            'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them'
        }
        
        # Filter words
        filtered_words = [
            word for word in words 
            if word not in stop_words 
            and len(word) > 3  # Only words longer than 3 characters
            and word.isalpha()  # Only alphabetic words
        ]
        
        # Count frequency
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # Sort by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        
        # Get most common words as tags
        common_words = [word for word, freq in sorted_words]
        
        # Prioritize education-related keywords
        education_keywords = {
            'education', 'school', 'university', 'college', 'student', 'teacher', 'tutor', 'learning', 
            'academic', 'scholarship', 'exam', 'test', 'grade', 'class', 'course', 'subject', 
            'math', 'science', 'english', 'history', 'geography', 'physics', 'chemistry', 'biology',
            'rwanda', 'kigali', 'africa', 'government', 'ministry', 'reb', 'mineduc', 'unesco',
            'online', 'digital', 'technology', 'computer', 'internet', 'mobile', 'app',
            'career', 'job', 'employment', 'opportunity', 'training', 'skill', 'development'
        }
        
        # Prioritize education keywords, then fill with other common words
        tags = []
        for word in common_words:
            if word in education_keywords and word not in tags:
                tags.append(word)
            elif len(tags) < max_tags and word not in tags:
                tags.append(word)
        
        # Ensure we have at least some tags
        if not tags:
            tags = common_words[:max_tags] if common_words else []
        
        return tags[:max_tags]
        
    except Exception as e:
        print(f"Error generating tags: {e}")
        return []

router = APIRouter(prefix="/news", tags=["News"])


class NewsCreate(BaseModel):
    title:       str
    content:     str
    category:    str = "news"
    tags:        list[str] = []
    image_url:   Optional[str] = None
    source_url:  Optional[str] = None
    source_name: Optional[str] = None
    is_featured: bool = False
    slug:        Optional[str] = None
    description: Optional[str] = None

class NewsletterSubscribe(BaseModel):
    email: str

class ImageDeletePayload(BaseModel):
    path: str
# ── Admin: cleanup orphaned payment proof images ───────────────────────────────
@router.delete("/admin/cleanup-proofs")
async def cleanup_payment_proofs(admin: dict = Depends(require_admin)):
    """
    Scans payment-proofs/ folder in storage and deletes any images
    that are not referenced in orders or guest_orders tables.
    Safe to run anytime — only deletes truly orphaned files.
    """
    sb = get_supabase_admin()

    # 1. Get all files in payment-proofs/ folder
    try:
        storage_files = sb.storage.from_("news-images").list("payment-proofs")
    except Exception as e:
        raise HTTPException(500, f"Could not list storage files: {str(e)}")

    if not storage_files:
        return {"deleted": 0, "message": "No proof files found in storage"}

    # 2. Collect all proof URLs referenced in both orders tables
    referenced_urls = set()
    try:
        member_orders = sb.table("orders").select("payment_proof").not_.is_("payment_proof", "null").execute()
        for o in (member_orders.data or []):
            if o.get("payment_proof"):
                referenced_urls.add(o["payment_proof"])
    except Exception:
        pass

    try:
        guest_orders = sb.table("guest_orders").select("payment_proof").not_.is_("payment_proof", "null").execute()
        for o in (guest_orders.data or []):
            if o.get("payment_proof"):
                referenced_urls.add(o["payment_proof"])
    except Exception:
        pass

    try:
        course_orders = sb.table("course_orders").select("payment_proof").not_.is_("payment_proof", "null").execute()
        for o in (course_orders.data or []):
            if o.get("payment_proof"):
                referenced_urls.add(o["payment_proof"])
    except Exception:
        pass

    # 3. Find orphaned files — in storage but not in any order
    to_delete = []
    for f in storage_files:
        fname = f.get("name", "")
        full_path = f"payment-proofs/{fname}"
        # Build what the public URL would look like for this file
        public_url = sb.storage.from_("news-images").get_public_url(full_path)
        if public_url not in referenced_urls:
            to_delete.append(full_path)

    if not to_delete:
        return {"deleted": 0, "message": "No orphaned proof images found — storage is clean ✅"}

    # 4. Delete orphaned files in batches of 20
    deleted = 0
    errors = []
    batch_size = 20
    for i in range(0, len(to_delete), batch_size):
        batch = to_delete[i:i + batch_size]
        try:
            sb.storage.from_("news-images").remove(batch)
            deleted += len(batch)
        except Exception as e:
            errors.append(str(e))

    return {
        "deleted": deleted,
        "errors": errors if errors else None,
        "message": f"Cleaned up {deleted} orphaned proof image{'s' if deleted != 1 else ''} ✅"
    }
# ── Public: upload payment proof (no auth required — guest users) ──────────────
@router.post("/public/upload-proof")
async def upload_payment_proof(file: UploadFile = File(...)):
    """
    Public endpoint for guest users to upload payment screenshots.
    Strictly images only, stored in payment-proofs/ folder.
    No authentication required.
    """
    import uuid

    # Strict image-only validation
    ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(400, "Only image files are allowed (JPG, PNG, WEBP)")

    # Max 5MB
    MAX_SIZE = 5 * 1024 * 1024
    file_bytes = await file.read()
    if len(file_bytes) > MAX_SIZE:
        raise HTTPException(400, "File too large. Maximum size is 5MB.")

    ext = (file.filename or "image.jpg").split(".")[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "webp", "gif"}:
        ext = "jpg"

    filename = f"payment-proofs/{uuid.uuid4()}.{ext}"

    try:
        sb = get_supabase_admin()
        sb.storage.from_("news-images").upload(
            path=filename,
            file=file_bytes,
            file_options={"content-type": file.content_type}
        )
        url = sb.storage.from_("news-images").get_public_url(filename)
        return {"url": url}
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {str(e)}")

# ── Get all news posts ─────────────────────────────────────────────────────────
@router.get("/")
async def get_news(
    category: Optional[str] = None,
    featured: Optional[bool] = None,
    popular: Optional[bool] = None,
    search: Optional[str] = None,
    limit: int = 20,
    offset: int = 0
):
    sb = get_supabase_admin()
    query = sb.table("news_posts").select(
        "*"
    )
    
    if category:
        query = query.eq("category", category)
    if featured is not None:
        query = query.eq("is_featured", featured)
    
    if search:
        query = query.or_(f"title.ilike.%{search}%,content.ilike.%{search}%")
    
    if popular:
        query = query.order("views_count", desc=True)
    else:
        query = query.order("is_featured", desc=True).order("created_at", desc=True)
    
    query = query.range(offset, offset + limit - 1)
    return query.execute().data or []

# ── Get single news post ───────────────────────────────────────────────────────
@router.get("/{post_id}")
async def get_news_post(post_id: str):
    sb = get_supabase_admin()
    try:
        # Get current views count first
        current_post = sb.table("news_posts").select("views_count").eq("id", post_id).single().execute().data
        if not current_post:
            raise HTTPException(404, "Post not found")
        
        # Increment views
        new_views = (current_post["views_count"] or 0) + 1
        sb.table("news_posts").update({"views_count": new_views}).eq("id", post_id).execute()
        
        return sb.table("news_posts").select(
            "*"
        ).eq("id", post_id).single().execute().data
    except Exception:
        raise HTTPException(404, "Post not found")

# ── Get news post by slug ─────────────────────────────────────────────────────
@router.get("/by-slug/{slug}")
async def get_news_post_by_slug(slug: str):
    
    sb = get_supabase_admin()
    try:
        # Get current views count first
        current_post = sb.table("news_posts").select("views_count").eq("slug", slug).single().execute().data
        if not current_post:
            raise HTTPException(404, "Post not found")
        
        # Increment views
        new_views = (current_post["views_count"] or 0) + 1
        sb.table("news_posts").update({"views_count": new_views}).eq("slug", slug).execute()
        
        return sb.table("news_posts").select(
            "*"
        ).eq("slug", slug).single().execute().data
    except Exception:
        raise HTTPException(404, "Post not found")

# ── Admin creates news post ────────────────────────────────────────────────────
@router.post("/", status_code=201)
async def create_news(payload: NewsCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    
    # Generate slug and description if not provided
    slug = payload.slug or generate_slug(payload.title)
    description = payload.description or generate_description(payload.content)
    
    # Generate tags if not provided
    tags = payload.tags if payload.tags else generate_tags(payload.content, payload.title)
    
    result = sb.table("news_posts").insert({
        "title":        payload.title,
        "content":      payload.content,
        "category":     payload.category,
        "tags":         tags,
        "image_url":    payload.image_url,
        "source_url":   payload.source_url,
        "source_name":  payload.source_name,
        "is_featured":  payload.is_featured,
        "slug":         slug,
        "description":  description,
        "published_by": admin["id"],
    }).execute()
    
    new_post = result.data[0]
    
    # Send email notifications to newsletter subscribers
    try:
        subscribers = sb.table("newsletter_subscriptions").select("email").eq("is_active", True).execute().data or []
        if subscribers:
            # Get category display name
            category_names = {
                "news": "Education News",
                "scholarship": "Scholarships", 
                "government": "Government Updates",
                "career": "Career Opportunities",
                "abroad": "Study Abroad",
                "resources": "Learning Resources"
            }
            category_display = category_names.get(payload.category, payload.category.title())
            
            subject = f"📰 New {category_display} - {payload.title}"
            body = f"""
            <p>We've published a new article that might interest you:</p>
            <h3>{payload.title}</h3>
            <p><strong>Category:</strong> {category_display}</p>
            <p>{payload.content[:200]}{'...' if len(payload.content) > 200 else ''}</p>
            """
            
            # Send emails asynchronously
            tasks = []
            for subscriber in subscribers:
                tasks.append(EmailService.send(
                    subscriber["email"], 
                    subject, 
                    EmailService.template(
                        title=f"New {category_display} Article",
                        body=body,
                        action_url=f"https://mathroneacademy.com/news/{new_post.get('slug') or new_post['id']}",
                        action_label="Read Article"
                    )
                ))
            asyncio.create_task(asyncio.gather(*tasks, return_exceptions=True))
    except Exception as e:
        print(f"Failed to send newsletter emails: {e}")
        # Don't fail the request if email sending fails
    
    return new_post

# ── Admin updates news post ────────────────────────────────────────────────────
@router.patch("/{post_id}")
async def update_news(post_id: str, payload: NewsCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    
    # Generate slug and description if not provided
    slug = payload.slug or generate_slug(payload.title)
    description = payload.description or generate_description(payload.content)
    
    # Generate tags if not provided
    tags = payload.tags if payload.tags else generate_tags(payload.content, payload.title)
    
    result = sb.table("news_posts").update({
        "title":        payload.title,
        "content":      payload.content,
        "category":     payload.category,
        "tags":         tags,
        "image_url":    payload.image_url,
        "source_url":   payload.source_url,
        "source_name":  payload.source_name,
        "is_featured":  payload.is_featured,
        "slug":         slug,
        "description":  description,
        "updated_at":   "now()",
    }).eq("id", post_id).execute()
    return result.data[0]

# ── Admin deletes image from storage ──────────────────────────────────────────
@router.delete("/delete-image")
async def delete_news_image(
    payload: ImageDeletePayload,
    admin: dict = Depends(require_admin)
):
    """Delete an image from Supabase Storage"""
    sb = get_supabase_admin()
    path = payload.path
    if not path:
        raise HTTPException(400, "No path provided")
    try:
        sb.storage.from_("news-images").remove([path])
        return {"message": "Image deleted"}
    except Exception as e:
        raise HTTPException(500, f"Failed to delete image: {str(e)}")

# ── Admin deletes news post ────────────────────────────────────────────────────
@router.delete("/{post_id}")
async def delete_news(post_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("news_posts").delete().eq("id", post_id).execute()
    return {"message": "Post deleted"}

# ── Get related articles ───────────────────────────────────────────────────────
@router.get("/{post_id}/related")
async def get_related_articles(post_id: str, limit: int = 5):
    sb = get_supabase_admin()
    # Get current post's tags and category
    post = sb.table("news_posts").select("tags, category").eq("id", post_id).single().execute().data
    if not post:
        return []
    
    # Find posts with matching tags or category, excluding current post
    # Combine all OR conditions into a single comma-separated string
    or_conditions = [f"category.eq.{post.get('category')}"]
    if post.get('tags'):
        or_conditions.extend([f"tags.cs.{{{tag}}}" for tag in post['tags']])
    
    or_string = ",".join(or_conditions)

    related = sb.table("news_posts").select(
        "id, title, image_url, created_at, views_count"
    ).neq("id", post_id).or_(or_string).order("views_count", desc=True).limit(limit).execute().data or []
    
    return related

# ── Subscribe to newsletter ────────────────────────────────────────────────────
@router.post("/subscribe")
async def subscribe_newsletter(payload: NewsletterSubscribe):
    sb = get_supabase_admin()
    try:
        result = sb.table("newsletter_subscriptions").insert({
            "email": payload.email
        }).execute()
        return {"message": "Subscribed successfully"}
    except Exception as e:
        if "duplicate key" in str(e):
            raise HTTPException(400, "Email already subscribed")
        raise HTTPException(400, "Subscription failed")
from PIL import Image
import io

@router.post("/upload-image")
async def upload_news_image(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    
    # 1. Load image into Pillow
    try:
        contents = await file.read()
        img = Image.open(io.BytesIO(contents))
    except Exception:
        raise HTTPException(400, "Invalid image file")

    # 2. Convert to RGB (removes Alpha channel transparency for smaller JPEGs)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # 3. Smart Resize (Max 1200px width/height while keeping aspect ratio)
    img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

    # 4. Compress and Save to a buffer
    output = io.BytesIO()
    img.save(output, format="JPEG", quality=85, optimize=True)
    output.seek(0)

    # 5. Upload to Supabase
    import uuid
    path = f"news/{uuid.uuid4()}.jpg"
    sb.storage.from_("news-images").upload(
        path, output.read(),
        file_options={"content-type": "image/jpeg", "upsert": "true"}
    )
    
    url = sb.storage.from_("news-images").get_public_url(path)
    return {"url": url}
from fastapi.responses import HTMLResponse

@router.get("/preview/{post_id}", response_class=HTMLResponse)
async def news_preview(post_id: str):
    sb = get_supabase_admin()
    try:
        post = sb.table("news_posts").select("title, content, image_url").eq("id", post_id).single().execute().data
        if not post:
            raise HTTPException(404, "Post not found")
        description = post["content"].replace("<", " ").replace(">", " ")
        description = " ".join(description.split())[:150] + "..."
        image = post["image_url"] or "https://images.unsplash.com/photo-1523240795612-9a054b0db644?w=1200&q=80"
        redirect_url = f"https://mathroneacademy.com/news/{post_id}"
        return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <title>{post["title"]} — Mathrone Academy</title>
  <meta property="og:title" content="{post["title"]}"/>
  <meta property="og:description" content="{description}"/>
  <meta property="og:image" content="{image}"/>
  <meta property="og:url" content="{redirect_url}"/>
  <meta property="og:type" content="article"/>
  <meta name="twitter:card" content="summary_large_image"/>
  <meta name="twitter:title" content="{post["title"]}"/>
  <meta name="twitter:description" content="{description}"/>
  <meta name="twitter:image" content="{image}"/>
  <meta http-equiv="refresh" content="0;url={redirect_url}"/>
  <script>window.location.href="{redirect_url}"</script>
</head>
<body>Redirecting to article...</body>
</html>""")
    except Exception:
        return HTMLResponse('<meta http-equiv="refresh" content="0;url=https://mathroneacademy.com"/>')