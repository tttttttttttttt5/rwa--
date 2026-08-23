"""NBER 工作论文抓取器：解析 NBER 各方向 RSS。"""
from __future__ import annotations

import datetime
import logging
import re

from .base import BaseFetcher, Paper

log = logging.getLogger(__name__)

_AUTHOR_RE = re.compile(r"\bby\s+([A-Z][A-Za-z.\- ]+(?:\s*[,&]\s*[A-Z][A-Za-z.\- ]+)*)")


def _parse_date(s: str):
    if not s:
        return None
    try:
        import email.utils
        dt = email.utils.parsedate_to_datetime(s)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None


def _clean(s: str) -> str:
    s = s or ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


class NberFetcher(BaseFetcher):
    name = "nber"

    def fetch(self) -> list[Paper]:
        try:
            import feedparser
        except ImportError:
            log.warning("未安装 feedparser，跳过 NBER 数据源")
            return []

        lookback = int(self.cfg.get("lookback_days", 7))
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback)
        feeds = self.cfg.get("feeds", [])
        seen: set[str] = set()
        out: list[Paper] = []

        for url in feeds:
            try:
                d = feedparser.parse(url, request_headers={"User-Agent": "rwa-weekly/1.0"})
            except Exception as e:
                log.warning("NBER feed 解析失败 %s: %s", url, e)
                continue
            for e in d.entries:
                pub = _parse_date(e.get("published", ""))
                if pub and pub < cutoff:
                    continue
                link = e.get("link", "") or ""
                if not link or link in seen:
                    continue
                seen.add(link)
                body = _clean(e.get("summary", "") or e.get("description", ""))
                m = _AUTHOR_RE.search(body)
                authors = [a.strip() for a in re.split(r"[,&]", m.group(1))] if m else []
                title = _clean(e.get("title", ""))
                out.append(Paper(
                    title=title,
                    authors=authors,
                    abstract=body,
                    url=link,
                    source="nber",
                    published=pub.date().isoformat() if pub else "",
                    journal="NBER Working Papers",
                    raw={"feed": url},
                ))
        log.info("NBER 抓取到 %d 篇", len(out))
        return out
