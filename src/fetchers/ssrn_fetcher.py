"""SSRN 抓取器：尽力而为的关键词搜索解析（HTML 结构易变，失败时优雅降级）。"""
from __future__ import annotations

import datetime
import logging
import re
import urllib.parse

from .base import BaseFetcher, Paper

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


class SsrnFetcher(BaseFetcher):
    name = "ssrn"

    def fetch(self) -> list[Paper]:
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            log.warning("未安装 requests/beautifulsoup4，跳过 SSRN 数据源")
            return []

        lookback = int(self.cfg.get("lookback_days", 7))
        cutoff = datetime.datetime.utcnow().date() - datetime.timedelta(days=lookback)
        max_results = int(self.cfg.get("max_results", 60))
        queries = self.cfg.get("queries", [])
        seen: set[str] = set()
        out: list[Paper] = []

        for q in queries:
            url = (
                "https://papers.ssrn.com/sol2/results.cfm?"
                f"txtKey_Wrd={urllib.parse.quote(q)}&npage=1"
                "&SortOrder=ab_appl_date&Facelift=1"
            )
            try:
                html = requests.get(url, headers={"User-Agent": UA}, timeout=30).text
            except Exception as e:
                log.warning("SSRN 搜索失败 [%s]: %s", q, e)
                continue
            for card in self._parse_cards(html):
                link = card.get("url", "")
                if not link or link in seen or len(out) >= max_results:
                    continue
                seen.add(link)
                pub = card.get("date") or ""
                try:
                    pub_d = datetime.datetime.strptime(pub, "%m/%d/%Y").date()
                    if pub_d < cutoff:
                        continue
                except Exception:
                    pub_d = None
                out.append(Paper(
                    title=card.get("title", "").strip(),
                    authors=[a.strip() for a in card.get("authors", "").split(";") if a.strip()],
                    abstract=card.get("abstract", "").strip(),
                    url=link,
                    source="ssrn",
                    published=pub_d.isoformat() if pub_d else "",
                    journal="SSRN Working Paper",
                    raw={"query": q},
                ))
        log.info("SSRN 抓取到 %d 篇", len(out))
        return out

    def _parse_cards(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cards: list[dict] = []
        for a in soup.select("a.title, a[onclick]"):
            href = a.get("href", "")
            if "papers.cfm" not in href and "abstract" not in href:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            link = urllib.parse.urljoin("https://papers.ssrn.com/", href)
            row = a.find_parent(["li", "div", "tr"])
            txt = row.get_text(" ", strip=True) if row else ""
            date_m = re.search(r"(\d{2}/\d{2}/\d{4})", txt)
            cards.append({
                "title": title,
                "url": link,
                "abstract": "",
                "authors": "",
                "date": date_m.group(1) if date_m else "",
            })
        return cards
