"""构建集合内论文之间的引用关系图（基于 Semantic Scholar 免费 API）。

只对有 arXiv id 的论文查询，找出在本次入选集合内部互相引用的边，
用于日报“关联图说明”。
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)

S2_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxid}"
FIELDS = "references.externalIds,citations.externalIds"


def build(papers: list, enabled: bool = True) -> list[tuple]:
    """返回引用边列表 [(citing_key, cited_key)]，并回填 paper.cites / cited_by。"""
    if not enabled or not papers:
        return []

    try:
        import requests
    except ImportError:
        log.warning("未安装 requests，跳过引用图构建")
        return []

    by_arxid = {p.arxiv_id: p for p in papers if p.arxiv_id}
    if not by_arxid:
        return []

    edges: list[tuple] = []
    for arxid, p in by_arxid.items():
        try:
            r = requests.get(
                S2_URL.format(arxid=arxid),
                params={"fields": "references.externalIds,citations.externalIds"},
                timeout=20,
                headers={"User-Agent": "rwa-weekly/1.0"},
            )
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception as e:
            log.debug("S2 查询失败 %s: %s", arxid, e)
            continue

        ref_ids = []
        for ref in data.get("references", []) or []:
            ext = ref.get("externalIds") or {}
            if ext.get("ArXiv"):
                ref_ids.append(ext["ArXiv"])
        cit_ids = []
        for cit in data.get("citations", []) or []:
            ext = cit.get("externalIds") or {}
            if ext.get("ArXiv"):
                cit_ids.append(ext["ArXiv"])

        p.cites = [k for k in ref_ids if k in by_arxid and k != arxid]
        p.cited_by = [k for k in cit_ids if k in by_arxid and k != arxid]
        for k in p.cites:
            edges.append((p.arxiv_id, k))
        time.sleep(0.35)  # 友好限速

    log.info("引用图：构建 %d 条内部引用边", len(edges))
    return edges


def describe(papers: list) -> str:
    """把引用关系渲染成自然语言说明，用于邮件正文。"""
    links = []
    for p in papers:
        for k in p.cites:
            target = next((q for q in papers if q.arxiv_id == k), None)
            if target:
                links.append(f"《{p.title[:30]}…》引用了 《{target.title[:30]}…》")
    if not links:
        return "今日入选论文之间未检测到直接引用关系。"
    head = links[:8]
    more = f"\n（共 {len(links)} 条引用关系，已展示前 8 条）" if len(links) > 8 else ""
    return "\n".join(head) + more
