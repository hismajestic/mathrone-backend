from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from app.core.security import get_current_user, require_admin
from app.db.supabase import get_supabase_admin
from pydantic import BaseModel
from typing import Optional, List
import uuid
import asyncio
import re

router = APIRouter(prefix="/shop", tags=["shop"])

# ─── PUBLIC ENDPOINTS ─────────────────────────────────

@router.get("/products")
async def get_products(
    category: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    search: Optional[str] = None,
    featured: Optional[bool] = None
):
    sb = get_supabase_admin()
    query = sb.table("products").select("*").eq("is_active", True)
    if category and category != "all":
        query = query.eq("category", category)
    if featured:
        query = query.eq("is_featured", True)
    products = query.order("created_at", desc=True).execute().data or []
    if min_price is not None:
        products = [p for p in products if p["price"] >= min_price]
    if max_price is not None:
        products = [p for p in products if p["price"] <= max_price]
    if search:
        s = search.lower()
        products = [p for p in products if s in p["name"].lower() or s in (p["description"] or "").lower()]
    return products

@router.get("/products/{product_id}")
async def get_product(product_id: str):
    sb = get_supabase_admin()
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    if uuid_pattern.match(product_id):
        product = sb.table("products").select("*").eq("id", product_id).execute().data
    else:
        product = sb.table("products").select("*").eq("slug", product_id).execute().data
    if not product:
        raise HTTPException(404, "Product not found")
    return product[0]

@router.get("/bundles")
async def get_bundles():
    sb = get_supabase_admin()
    return sb.table("bundles").select("*, bundle_items(*, products(*))").eq("is_active", True).execute().data or []

@router.get("/featured")
async def get_featured():
    sb = get_supabase_admin()
    products = sb.table("products").select("*").eq("is_featured", True).eq("is_active", True).limit(8).execute().data or []
    bundles  = sb.table("bundles").select("*, bundle_items(*, products(*))").eq("is_featured", True).eq("is_active", True).execute().data or []
    return {"products": products, "bundles": bundles}

# ─── CART ─────────────────────────────────────────────

