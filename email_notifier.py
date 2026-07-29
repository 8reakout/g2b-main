from __future__ import annotations

import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def _split_emails(value: str) -> list[str]:
    return [x.strip() for x in (value or "").replace(";", ",").split(",") if x.strip()]


def send_html_email(subject: str, html_body: str, attachment_path: str | None = None) -> None:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes", "y"}
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    mail_from = os.getenv("MAIL_FROM", smtp_user)
    mail_to = _split_emails(os.getenv("MAIL_TO", ""))
    mail_cc = _split_emails(os.getenv("MAIL_CC", ""))

    if not smtp_user or not smtp_password:
        raise ValueError("SMTP_USER 또는 SMTP_PASSWORD 값이 없습니다.")
    if not mail_from:
        raise ValueError("MAIL_FROM 값이 없습니다.")
    if not mail_to:
        raise ValueError("MAIL_TO 값이 없습니다.")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = ", ".join(mail_to)
    if mail_cc:
        msg["Cc"] = ", ".join(mail_cc)

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText("HTML 이메일을 지원하는 클라이언트에서 확인해주세요.", "plain", "utf-8"))
    alternative.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alternative)

    if attachment_path:
        path = Path(attachment_path)
        if path.exists() and path.is_file():
            with path.open("rb") as f:
                part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)

    recipients = mail_to + mail_cc

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        if smtp_use_tls:
            server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(mail_from, recipients, msg.as_string())
