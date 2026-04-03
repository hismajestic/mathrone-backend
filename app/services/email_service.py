import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:

    @staticmethod
    async def send(to_email: str, subject: str, html_body: str):
        if not settings.smtp_user or not settings.smtp_password:
            logger.warning("SMTP not configured — skipping email")
            return
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"]    = f"{settings.from_name} <{settings.from_email}>"
            msg["To"]      = to_email
            msg.attach(MIMEText(html_body, "html"))
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.from_email, to_email, msg.as_string())
            logger.info(f"Email sent to {to_email}: {subject}")
        except Exception as e:
            logger.error(f"Email failed to {to_email}: {e}")

    @staticmethod
    def template(title: str, body: str, action_url: str = None, action_label: str = None) -> str:
        action_btn = f"""
        <div style="text-align:center;margin:24px 0">
          <a href="{action_url}" style="background:#2563eb;color:#fff;padding:12px 28px;border-radius:8px;text-decoration:none;font-weight:600;font-size:15px">{action_label}</a>
        </div>""" if action_url and action_label else ""

        return f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="margin:0;padding:0;background:#f1f5f9;font-family:'Segoe UI',Arial,sans-serif">
          <div style="max-width:600px;margin:40px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
            <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:32px 40px;text-align:center">
              <div style="font-size:36px;margin-bottom:8px">👑</div>
              <h1 style="color:#fff;margin:0;font-size:22px;font-weight:800">Mathrone Academy</h1>
            </div>
            <div style="padding:32px 40px">
              <h2 style="color:#1e3a5f;font-size:20px;margin:0 0 16px">{title}</h2>
              <div style="color:#475569;font-size:15px;line-height:1.6;margin:0 0 16px">{body}</div>
              {action_btn}
            </div>
            <div style="background:#f8fafc;padding:20px 40px;text-align:center;border-top:1px solid #e2e8f0">
              <p style="color:#94a3b8;font-size:12px;margin:0">© 2025 Mathrone Academy. All rights reserved.</p>
            </div>
          </div>
        </body>
        </html>"""