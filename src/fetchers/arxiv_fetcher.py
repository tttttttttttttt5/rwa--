"""arXiv 抓取器：按 q-fin 等分类拉取最近 N 天论文。"""
from __future__ import annotations

import datetime
import logging

from .base import BaseFetcher, Paper

log = logging.getLogger(__name__)


class ArxivFetcher(BaseFetcher):
    name = "arxiv"

    def fetch(self) -> list[Paper]:
        try:
            import arxiv
        except ImportError:
            log.warning("未安装 arxiv 库，跳过 arXiv 数据源")
            return []

        cats = self.cfg.get("categories", [])
        lookback = int(self.cfg.get("lookback_days", 7))
        max_results = int(self.cfg.get("max_results", 300))
        if not cats:
            return []

        query = " OR ".join(f"cat:{c}" for c in cats)
        client = arxiv.Client(num_retries=3, page_size=100)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback)
        out: list[Paper] = []
        try:
            for r in client.results(search):
                pub = r.published
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=datetime.timezone.utc)
                if pub < cutoff:
                    break  # 结果按提交时间倒序，遇到旧的就停
                entry_id = getattr(r, "entry_id", "") or ""
                arxid = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else r.get_short_id()
                # 去掉版本号 vN，链接用稳定的 abs 页（https）
                if arxid and arxid[-2] == "v" and arxid[-1].isdigit():
                    arxid_base = arxid[:-2]
                else:
                    arxid_base = arxid
                stable_url = f"https://arxiv.org/abs/{arxid_base}" if arxid_base else (
                    entry_id.replace("http://", "https://") or getattr(r, "pdf_url", "")
                )
                out.append(Paper(
                    title=(r.title or "").strip().replace("\n", " "),
                    authors=[a.name for a in (r.authors or [])],
                    abstract=(r.summary or "").strip(),
                    url=stable_url,
                    source="arxiv",
                    published=pub.date().isoformat(),
                    journal=f"arXiv {r.primary_category or ''}".strip(),
                    arxiv_id=arxid,
                    doi=getattr(r, "doi", None),
                    raw={"categories": r.categories, "primary": r.primary_category},
                ))
        except Exception as e:
            log.warning("arXiv 抓取出错: %s", e)
        log.info("arXiv 抓取到 %d 篇", len(out))
        return out
