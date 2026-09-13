"""arXiv 抓取器：拆分金融分类和 AI/ML 分类，分别查询。

策略：
  1) q-fin.* 等金融分类 → 直接拉取（论文总量小，全量收）
  2) cs.AI / cs.LG / stat.ML / cs.CL → 带金融关键词 abs: 搜索
     （这些分类论文量极大，必须加关键词过滤否则 arXiv API 超时）
"""
from __future__ import annotations

import datetime
import logging

from .base import BaseFetcher, Paper

log = logging.getLogger(__name__)

# AI/ML 分类需要搭配金融关键词搜索，避免拉到无关论文
_AI_FINANCE_KEYWORDS = [
    "finance", "trading", "portfolio", "asset", "market",
    "risk", "cryptocurrency", "blockchain", "token", "DeFi",
    "stock", "option", "derivative", "pricing", "liquidity",
]


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

        # 拆分：金融分类 vs AI/ML 分类
        fin_cats = [c for c in cats if c.startswith("q-fin")]
        ai_cats = [c for c in cats if not c.startswith("q-fin")]

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=lookback)
        out: list[Paper] = []
        client = arxiv.Client(num_retries=3, page_size=100)

        # --- 查询 1：金融分类（全量，不加关键词）---
        if fin_cats:
            q1 = " OR ".join(f"cat:{c}" for c in fin_cats)
            out.extend(self._run_query(client, q1, max_results, cutoff))

        # --- 查询 2：AI/ML 分类 + 金融关键词 ---
        if ai_cats:
            cat_part = " OR ".join(f"cat:{c}" for c in ai_cats)
            kw_part = " OR ".join(f'abs:"{k}"' for k in _AI_FINANCE_KEYWORDS)
            q2 = f"({cat_part}) AND ({kw_part})"
            out.extend(self._run_query(client, q2, max_results, cutoff))

        log.info("arXiv 抓取到 %d 篇", len(out))
        return out

    def _run_query(self, client, query: str, max_results: int, cutoff) -> list[Paper]:
        import arxiv
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )
        out: list[Paper] = []
        try:
            for r in client.results(search):
                pub = r.published
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=datetime.timezone.utc)
                if pub < cutoff:
                    break
                entry_id = getattr(r, "entry_id", "") or ""
                arxid = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else r.get_short_id()
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
            log.warning("arXiv 查询出错 [%s...]: %s", query[:80], e)
        return out
