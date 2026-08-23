"""RWA 学术文献日报 —— 主入口。

流程：加载配置 -> 抓取各数据源 -> 去重 -> 匹配+规则评分 ->
（可选）AI 评分 -> 阈值过滤 -> 引用图 -> 报告生成 -> 邮件推送。
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
from collections import Counter

from . import citation_graph, email_sender, report, scoring
from .config_loader import load_config
from .llm import LLM
from .fetchers.arxiv_fetcher import ArxivFetcher
from .fetchers.nber_fetcher import NberFetcher
from .fetchers.scholar_fetcher import ScholarFetcher
from .fetchers.ssrn_fetcher import SsrnFetcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("rwa-weekly")


def fetch_all(cfg) -> list:
    papers = []
    fetchers = []
    if cfg.source_enabled("arxiv"):
        fetchers.append(ArxivFetcher(cfg.source_cfg("arxiv")))
    if cfg.source_enabled("nber"):
        fetchers.append(NberFetcher(cfg.source_cfg("nber")))
    if cfg.source_enabled("ssrn"):
        fetchers.append(SsrnFetcher(cfg.source_cfg("ssrn")))
    if cfg.source_enabled("scholar"):
        fetchers.append(ScholarFetcher(cfg.source_cfg("scholar")))

    for f in fetchers:
        try:
            papers.extend(f.fetch())
        except Exception as e:
            log.warning("数据源 %s 抓取异常: %s", f.name, e)
    return papers


def dedupe(papers) -> list:
    seen, out = set(), []
    for p in papers:
        k = p.key
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def main():
    cfg = load_config()
    log.info("配置加载完成 | 关键词 %d 个 | 阈值 %s | AI=%s",
             len(cfg.keywords), cfg.scoring.get("threshold"), cfg.ai.get("enabled"))

    # 1. 抓取 + 去重
    papers = dedupe(fetch_all(cfg))
    log.info("去重后共 %d 篇候选", len(papers))

    # 2. 规则评分（关键词/作者/期刊/时效）
    for p in papers:
        scoring.enrich(p, cfg)

    # 3. 候选池：至少命中一个关键词或是关注作者，过滤无关噪音
    candidates = [p for p in papers if p.matched_keywords or p.watched_authors]
    log.info("候选池 %d 篇（命中关键词或关注作者）", len(candidates))

    # 4. AI 评分（控制成本：只送规则分前 N 篇）
    llm = LLM(cfg.ai)
    ai_weight = float(cfg.ai.get("weight", 0.0))
    max_ai = int(cfg.ai.get("max_papers_to_score", 60))
    pool = sorted(candidates, key=lambda x: x.rule_score, reverse=True)[:max_ai]
    for p in pool:
        tier = scoring.journal_tier(p, cfg.journal_priority)
        p.ai_score = llm.score_paper(p, cfg.keywords, tier)
        scoring.blend_final(p, ai_weight)
    # 未送 AI 的候选用纯规则分
    for p in candidates:
        if p not in pool:
            scoring.blend_final(p, 0.0)

    # 5. 阈值过滤（关注作者 bypass 但仍收入）
    threshold = float(cfg.scoring.get("threshold", 0))
    selected = []
    for p in candidates:
        if p.watched_authors or p.final_score >= threshold:
            selected.append(p)
    selected.sort(key=lambda x: x.final_score, reverse=True)
    log.info("入选 %d 篇（阈值 %.0f）", len(selected), threshold)

    # 6. 中文导读（仅入选论文，控制成本）
    if cfg.summary.get("enable_ai_digest") and llm.enabled:
        style = cfg.summary.get("style", "detailed")
        for p in selected[:20]:
            try:
                p.digest = llm.generate_digest(p, style)
            except Exception:
                pass

    # 7. 引用关系图
    citation_text = "今日入选论文之间未检测到直接引用关系。"
    try:
        citation_graph.build(selected, cfg.report.get("include_citation_graph", True))
        citation_text = citation_graph.describe(selected)
    except Exception as e:
        log.warning("引用图构建失败: %s", e)

    # 8. Top-picks 推荐
    top_picks = llm.pick_top_picks(selected, int(cfg.report.get("top_picks", 2)))
    if not top_picks and selected:
        top_picks = [{"paper": selected[0], "reason": "今日规则评分最高"}][:int(cfg.report.get("top_picks", 2))]

    # 9. 生成报告
    stats = {
        "fetched": len(papers),
        "selected": len(selected),
        "by_source": dict(Counter(p.source for p in selected)),
        "candidates": len(candidates),
    }
    ctx = report.build_context(selected, top_picks, citation_text, cfg, stats)
    html = report.render_html(ctx)
    md = report.render_markdown(ctx)
    html_path, md_path = report.save(html, md, cfg)

    # 10. 邮件推送
    email_sender.send(html, cfg, datetime.date.today().isoformat())

    log.info("完成。报告：%s", md_path)
    print(f"\n日报已生成：\n  HTML: {html_path}\n  MD  : {md_path}\n  入选 {len(selected)} 篇\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
