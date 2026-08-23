"""Google Scholar Alerts 抓取器：从 IMAP 邮箱解析 Scholar 警报邮件。

需要在 Google Scholar 中设置 Alerts 并把接收邮箱配置为 IMAP 可登录
（建议为该邮箱单独创建“应用专用密码”）。
"""
from __future__ import annotations

import datetime
import email
import email.utils
import imaplib
import logging
import os
import re

from .base import BaseFetcher, Paper

log = logging.getLogger(__name__)


class ScholarFetcher(BaseFetcher):
    name = "scholar"

    def fetch(self) -> list[Paper]:
        try:
            import imaplib  # noqa
        except Exception:
            return []

        host = self.cfg.get("imap_host", "imap.gmail.com")
        port = int(self.cfg.get("imap_port", 993))
        user = os.getenv("SCHOLAR_IMAP_USER")
        pwd = os.getenv("SCHOLAR_IMAP_PASS")
        if not user or not pwd:
            log.warning("未配置 SCHOLAR_IMAP_USER/PASS，跳过 Scholar 数据源")
            return []

        mailbox = self.cfg.get("mailbox", "INBOX")
        sender = self.cfg.get("sender_contains", "scholar.google")
        lookback = int(self.cfg.get("lookback_days", 7))
        since = (datetime.date.today() - datetime.timedelta(days=lookback)).strftime("%d-%b-%Y")

        out: list[Paper] = []
        try:
            mail = imaplib.IMAP4_SSL(host, port)
            mail.login(user, pwd)
            mail.select(mailbox, readonly=True)
            typ, data = mail.search(None, f'(SINCE {since} FROM "{sender}")')
            if typ != "OK":
                return []
            for num in (b.split()[-1] if isinstance(b, bytes) else b for b in data):
                if isinstance(num, bytes):
                    num = num.decode()
                _, msg_data = mail.fetch(num, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
                out += self._parse_message(msg)
            mail.logout()
        except Exception as e:
            log.warning("Scholar IMAP 解析失败: %s", e)
        log.info("Scholar 抓取到 %d 篇", len(out))
        return out

    def _parse_message(self, msg) -> list[Paper]:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", "ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", "ignore")
        body = re.sub(r"\s+", " ", body)

        pub = email.utils.parsedate_to_datetime(msg.get("Date", "")).date().isoformat() \
            if msg.get("Date") else ""
        out = []
        # Scholar alert 内每条形如：标题 \n 链接 \n 摘要
        for m in re.finditer(
            r"(https?://scholar\.google[a-z./]*\?[^ )]+|https?://[^\s)]+scholar[^\s)]+)",
            body,
        ):
            url = m.group(1)
            start = m.start()
            title = (body[max(0, start - 160):start].strip().split(". ")[-1]).strip(" -")
            out.append(Paper(
                title=title or "(Google Scholar result)",
                authors=[],
                abstract="",
                url=url,
                source="scholar",
                published=pub,
                journal="Google Scholar Alert",
                raw={"subject": msg.get("Subject", "")},
            ))
        return out
