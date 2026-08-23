"""SMTP 邮件推送。"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate

log = logging.getLogger(__name__)


def send(html: str, cfg, date_label: str) -> bool:
    email_cfg = (cfg.notifications or {}).get("email", {})
    if not email_cfg.get("enabled", False):
        log.info("邮件推送未启用，跳过")
        return False

    host = os.getenv("SMTP_HOST") or email_cfg.get("host")
    port = int(os.getenv("SMTP_PORT") or email_cfg.get("port", 465))
    use_ssl = (os.getenv("SMTP_USE_SSL") or str(email_cfg.get("use_ssl", True))).lower() == "true"
    user = os.getenv("SMTP_USER") or email_cfg.get("user")
    pwd = os.getenv("SMTP_PASSWORD") or email_cfg.get("password")
    sender = os.getenv("SMTP_FROM") or user
    recipients = email_cfg.get("recipients", [])
    if not (host and user and pwd and recipients):
        log.warning("SMTP 配置不全，跳过邮件发送")
        return False

    prefix = email_cfg.get("subject_prefix", "【日报】")
    msg = MIMEMultipart("alternative")
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"{prefix} {date_label}"
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText("请使用支持 HTML 的客户端查看本邮件。", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
                s.login(user, pwd)
                s.sendmail(sender, recipients, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pwd)
                s.sendmail(sender, recipients, msg.as_string())
        log.info("邮件已发送至 %s", recipients)
        return True
    except Exception as e:
        log.warning("邮件发送失败: %s", e)
        return False
