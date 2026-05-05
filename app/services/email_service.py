import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class EmailService:
    @staticmethod
    async def send(to_email: str, subject: str, html_body: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    RESEND_API_URL,
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from":    f"{settings.from_name} <{settings.from_email}>",
                        "to":      [to_email],
                        "subject": subject,
                        "html":    html_body,
                    },
                )

            if response.status_code == 200 or response.status_code == 201:
                logger.info(f"Email sent via Resend to {to_email}")
                return True
            else:
                logger.error(f"Resend error {response.status_code}: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False

    @staticmethod
    def template(
        title: str,
        body: str,
        action_url: str = None,
        action_label: str = None,
    ) -> str:
        btn = (
            f'<div style="text-align:center;margin:30px;">'
            f'<a href="{action_url}" style="background:#1A5FFF;color:#fff;'
            f'padding:12px 25px;text-decoration:none;border-radius:8px;">'
            f"{action_label}</a></div>"
            if action_url
            else ""
        )
        return (
            f"<html><body style='font-family:sans-serif;padding:20px;'>"
            f"<h2>{title}</h2><p>{body}</p>{btn}</body></html>"
        )