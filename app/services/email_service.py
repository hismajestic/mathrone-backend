import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:
    @staticmethod
    async def send(to_email: str, subject: str, html_body: str):
        try:
            msg = MIMEMultipart()
            msg["From"] = f"{settings.from_name} <{settings.from_email}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(html_body, "html"))

            # Gmail SMTP logic
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.from_email, to_email, msg.as_string())
            server.quit()
            
            logger.info(f"Email sent to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            print(f"DEBUG SMTP ERROR: {e}")
            return False

    @staticmethod
    def template(title: str, body: str, action_url: str = None, action_label: str = None) -> str:
        btn = f'<div style="text-align:center;margin:30px;"><a href="{action_url}" style="background:#1A5FFF;color:#fff;padding:12px 25px;text-decoration:none;border-radius:8px;">{action_label}</a></div>' if action_url else ""
        return f"<html><body style='font-family:sans-serif;padding:20px;'><h2>{title}</h2><p>{body}</p>{btn}</body></html>"