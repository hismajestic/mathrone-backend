from supabase import Client


class NotificationService:
    @staticmethod
    async def create(
        user_id: str,
        type: str,
        title: str,
        body: str,
        db: Client,
        data: dict = None,
    ) -> dict:
        """Create a single notification. Silently ignores failures so it never
        breaks the main request flow."""
        try:
            result = db.table("notifications").insert({
                "user_id": user_id,
                "type":    type,
                "title":   title,
                "body":    body,
                "data":    data or {},
            }).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            print(f"[NotificationService] Failed: {e}")
            return {}

    @staticmethod
    async def create_bulk(
        user_ids: list[str],
        type: str,
        title: str,
        body: str,
        db: Client,
        data: dict = None,
    ) -> None:
        """Send the same notification to multiple users in one insert."""
        if not user_ids:
            return
        rows = [
            {"user_id": uid, "type": type, "title": title, "body": body, "data": data or {}}
            for uid in user_ids
        ]
        try:
            db.table("notifications").insert(rows).execute()
        except Exception as e:
            print(f"[NotificationService] Bulk failed: {e}")