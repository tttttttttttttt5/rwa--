"""加载并校验 config.yaml，提供带默认值的访问。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml


class Config:
    def __init__(self, data: dict):
        self._d = data

    # ---- 通用读取 ----
    def get(self, *path, default=None):
        node = self._d
        for p in path:
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        return node

    # ---- 便捷属性 ----
    @property
    def keywords(self) -> list[str]:
        return self.get("keywords", default=[]) or []

    @property
    def watched_authors(self) -> list[str]:
        return self.get("watched_authors", default=[]) or []

    @property
    def journal_priority(self) -> dict:
        return self.get("journal_priority", default={}) or {}

    @property
    def scoring(self) -> dict:
        return self.get("scoring", default={}) or {}

    @property
    def ai(self) -> dict:
        return self.get("ai", default={}) or {}

    @property
    def summary(self) -> dict:
        return self.get("summary", default={}) or {}

    @property
    def report(self) -> dict:
        return self.get("report", default={}) or {}

    @property
    def notifications(self) -> dict:
        return self.get("notifications", default={}) or {}

    @property
    def sources(self) -> dict:
        return self.get("sources", default={}) or {}

    @property
    def lookback_days(self) -> int:
        return int(self.get("lookback_days", default=7) or 7)

    def source_cfg(self, name: str) -> dict:
        return (self.sources.get(name) or {})

    def source_enabled(self, name: str) -> bool:
        return bool((self.sources.get(name) or {}).get("enabled", False))


def load_config(path: str | Path | None = None) -> Config:
    """从文件加载，未找到则用内置最小默认，保证脚本永远能跑。"""
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        env_path = os.getenv("RWA_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        candidates += [
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path(__file__).resolve().parent.parent / "config" / "config.yaml",
        ]

    for c in candidates:
        if c.exists():
            with open(c, "r", encoding="utf-8") as f:
                return Config(yaml.safe_load(f) or {})

    # 兜底默认
    return Config({
        "keywords": ["RWA tokenization", "DeFi", "real world assets"],
        "watched_authors": [],
        "journal_priority": {"source_tier": {"arxiv": 2, "ssrn": 2, "nber": 2, "scholar": 3},
                              "default_tier": 3, "tier_scores": {1: 30, 2: 20, 3: 10}},
        "scoring": {"threshold": 55, "weights": {"keyword": 40, "journal": 30, "author": 20, "recency": 10},
                    "keyword_full_at": 3, "author_bonus_per_hit": 10, "author_bonus_cap": 20,
                    "recency": {"within_days_7": 10, "within_days_14": 5, "else": 0}},
        "ai": {"enabled": False},
        "summary": {"style": "short", "max_abstract_chars": 600, "enable_ai_digest": False},
        "report": {"top_picks": 2, "include_citation_graph": True, "save_dir": "reports"},
        "notifications": {"email": {"enabled": False}},
        "sources": {}, "lookback_days": 7,
    })
