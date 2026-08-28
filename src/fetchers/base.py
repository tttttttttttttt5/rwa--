"""核心数据模型与 fetcher 基类。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Paper:
    title: str
    authors: list[str]
    abstract: str
    url: str
    source: str                     # arxiv | nber | ssrn | scholar
    published: str = ""             # ISO yyyy-mm-dd
    journal: str = ""               # venue 名称或来源标签
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    matched_keywords: list[str] = field(default_factory=list)
    watched_authors: list[str] = field(default_factory=list)
    rule_score: float = 0.0
    ai_score: Optional[float] = None
    final_score: float = 0.0
    digest: str = ""                # AI 生成的一句话中文导读（可选）
    summary_content: str = ""       # AI 结构化总结：研究内容
    summary_method: str = ""        # AI 结构化总结：方法
    summary_takeaway: str = ""      # AI 结构化总结：可借鉴之处
    cites: list[str] = field(default_factory=list)       # 本集合内被引用的 key
    cited_by: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """去重 / 引用图用的稳定标识。"""
        return self.arxiv_id or self.doi or self.url

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)


class BaseFetcher:
    """所有数据源的统一接口。"""

    name = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}

    def fetch(self) -> list[Paper]:
        raise NotImplementedError
