"""SMTP 邮件推送。

支持通过 HTTP 代理（env: HTTP_PROXY / HTTPS_PROXY 或显式 SMTP_PROXY_URL）
走 CONNECT 隧道连接 SMTP 服务器。用于需要通过 HTTP 代理出网的沙盒环境。
普通直连环境（如 GitHub Actions）保持原行为。
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from urllib.parse import urlparse

log = logging.getLogger(__name__)


def _resolve_proxy():
    for k in ("SMTP_PROXY_URL", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.getenv(k)
        if v:
            return v
    return None


def _build_proxied_socket(host: str, port: int, proxy_url: str, timeout: int,
                          use_ssl: bool, context):
    """通过 HTTP 代理 CONNECT 隧道建立 socket。返回 (连接好的已 SSL 或普通 sock)。

    失败时抛异常给调用方回退或记录。
    """
    import socket as _socket

    parsed = urlparse(proxy_url)
    phost = parsed.hostname
    pport = parsed.port or (80 if parsed.scheme == "http" else 443)
    if not phost or not pport:
        raise ValueError(f"invalid proxy url: {proxy_url}")

    raw_sock = _socket.create_connection((phost, pport), timeout=timeout)
    # 发 CONNECT 请求
    req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if parsed.username or parsed.password:
        from base64 import b64encode
        auth = f"{parsed.username or ''}:{parsed.password or ''}".encode()
        req += f"Proxy-Authorization: Basic {b64encode(auth).decode()}\r\n"
    req += "\r\n"
    raw_sock.sendall(req.encode())
    # 读响应头直到 \r\n\r\n
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = raw_sock.recv(4096)
        if not chunk:
            raise ConnectionError("proxy closed before CONNECT reply")
        head += chunk
        if len(head) > 4096:
            raise ConnectionError("proxy CONNECT reply too long")
    first_line = head.split(b"\r\n", 1)[0].decode("utf-8", "replace")
    parts = first_line.split(" ", 2)
    if len(parts) < 2 or parts[1] != "200":
        raise ConnectionError(f"proxy CONNECT failed: {first_line!r}")

    if use_ssl:
        ctx = context or ssl.create_default_context()
        return ctx.wrap_socket(raw_sock, server_hostname=host)
    return raw_sock


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

    proxy_url = _resolve_proxy()
    ctx = ssl.create_default_context()
    try:
        if proxy_url and os.getenv("SMTP_USE_PROXY", "1") != "0":
            # 通过 HTTP 代理 CONNECT 隧道；完全绕过 smtplib 内部 connect
            log.info("通过 HTTP 代理发送邮件 %s", proxy_url.split("@")[-1])
            # 先建立到代理的原始 socket 并 CONNECT，拿到目标端口上的裸或 TLS socket
            tunnel_sock = _build_proxied_socket(host, port, proxy_url, timeout=60,
                                                 use_ssl=use_ssl, context=ctx)
            # 手工组装一个未 connect 的 SMTP 实例，只覆盖 sock/file 等必要属性
            if use_ssl:
                s = smtplib.SMTP_SSL.__new__(smtplib.SMTP_SSL)
            else:
                s = smtplib.SMTP.__new__(smtplib.SMTP)
            # 手动初始化必要字段（完全绕过 __init__ 避免自动 connect）
            s.host = host
            s.port = port
            s.timeout = 60
            s.esmtp_features = {}
            s.does_esmtp = 0
            s.helo_resp = None
            s.ehlo_resp = None
            s.command_encoding = "ascii"
            s.source_address = None
            s.local_hostname = None
            s.sock = tunnel_sock
            s.file = tunnel_sock.makefile("rb")
            if use_ssl:
                s._host = host
                s.context = ctx
                s.keyfile = None
                s.certfile = None
            try:
                # 读初始 220 greeting
                s.getreply()
                s.login(user, pwd)
                s.sendmail(sender, recipients, msg.as_string())
                try: s.quit()
                except Exception: pass
            finally:
                try: tunnel_sock.close()
                except Exception: pass
        else:
            if use_ssl:
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
