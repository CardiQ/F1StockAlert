"""Send notification emails over SMTP.

Configure with env vars (or a .env file in the repo root):
  SMTP_HOST      default smtp.gmail.com
  SMTP_PORT      default 465 (SSL); 587 uses STARTTLS
  SMTP_USER      login, e.g. you@gmail.com
  SMTP_PASSWORD  for Gmail, an App Password (https://myaccount.google.com/apppasswords)
  SMTP_FROM      optional, defaults to SMTP_USER
"""
import os
import smtplib
from email.message import EmailMessage


def send_email(to, subject, body):
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD not set; cannot send email")

    msg = EmailMessage()
    msg["From"] = os.environ.get("SMTP_FROM", user)
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
