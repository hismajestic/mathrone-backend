import resend
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:

    @staticmethod
    async def send(to_email: str, subject: str, html_body: str):
        if not settings.resend_api_key:
            logger.warning("Resend API Key not configured — skipping email")
            return
        
        try:
            resend.api_key = settings.resend_api_key
            
            params = {
                "from": f"{settings.from_name} <{settings.from_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }

            # This uses the Resend API (HTTPS), which cloud providers never block
            email = resend.Emails.send(params)
            logger.info(f"Email sent via Resend to {to_email}: {subject} (ID: {email['id']})")
            return email
        except Exception as e:
            logger.error(f"Resend Email failed to {to_email}: {str(e)}")
            # Fallback for dev: log it so you can still see the token if email fails
            print(f"\n--- EMAIL FAILED ---\nTo: {to_email}\nSubject: {subject}\nBody preview: {html_body[:100]}...\n--------------------\n")

    @staticmethod
    def template(title: str, body: str, action_url: str = None, action_label: str = None) -> str:
        action_btn = f"""
        <div style="text-align:center;margin:32px 0">
          <a href="{action_url}" style="background-color:#1A5FFF;color:#ffffff;padding:14px 30px;border-radius:10px;text-decoration:none;font-weight:bold;font-size:16px;display:inline-block;box-shadow:0 4px 12px rgba(26,95,255,0.3)">{action_label}</a>
        </div>""" if action_url and action_label else ""

        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="margin:0;padding:0;background-color:#F8FAFE;font-family:sans-serif;">
          <div style="max-width:600px;margin:20px auto;background-color:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #EEF2FA">
            <div style="background-color:#0D1B40;padding:40px 20px;text-align:center">
              <img src="https://hdpkjomganndiiprnpok.supabase.co/storage/v1/object/public/assets/mathrone%20logo1.png" style="height:50px;width:auto;filter:brightness(0) invert(1)"/>
            </div>
            <div style="padding:40px 30px">
              <h2 style="color:#0D1B40;font-size:22px;margin-top:0">{title}</h2>
              <div style="color:#4A5578;font-size:16px;line-height:1.7">{body}</div>
              {action_btn}
              <hr style="border:none;border-top:1px solid #EEF2FA;margin:30px 0"/>
              <p style="color:#8A98B8;font-size:13px">If you didn't expect this email, you can safely ignore it.</p>
            </div>
          </div>
        </body>
        </html>"""