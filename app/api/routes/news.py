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

def generate_description(content: str, max_length: int = 160) -> str:
    """Generate meta description from content"""
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
                        action_url=f"https://mathrone-academy.netlify.app/news-article/{new_post['id']}",
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
    related = sb.table("news_posts").select(
        "id, title, image_url, created_at, views_count"
    ).neq("id", post_id).or_(
        f"category.eq.{post['category']}",
        *[f"tags.cs.{{{tag}}}" for tag in post['tags']]
    ).order("views_count", desc=True).limit(limit).execute().data or []
    
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
@router.post("/upload-image")
async def upload_news_image(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    contents = await file.read()
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['jpg','jpeg','png','webp','gif']:
        raise HTTPException(400, "Only JPG, PNG, WebP or GIF allowed")
    import uuid
    path = f"news/{uuid.uuid4()}.{ext}"
    sb.storage.from_("news-images").upload(
        path, contents,
        file_options={"content-type": file.content_type, "upsert": "true"}
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
        redirect_url = f"https://mathrone-academy.netlify.app/#news-article/{post_id}"
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
        return HTMLResponse('<meta http-equiv="refresh" content="0;url=https://mathrone-academy.netlify.app"/>')