from fastapi import UploadFile, HTTPException
from app.db.supabase import get_supabase_admin
from app.core.config import settings
import uuid
import os


class StorageService:

    @staticmethod
    async def _upload(file: UploadFile, bucket: str, path: str) -> str:
        sb = get_supabase_admin()
        chunk_size = 1024 * 1024
        size = 0
        contents = bytearray()
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk: break
            size += len(chunk)
            if size > settings.max_upload_size_mb * 1024 * 1024:
                raise HTTPException(413, f"File too large. Max {settings.max_upload_size_mb}MB")
            contents.extend(chunk)

        try: sb.storage.from_(bucket).remove([path])
        except: pass

        try:
            sb.storage.from_(bucket).upload(
                path=path,
                file=bytes(contents),
                file_options={"content-type": file.content_type or "application/octet-stream"},
            )
        except Exception as e:
            raise HTTPException(500, f"Upload failed: {str(e)}")

        return sb.storage.from_(bucket).get_public_url(path)

    @staticmethod
    async def upload_cv(file: UploadFile, user_id: str) -> str:
        allowed = [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ]
        if file.content_type not in allowed:
            raise HTTPException(400, "CV must be a PDF or Word document (.pdf, .doc, .docx)")
        ext  = os.path.splitext(file.filename or "cv")[1] or ".pdf"
        path = f"{user_id}/cv{ext}"
        return await StorageService._upload(file, settings.storage_bucket_cvs, path)

    @staticmethod
    async def upload_certificate(file: UploadFile, user_id: str) -> str:
        allowed = ["application/pdf", "image/jpeg", "image/png", "image/webp"]
        if file.content_type not in allowed:
            raise HTTPException(400, "Certificate must be a PDF or image (JPEG, PNG, WebP)")
        ext  = os.path.splitext(file.filename or "cert")[1] or ".pdf"
        path = f"{user_id}/{uuid.uuid4()}{ext}"
        return await StorageService._upload(file, settings.storage_bucket_certs, path)

    @staticmethod
    async def upload_avatar(file: UploadFile, user_id: str) -> str:
        allowed = ["image/jpeg", "image/png", "image/webp"]
        if file.content_type not in allowed:
            raise HTTPException(400, "Avatar must be a JPEG, PNG, or WebP image")
        ext  = os.path.splitext(file.filename or "avatar")[1] or ".jpg"
        path = f"{user_id}/avatar{ext}"
        return await StorageService._upload(file, settings.storage_bucket_avatars, path)

    @staticmethod
    async def upload_material(file: UploadFile, session_id: str) -> str:
        safe_name = file.filename or "file"
        path = f"{session_id}/{uuid.uuid4()}_{safe_name}"
        return await StorageService._upload(file, settings.storage_bucket_materials, path)