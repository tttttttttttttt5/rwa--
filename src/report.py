"""日报生成：HTML（Jinja2 模板）+ Markdown。"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_TEMPLATE_DIR = _HERE.parent / "templates"


def _abstract(paper, cfg) -> str:
    style = cfg.summary.get("style", "short")
    cap = int(cfg.summary.get("max_abstract_chars", 600))
    text = (paper.abstract or "").strip()
    if not text:
        return ""
    if style == "short":
        return (text[:220] + "…") if len(text) > 220 else text
    if style == "critical" and paper.digest:
        return paper.digest
    return text[:cap] + ("…" if len(text) > cap else "")


def build_context(papers, top_picks, citation_text, cfg, stats):
    today = datetime.date.today().isoformat()
    start = (datetime.date.today() - datetime.timedelta(days=cfg.lookback_days)).isoformat()
    rows = []
    for p in sorted(papers, key=lambda x: x.final_score, reverse=True):
        rows.append({
            "title": p.title,
            "authors": ", ".join(p.authors[:4]) + (" 等" if len(p.authors) > 4 else ""),
            "source": p.source,
            "score": p.final_score,
            "rule": p.rule_score,
            "ai": p.ai_score,
            "journal": p.journal,
            "url": p.url,
            "keywords": p.matched_keywords,
            "watched": bool(p.watched_authors),
            "abstract": _abstract(p, cfg),
            "digest": p.digest,
        })
    return {
        "date": today,
        "window": f"{start} ~ {today}",
        "stats": stats,
        "rows": rows,
        "top_picks": top_picks,
        "citation_text": citation_text,
        "threshold": cfg.scoring.get("threshold"),
        "keywords": cfg.keywords,
    }


def render_html(ctx) -> str:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    tpl = env.get_template("report.html.j2")
    return tpl.render(**ctx)


def render_markdown(ctx) -> str:
    lines = [
        f"# {ctx['date']} RWA 学术文献日报",
        f"统计窗口：{ctx['window']} | 评分阈值：{ctx['threshold']}",
        "",
        f"## 概览\n",
        f"- 共抓取 {ctx['stats'].get('fetched',0)} 篇，入选 {ctx['stats'].get('selected',0)} 篇",
        f"- 来源分布：{ctx['stats'].get('by_source',{})}",
        "",
    ]
    if ctx["top_picks"]:
        lines.append("## ★ 今日最值得精读")
        for pick in ctx["top_picks"]:
            p = pick["paper"]
            lines.append(f"- **{p.title}**（{p.final_score:.0f}分）— {pick['reason']}")
        lines.append("")
    lines.append("## 入选论文列表")
    for r in ctx["rows"]:
        tag = " [★作者关注]" if r["watched"] else ""
        lines.append(f"- [{r['title']}]({r['url']}) — {r['authors']} | {r['source']} | {r['score']:.0f}分{tag}")
        if r["digest"]:
            lines.append(f"  - {r['digest']}")
    lines.append("")
    lines.append("## 论文关联图说明")
    lines.append(ctx["citation_text"])
    lines.append("")
    lines.append(f"## 关键词列表\n{', '.join(ctx['keywords'])}")
    return "\n".join(lines)


def save(html, markdown, cfg) -> tuple:
    out_dir = Path(cfg.report.get("save_dir", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    html_path = out_dir / f"report-{date}.html"
    md_path = out_dir / f"report-{date}.md"
    html_path.write_text(html, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    log.info("报告已保存：%s, %s", html_path, md_path)
    return str(html_path), str(md_path)