@router.get("/cart")
async def get_cart(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    return sb.table("cart_items").select("*, products(*), bundles(*)").eq("user_id", current_user["id"]).execute().data or []

class CartAdd(BaseModel):
    product_id: Optional[str] = None
    bundle_id:  Optional[str] = None
    quantity:   int = 1

@router.post("/cart")
async def add_to_cart(payload: CartAdd, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    if not payload.product_id and not payload.bundle_id:
        raise HTTPException(400, "product_id or bundle_id required")
    data = {"user_id": current_user["id"], "quantity": payload.quantity}
    if payload.product_id:
        data["product_id"] = payload.product_id
        existing = sb.table("cart_items").select("id, quantity").eq("user_id", current_user["id"]).eq("product_id", payload.product_id).execute().data
        if existing:
            sb.table("cart_items").update({"quantity": existing[0]["quantity"] + payload.quantity}).eq("id", existing[0]["id"]).execute()
            return {"message": "Cart updated"}
    if payload.bundle_id:
        data["bundle_id"] = payload.bundle_id
        existing = sb.table("cart_items").select("id, quantity").eq("user_id", current_user["id"]).eq("bundle_id", payload.bundle_id).execute().data
        if existing:
            sb.table("cart_items").update({"quantity": existing[0]["quantity"] + payload.quantity}).eq("id", existing[0]["id"]).execute()
            return {"message": "Cart updated"}
    sb.table("cart_items").insert(data).execute()
    return {"message": "Added to cart"}

@router.patch("/cart/{item_id}")
async def update_cart_item(item_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    qty = payload.get("quantity", 1)
    if qty < 1:
        sb.table("cart_items").delete().eq("id", item_id).eq("user_id", current_user["id"]).execute()
    else:
        sb.table("cart_items").update({"quantity": qty}).eq("id", item_id).eq("user_id", current_user["id"]).execute()
    return {"message": "Cart updated"}

@router.delete("/cart/{item_id}")
async def remove_from_cart(item_id: str, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    sb.table("cart_items").delete().eq("id", item_id).eq("user_id", current_user["id"]).execute()
    return {"message": "Removed from cart"}

@router.delete("/cart")
async def clear_cart(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    sb.table("cart_items").delete().eq("user_id", current_user["id"]).execute()
    return {"message": "Cart cleared"}

# ─── WISHLIST ─────────────────────────────────────────

@router.get("/wishlist")
async def get_wishlist(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    return sb.table("wishlist").select("*, products(*)").eq("user_id", current_user["id"]).execute().data or []

@router.post("/wishlist/{product_id}")
async def toggle_wishlist(product_id: str, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    existing = sb.table("wishlist").select("id").eq("user_id", current_user["id"]).eq("product_id", product_id).execute().data
    if existing:
        sb.table("wishlist").delete().eq("id", existing[0]["id"]).execute()
        return {"wishlisted": False}
    sb.table("wishlist").insert({"user_id": current_user["id"], "product_id": product_id}).execute()
    return {"wishlisted": True}

# ─── ORDERS ───────────────────────────────────────────

class OrderItem(BaseModel):
    product_id: Optional[str] = None
    bundle_id:  Optional[str] = None
    name:       str
    quantity:   int
    price:      float

class PlaceOrder(BaseModel):
    items:            List[OrderItem]
    total_amount:     float
    payment_method:   str
    payment_phone:    Optional[str] = None
    delivery_address: str
    delivery_phone:   str
    notes:            Optional[str] = None
    momo_reference:   Optional[str] = None
    payment_proof:    Optional[str] = None

@router.post("/orders")
async def place_order(payload: PlaceOrder, current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    
    # Check for duplicate MoMo reference
    if payload.momo_reference:
        existing = sb.table("orders").select("id").eq("momo_reference", payload.momo_reference).execute()
        if existing.data:
            raise HTTPException(400, "This MoMo reference number has already been used.")

    order = sb.table("orders").insert({
        "user_id":          current_user["id"],
        "total_amount":     payload.total_amount,
        "payment_method":   payload.payment_method,
        "payment_phone":    payload.payment_phone,
        "delivery_address": payload.delivery_address,
        "delivery_phone":   payload.delivery_phone,
        "notes":            payload.notes,
        "status":           "pending",
        "momo_reference":   payload.momo_reference,
        "payment_proof":    payload.payment_proof
    }).execute().data[0]
    order_items = []
    for item in payload.items:
        order_items.append({
            "order_id":   order["id"],
            "product_id": item.product_id,
            "bundle_id":  item.bundle_id,
            "name":       item.name,
            "quantity":   item.quantity,
            "price":      item.price
        })
    if order_items:
        sb.table("order_items").insert(order_items).execute()
    sb.table("cart_items").delete().eq("user_id", current_user["id"]).execute()
    try:
        from app.services.notification_service import NotificationService
        admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
        for admin in admins:
            await NotificationService.create(
                admin["id"], "general",
                f"New Order Received! 🛒",
                f"Order #{order['id'][:8].upper()} for RWF {payload.total_amount:,.0f} — {payload.delivery_address}",
                sb
            )
    except Exception:
        pass
    return {"order_id": order["id"], "message": "Order placed successfully!"}

@router.get("/orders/my")
async def my_orders(current_user: dict = Depends(get_current_user)):
    sb = get_supabase_admin()
    return sb.table("orders").select("*, order_items(*)").eq("user_id", current_user["id"]).order("created_at", desc=True).execute().data or []

# ─── ADMIN ────────────────────────────────────────────

@router.get("/orders/admin")
async def admin_orders(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("orders").select("*, order_items(*), profiles(full_name, email)").order("created_at", desc=True).execute().data or []

@router.patch("/orders/admin/{order_id}/status")
async def update_order_status(order_id: str, payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("orders").update({"status": payload.get("status"), "updated_at": "now()"}).eq("id", order_id).execute()
    try:
        from app.services.notification_service import NotificationService
        order = sb.table("orders").select("user_id").eq("id", order_id).single().execute().data
        status = payload.get("status", "")
        messages = {
            "confirmed":  "Your order has been confirmed! We are preparing it.",
            "processing": "Your order is being processed and packed.",
            "shipped":    "Your order is on its way! Expect delivery soon.",
            "delivered":  "Your order has been delivered! Enjoy your products.",
            "cancelled":  "Your order has been cancelled. Contact us for help.",
        }
        if order and status in messages:
            await NotificationService.create(
                order["user_id"], "general",
                f"Order Update: {status.title()} 📦",
                messages[status], sb
            )
    except Exception:
        pass
    return {"message": "Order status updated"}

@router.get("/products/admin/all")
async def get_all_products_admin(admin: dict = Depends(require_admin)):
    """Get all products (including inactive) for admin management"""
    sb = get_supabase_admin()
    products = sb.table("products").select("*").order("created_at", desc=True).execute().data or []
    return products

@router.patch("/products/admin/{product_id}/toggle-active")
async def toggle_product_active(product_id: str, admin: dict = Depends(require_admin)):
    """Toggle product active status"""
    sb = get_supabase_admin()
    product = sb.table("products").select("is_active").eq("id", product_id).execute().data
    if not product:
        raise HTTPException(404, "Product not found")
    new_status = not product[0]["is_active"]
    sb.table("products").update({"is_active": new_status}).eq("id", product_id).execute()
    return {"is_active": new_status, "message": f"Product {'activated' if new_status else 'deactivated'}"}

# ─── PRODUCTS ADMIN ───────────────────────────────────

class ProductCreate(BaseModel):
    name:               str
    slug:               Optional[str] = None
    description:        Optional[str] = None
    full_description:   Optional[str] = None
    price:              float
    category:           str
    stock:              int = 0
    is_featured:        bool = False
    tag:                Optional[str] = None
    image_url:          Optional[str] = None
    extra_images:       Optional[List[str]] = []
    video_url:          Optional[str] = None
    wholesale_enabled:  bool = False
    wholesale_min_qty:  int = 6
    wholesale_price:    Optional[float] = None
    wholesale_label:    Optional[str] = "Box"
    member_discount_pct: float = 3

@router.post("/products/admin")
async def create_product(payload: ProductCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    slug = payload.slug or re.sub(r'\s+', '-', re.sub(r'[^a-z0-9\s-]', '', payload.name.lower().strip()))
    result = sb.table("products").insert({
        "name":             payload.name,
        "slug":             slug,
        "description":      payload.description,
        "full_description": payload.full_description,
        "price":            payload.price,
        "category":         payload.category,
        "stock":            payload.stock,
        "is_featured":      payload.is_featured,
        "tag":              payload.tag,
        "image_url":        payload.image_url,
        "extra_images":     payload.extra_images or [],
        "video_url":        payload.video_url,
        "wholesale_enabled": payload.wholesale_enabled,
        "wholesale_min_qty": payload.wholesale_min_qty,
        "wholesale_price":   payload.wholesale_price,
        "wholesale_label":    payload.wholesale_label,
        "member_discount_pct": payload.member_discount_pct,
    }).execute().data
    return result[0] if result else {}

@router.patch("/products/admin/{product_id}")
async def update_product(product_id: str, payload: ProductCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    slug = payload.slug or re.sub(r'\s+', '-', re.sub(r'[^a-z0-9\s-]', '', payload.name.lower().strip()))
    sb.table("products").update({
        "name":             payload.name,
        "slug":             slug,
        "description":      payload.description,
        "full_description": payload.full_description,
        "price":            payload.price,
        "category":         payload.category,
        "stock":            payload.stock,
        "is_featured":      payload.is_featured,
        "tag":              payload.tag,
        "image_url":        payload.image_url,
        "extra_images":     payload.extra_images or [],
        "video_url":        payload.video_url,
        "wholesale_enabled": payload.wholesale_enabled,
        "wholesale_min_qty": payload.wholesale_min_qty,
        "wholesale_price":   payload.wholesale_price,
        "wholesale_label":    payload.wholesale_label,
        "member_discount_pct": payload.member_discount_pct,
    }).eq("id", product_id).execute()
    return {"message": "Product updated"}

# ─── IMAGE / VIDEO ROUTES (static before dynamic!) ────

@router.post("/products/admin/upload-image")
async def upload_product_image(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    contents = await file.read()
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['jpg', 'jpeg', 'png', 'webp']:
        raise HTTPException(400, "Only JPG, PNG or WebP allowed")
    path = f"products/{uuid.uuid4()}.{ext}"
    content_type = file.content_type
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: sb.storage.from_("product-images").upload(
            path, contents,
            file_options={"content-type": content_type, "upsert": "true"}
        )
    )
    url = sb.storage.from_("product-images").get_public_url(path)
    return {"url": url}

@router.post("/products/admin/upload-extra-image")
async def upload_extra_image(
    file: UploadFile = File(...),
    admin: dict = Depends(require_admin)
):
    sb = get_supabase_admin()
    contents = await file.read()
    ext = file.filename.split('.')[-1].lower()
    if ext not in ['jpg', 'jpeg', 'png', 'webp']:
        raise HTTPException(400, "Only JPG, PNG or WebP allowed")
    path = f"products/extra/{uuid.uuid4()}.{ext}"
    content_type = file.content_type
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: sb.storage.from_("product-images").upload(
            path, contents,
            file_options={"content-type": content_type, "upsert": "true"}
        )
    )
    url = sb.storage.from_("product-images").get_public_url(path)
    return {"url": url}

@router.delete("/products/admin/delete-image")
async def delete_product_image(payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    url = payload.get("url", "")
    if not url:
        raise HTTPException(400, "URL required")
    path = url.split("/product-images/")[-1]
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: sb.storage.from_("product-images").remove([path])
        )
    except Exception as e:
        raise HTTPException(500, f"Storage delete failed: {str(e)}")
    return {"message": "Image deleted from storage"}

@router.delete("/products/admin/delete-video")
async def delete_product_video(product_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("products").update({"video_url": None}).eq("id", product_id).execute()
    return {"message": "Video removed"}

# ─── dynamic product delete LAST so it never swallows static routes ───

@router.delete("/products/admin/{product_id}")
async def delete_product(product_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("products").delete().eq("id", product_id).execute()
    return {"message": "Product deleted"}

# ─── BUNDLES ADMIN ────────────────────────────────────

class BundleCreate(BaseModel):
    name:        str
    description: Optional[str] = None
    price:       float
    image_url:   Optional[str] = None
    is_featured: bool = False
    product_ids: List[dict]

@router.post("/bundles/admin")
async def create_bundle(payload: BundleCreate, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    bundle = sb.table("bundles").insert({
        "name":        payload.name,
        "description": payload.description,
        "price":       payload.price,
        "image_url":   payload.image_url,
        "is_featured": payload.is_featured,
    }).execute().data[0]
    for item in payload.product_ids:
        sb.table("bundle_items").insert({
            "bundle_id":  bundle["id"],
            "product_id": item["product_id"],
            "quantity":   item.get("quantity", 1)
        }).execute()
    return bundle

@router.delete("/bundles/admin/{bundle_id}")
async def delete_bundle(bundle_id: str, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("bundles").delete().eq("id", bundle_id).execute()
    return {"message": "Bundle deleted"}

# ─── GUEST ORDERS ─────────────────────────────────────

class GuestOrderItem(BaseModel):
    name: str
    quantity: int
    price: float
    is_wholesale: bool = False

class GuestOrder(BaseModel):
    full_name: str
    phone: str
    whatsapp: Optional[str] = None
    delivery_address: str
    items: List[GuestOrderItem]
    total_amount: float
    is_wholesale: bool = False
    notes: Optional[str] = None
    momo_reference: Optional[str] = None
    payment_proof: Optional[str] = None

@router.post("/guest-orders")
async def place_guest_order(payload: GuestOrder):
    sb = get_supabase_admin()
    order = sb.table("guest_orders").insert({
        "full_name":        payload.full_name,
        "phone":            payload.phone,
        "whatsapp":         payload.whatsapp or payload.phone,
        "delivery_address": payload.delivery_address,
        "items":            [i.dict() for i in payload.items],
        "total_amount":     payload.total_amount,
        "is_wholesale":     payload.is_wholesale,
        "notes":            payload.notes,
        "momo_reference":   payload.momo_reference,
        "payment_proof":    payload.payment_proof
    }).execute().data[0]
    try:
        from app.services.notification_service import NotificationService
        admins = sb.table("profiles").select("id").eq("role", "admin").execute().data or []
        for admin in admins:
            await NotificationService.create(
                admin["id"], "general",
                f"New Guest Order! 🛒",
                f"From {payload.full_name} ({payload.phone}) — RWF {payload.total_amount:,.0f}",
                sb
            )
    except Exception:
        pass
    return {"order_id": order["id"], "message": "Order received!"}

@router.get("/guest-orders/admin")
async def get_guest_orders(admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    return sb.table("guest_orders").select("*").order("created_at", desc=True).execute().data or []

@router.patch("/guest-orders/admin/{order_id}/status")
async def update_guest_order_status(order_id: str, payload: dict, admin: dict = Depends(require_admin)):
    sb = get_supabase_admin()
    sb.table("guest_orders").update({"status": payload.get("status")}).eq("id", order_id).execute()
    return {"message": "Status updated"}