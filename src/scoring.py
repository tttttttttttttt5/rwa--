"""规则评分 + 关键词/作者匹配 + 与 AI 分数的融合。"""
from __future__ import annotations

import datetime
import re

# 词边界匹配：避免 "DeFi" 匹配到 "deficit"、"AMM" 匹配到 "amman" 等子串误判
_WORD_RE_CACHE: dict = {}


def _in_text(text_clean: str, keyword: str) -> bool:
    """在干净小写文本里做词边界子串匹配。keyword 可为短语（含空格）。"""
    if not keyword:
        return False
    k = keyword.lower()
    rx = _WORD_RE_CACHE.get(k)
    if rx is None:
        # 用 \b 包裹关键词，短语内部空格用 \s+ 兼容
        pattern = r"(?<![a-z0-9])" + re.escape(k).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        rx = re.compile(pattern)
        _WORD_RE_CACHE[k] = rx
    return bool(rx.search(text_clean))


def match_keywords(paper, keywords: list[str]) -> list[str]:
    text = f"{paper.title} {paper.abstract}".lower()
    return [k for k in keywords if _in_text(text, k)]


def match_core_keywords(paper, cfg) -> bool:
    """是否命中任一核心金融关键词（RWA/DeFi/稳定币等）。
    用于候选池门禁：仅命中 AI 泛词/辅助词的纯技术论文不入选。"""
    tiers = getattr(cfg, "keyword_tiers", None) or cfg.scoring.get("keyword_tiers", {})
    core_list = [k for k in tiers.get("tier_core", [])]
    if not core_list:
        return bool(paper.matched_keywords)
    text = f"{paper.title} {paper.abstract}".lower()
    return any(_in_text(text, k) for k in core_list)


def match_authors(paper, watched: list[str]) -> list[str]:
    lower_authors = [a.lower() for a in paper.authors]
    return [w for w in watched if any(w.lower() in la for la in lower_authors)]


def journal_tier(paper, jp_cfg: dict) -> int:
    name = (paper.journal or "").lower()
    for j in jp_cfg.get("tier_1_journals", []):
        if j.lower() in name:
            return 1
    for j in jp_cfg.get("tier_2_journals", []):
        if j.lower() in name:
            return 2
    return jp_cfg.get("source_tier", {}).get(paper.source, jp_cfg.get("default_tier", 3))


def _recency_points(paper, rec_cfg: dict) -> float:
    if not paper.published:
        return rec_cfg.get("else", 0)
    try:
        d = datetime.date.fromisoformat(paper.published)
    except Exception:
        return rec_cfg.get("else", 0)
    age = (datetime.date.today() - d).days
    if age <= 7:
        return rec_cfg["within_days_7"]
    if age <= 14:
        return rec_cfg["within_days_14"]
    return rec_cfg["else"]


def enrich(paper, cfg) -> int:
    """填充匹配信息与规则分，返回 journal_tier。"""
    paper.matched_keywords = match_keywords(paper, cfg.keywords)
    paper.watched_authors = match_authors(paper, cfg.watched_authors)
    tier = journal_tier(paper, cfg.journal_priority)
    paper.rule_score = _rule_score(paper, tier, cfg)
    return tier


def _weighted_keyword_hits(paper, cfg) -> float:
    """关键词分层加权命中数：核心词 1.0/个，辅助词 0.4/个。"""
    tiers = getattr(cfg, "keyword_tiers", None) or cfg.scoring.get("keyword_tiers", {})
    if not tiers:
        # 无分层配置 → 回退到原始计数
        return float(len(paper.matched_keywords))

    core_list = [k.lower() for k in tiers.get("tier_core", [])]
    aux_list = [k.lower() for k in tiers.get("tier_aux", [])]
    text = f"{paper.title} {paper.abstract}".lower()

    core_hits = sum(1 for k in core_list if k and k in text)
    aux_hits = sum(1 for k in aux_list if k and k in text)
    return core_hits * 1.0 + aux_hits * 0.4


def _rule_score(paper, tier: int, cfg) -> float:
    s = cfg.scoring
    w = s.get("weights", {"keyword": 40, "journal": 30, "author": 20, "recency": 10})

    # 关键词：分层加权命中 → 归一化
    kw_weighted = _weighted_keyword_hits(paper, cfg)
    full_at = max(float(s.get("keyword_full_at", 3)), 1.0)
    kw_pts = min(kw_weighted / full_at, 1.0) * w["keyword"]

    tier_scores = cfg.journal_priority.get("tier_scores", {1: 30, 2: 20, 3: 10})
    jl_pts = tier_scores.get(tier, tier_scores.get(3, 10))

    au_pts = min(
        len(paper.watched_authors) * s.get("author_bonus_per_hit", 10),
        s.get("author_bonus_cap", 20),
    )

    rc_pts = _recency_points(paper, s.get("recency", {}))

    return round(kw_pts + jl_pts + au_pts + rc_pts, 1)


def blend_final(paper, ai_weight: float):
    """融合规则分与 AI 分。"""
    if paper.ai_score is None:
        paper.final_score = paper.rule_score
    else:
        aw = max(0.0, min(1.0, ai_weight))
        paper.final_score = round(paper.rule_score * (1 - aw) + paper.ai_score * aw, 1)
    return paper.final_score
