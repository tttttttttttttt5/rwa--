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

    # ---------- 单篇结构化总结（内容 / 方法 / 可借鉴） ----------
    def generate_structured_summary(self, paper) -> dict:
        """对单篇论文生成结构化中文总结。

        返回 {"content": str, "method": str, "takeaway": str}，
        每段 1-2 句，takeaway 站在 RWA/DeFi 研究者视角提炼可借鉴之处。
        任一字段缺失返回空串。失败时返回空 dict。
        """
        if not self.client or not paper.abstract:
            return {}
        prompt = (
            "你是 RWA/DeFi/区块链金融领域的研究助手。请基于下列论文信息，"
            "用中文生成结构化总结，包含三部分：\n"
            "1) content：研究在解决什么问题、核心结论（1-2 句，<=80 字）\n"
            "2) method：采用的方法/数据/模型（1-2 句，<=80 字）\n"
            "3) takeaway：对 RWA 定价、DeFi 机制设计或相关研究的方法论或思路启示，"
            "指出可直接借鉴的点（1-2 句，<=80 字）\n\n"
            "严格只返回 JSON，形如 "
            '{"content":"...","method":"...","takeaway":"..."}，'
            "不要加任何额外文字、不要 Markdown 代码块。\n\n"
            f"标题: {paper.title}\n"
            f"摘要: {paper.abstract[:1500]}\n"
            f"命中的关键词: {', '.join(paper.matched_keywords[:5]) or '(无)'}"
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=400,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text.strip()
            # 兼容模型偶尔包 ```json ... ```
            m = re.search(r"\{.*\}", txt, re.S)
            if not m:
                return {}
            obj = json.loads(m.group(0))
            return {
                "content": str(obj.get("content", "")).strip(),
                "method": str(obj.get("method", "")).strip(),
                "takeaway": str(obj.get("takeaway", "")).strip(),
            }
        except Exception as e:
            log.warning("AI 结构化总结失败 [%s]: %s", paper.title[:40], e)
            return {}

    # ---------- 整体大总结 + 可借鉴要点 ----------
    def generate_synthesis(self, papers, max_papers: int = 20) -> dict:
        """对当日入选论文做整体综述。

        返回 {"overview": str, "takeaways": [str, ...]}。
        overview：把当日论文串成一段中文综述（<=200 字），点出共同主题与差异。
        takeaways：3-5 条可借鉴要点，每条一句，聚焦方法/数据/思路可迁移之处。
        失败时返回空 dict。
        """
        if not self.client or not papers:
            return {}
        pool = sorted(papers, key=lambda p: p.final_score, reverse=True)[:max_papers]
        items = "\n".join(
            f"{i+1}. [{p.final_score:.0f}分] {p.title} | 关键词: {', '.join(p.matched_keywords[:3]) or '(无)'}"
            f"\n   摘要: {p.abstract[:280]}"
            for i, p in enumerate(pool)
        )
        prompt = (
            "你是 RWA/DeFi 研究综述编辑。下面是今日入选的若干论文。请输出两部分：\n"
            "1) overview：用一段中文综述当日论文（<=200 字），点出共同主题、"
            "方法差异、与 RWA/DeFi 的关联，避免简单罗列。\n"
            "2) takeaways：3-5 条对 RWA/DeFi 研究可借鉴的要点，每条一句（<=40 字），"
            "聚焦方法、数据、模型或思路的可迁移之处，不要重复论文标题。\n\n"
            "严格只返回 JSON，形如 "
            '{"overview":"...","takeaways":["...","..."]}，'
            "不要加任何额外文字、不要 Markdown 代码块。\n\n" + items
        )
        try:
            resp = self.client.messages.create(
                model=self.cfg.get("model", "claude-3-5-sonnet-20241022"),
                max_tokens=700,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            txt = resp.content[0].text.strip()
            m = re.search(r"\{.*\}", txt, re.S)
            if not m:
                return {}
            obj = json.loads(m.group(0))
            overview = str(obj.get("overview", "")).strip()
            raw_takes = obj.get("takeaways", []) or []
            takeaways = [str(t).strip() for t in raw_takes if str(t).strip()][:5]
            return {"overview": overview, "takeaways": takeaways}
        except Exception as e:
            log.warning("AI 整体大总结失败: %s", e)
            return {}

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
