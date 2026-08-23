"""Claude / Anthropic 客户端封装：评分、中文导读、Top-picks 推荐。"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)


class LLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False)) and bool(os.getenv("ANTHROPIC_API_KEY"))
        self.client = None
        if self.enabled:
            try:
                import anthropic
                self.client = anthropic.Anthropic()  # 自动读取 ANTHROPIC_API_KEY
            except Exception as e:
                log.warning("Anthropic 客户端初始化失败，降级为纯规则评分: %s", e)
                self.enabled = False

    # ---------- 单篇相关性评分 ----------
    def score_paper(self, paper, keywords: list[str], journal_tier: int) -> float | None:
        if not self.client:
            return None
        prompt = (
            "你是专注 RWA/DeFi 研究的金融科技学术评审。请根据以下信息，给该论文对"
            "“RWA学术日报”读者的相关性与价值打分 0-100（整数）。\n"
            "考量维度：与关键词的相关性、对 RWA 定价/DeFi 机制的实质贡献、方法学新颖度。\n\n"
            f"关键词列表: {', '.join(keywords)}\n"
            f"命中的关键词: {', '.join(paper.matched_keywords) or '(无)'}\n"
            f"期刊/来源档位: {journal_tier} (1=顶刊, 2=工作论文, 3=其它)\n"
            f"特殊关注作者命中: {', '.join(paper.watched_authors) or '(无)'}\n"
            f"标题: {paper.title}\n"
            f"摘要: {paper.abstract[:1500]}\n\n"
            "只回复一个 0-100 的整数。"
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=10,
                temperature=float(self.cfg.get("temperature", 0.0)),
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text
            m = re.search(r"\d+", txt)
            if not m:
                return None
            return max(0.0, min(100.0, float(m.group())))
        except Exception as e:
            log.warning("AI 评分失败 [%s]: %s", paper.title[:40], e)
            return None

    # ---------- 一句话中文导读 ----------
    def generate_digest(self, paper, style: str = "detailed") -> str:
        if not self.client or not paper.abstract:
            return ""
        lens = {"short": 30, "detailed": 60, "critical": 90}.get(style, 60)
        prompt = (
            "请用中文为这篇论文写一句话导读，突出它对 RWA/DeFi 研究的启示。"
            f"不超过 {lens} 个汉字，不要加引号或多余格式。\n"
            f"标题: {paper.title}\n摘要: {paper.abstract[:1200]}"
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=160,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip().strip('"“”')
        except Exception:
            return ""

    # ---------- 推荐 Top-picks ----------
    def pick_top_picks(self, papers, n: int) -> list[dict]:
        """让模型从高评分论文中挑 n 篇最值得精读，返回 [{title, reason}]。"""
        if not self.client or not papers:
            return []
        pool = sorted(papers, key=lambda p: p.final_score, reverse=True)[:12]
        items = "\n".join(
            f"{i+1}. [{p.final_score:.0f}分] {p.title} | {', '.join(p.matched_keywords[:3])} | "
            f"{p.abstract[:200]}" for i, p in enumerate(pool)
        )
        prompt = (
            "你正在为 RWA/DeFi 研究者编辑日报。从下列论文中挑出"
            f"最值得精读的 {n} 篇，每篇给出一句中文推荐理由（<=40 字）。"
            "严格按 JSON 数组返回，元素形如 {\"index\": 1, \"reason\": \"...\"}，"
            "index 对应下面的编号。不要输出其它内容。\n\n" + items
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=400,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text.strip()
            m = re.search(r"\[.*\]", txt, re.S)
            arr = json.loads(m.group(0)) if m else []
            out = []
            for it in arr[:n]:
                idx = int(it.get("index", 0)) - 1
                if 0 <= idx < len(pool):
                    out.append({"paper": pool[idx], "reason": it.get("reason", "")})
            return out
        except Exception as e:
            log.warning("AI top-picks 失败: %s", e)
            return []
