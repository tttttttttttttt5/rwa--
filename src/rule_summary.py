"""纯规则版总结（无需 API）。

根据每篇论文的标题、摘要、命中关键词、关注作者、来源等信息，
用句子切分 + 关键词/方法词命中 + 可借鉴模板映射的方式，离线生成：
  1) 每篇论文：一句话导读 + 三段式总结（研究内容 / 方法 / 可借鉴）
  2) 整体：大总结（overview） + 跨论文可借鉴要点（takeaways）
"""
from __future__ import annotations

import re
from collections import Counter

# ---------- 方法词典：命中则在"方法"段列举 ----------
METHOD_PATTERNS = [
    # 机器学习 / 深度学习
    (r"\b(gradient\s*boost(?:ing)?|xgb|xgboost|lightgbm|gbdt|random\s*forest)\b",
     "集成树模型（梯度提升树/随机森林）"),
    (r"\b(neural\s*network|lstm|gru|transformer|bert|deep\s*learning)\b",
     "神经网络 / 深度学习"),
    (r"\b(graph\s*neural\s*network|gnn|graph\s*attention|gat|gcn)\b",
     "图神经网络 GNN（聚合结构信息刻画网络拓扑）"),
    (r"\b(transformer|self[\s-]?attention)\b", "Transformer / 自注意力"),
    (r"\b(reinforcement\s*learning|(?:deep\s*)?rl)\b", "强化学习策略优化"),
    (r"\b(svm|support\s*vector)\b", "支持向量机"),
    (r"\b(?:tab(?:ular)?[\s-]?)(?:net|dl|deep\s*learning)\b",
     "表格数据专用深度学习（残差表格网络等）"),
    (r"\b(clustering|k-?means|dbscan)\b", "聚类分析"),
    (r"\b(principal\s*component|pca|autoencoder)\b", "降维 / 表征学习"),

    # 因果 / 计量
    (r"\b(causal\s*inference|causality|treatment\s*effect)\b",
     "因果推断（处理效应估计）"),
    (r"\b(difference[\s-]in[\s-]differences?|did)\b", "双重差分 DiD"),
    (r"\b(regression\s*discontinuity|rdd)\b", "断点回归 RDD"),
    (r"\b(instrumental\s*variable|iv[ -]?\d?s?l[sr])\b", "工具变量 IV / 2SLS"),
    (r"\b(probability\s*of\s*treatment|propensity|psm)\b", "倾向得分匹配 PSM"),
    (r"\b(structural\s*(?:model|estimation))\b", "结构模型估计"),

    # 金融工程 / 计量
    (r"\b(back-?test|rolling\s*window|walk[\s-]forward)\b",
     "滚动前向回测（避免未来函数）"),
    (r"\b(garch|volatility\s*model|stochastic\s*volatility)\b",
     "GARCH / 随机波动率模型"),
    (r"\b(arima|var|vector\s*auto\s*regress)\b", "时间序列 (ARIMA/VAR)"),
    (r"\b(no[- ]?arbitrage|arbitrage\s*free|equilibrium\s*model)\b",
     "无套利 / 均衡模型推导"),
    (r"\b(mean[\s-]variance|markowitz|portfolio\s*optimization)\b",
     "均值-方差投资组合优化"),
    (r"\b(value[ -]at[ -]risk|var\b|expected\s*shortfall|es)", "VaR / ES 风险测度"),
    (r"\b(duration|convexity|yield\s*curve)\b", "久期 / 凸性 / 收益率曲线建模"),
    (r"\b(copula|merton\s*model|credit\s*risk|default\s*probability)\b",
     "信用风险 / 违约概率 / Copula"),
    (r"\b(kalman\s*filter|state\s*space)\b", "卡尔曼滤波 / 状态空间模型"),

    # DeFi / AMM / 机制设计
    (r"\b(automated\s*market\s*maker|amm|concentrated\s*liquidity)\b",
     "AMM 自动化做市商（含 v3 集中流动性）"),
    (r"\b(liquidity\s*provider|lp\s+|impermanent\s*loss)\b",
     "LP 收益 / 无常损失分析"),
    (r"\b(oracle|chainlink|price\s*feed)\b", "预言机 / 价格反馈"),
    (r"\b(funding\s*rate|perpetual(?:\s*futures)?)\b",
     "资金费率 / 永续期货定价关系"),
    (r"\b(stablecoin|pegging|peg)\b", "稳定币钉住机制"),
    (r"\b(mechanism\s*design|incentive\s*compat(?:ibility)?)\b",
     "机制设计 / 激励相容分析"),
    (r"\b(blockchain\s*(?:data|on[ -]?chain))\b", "链上实证 / 链下数据联动"),
]

# ---------- 主题词 -> 对应在"可借鉴"中的模板 ----------
TAKEAWAY_TEMPLATES = [
    # 机器学习方法论迁移
    (r"\b(gradient\s*boosting?|lightgbm|xgboost|gbdt)\b",
     "RWA 定价因子可纳入集成树模型刻画因素间的非线性交互"),
    (r"\b(gnn|graph\s*neural\s*network)\b",
     "RWA 生态的跨协议/跨资产传染风险可引入 GNN 聚合拓扑结构"),
    (r"\btabular\b",
     "RWA 抵押品的高基数类别特征（资产类型/评级/司法辖区）适合表格深度网络"),
    (r"\btransformer\b",
     "序列注意力可用于建模 RWA 资产跨时窗依赖的现金流冲击"),

    # 因果 / 计量
    (r"\bcausal\s*inference\b",
     "RWA 定价效果评估宜引入因果框架，剥离选择性偏差与时间混淆"),
    (r"\bdifference[\s-]in[\s-]differences?\b|did\b",
     "RWA 通证化前后的治理溢价可采用 DiD 准实验估计"),
    (r"\binstrumental\s*variable\b|iv[ -]?\d?s?l[sr]",
     "RWA 内生性较强的资产可用工具变量做一致估计"),

    # 评估 / 回测范式
    (r"\bback[- ]?test|rolling\s*window|walk[\s-]forward\b",
     "RWA 策略评估务必采用滚动前向回测，避免未来函数与样本内过拟合"),
    (r"\btransaction\s*cost|market\s*impact|bid[ -]ask\b",
     "RWA 策略评估要覆盖现实交易成本与市场冲击，避免纯统计显著性误导"),

    # 风险 / 信用
    (r"\bcredit\s*risk|default\s*probability|merton\b",
     "RWA 抵押品评估可借鉴 Merton 结构模型与违约概率校准"),
    (r"\b(value[ -]at[ -]risk|expected\s*shortfall|es)\b",
     "RWA 做市商的风险预算建议以 VaR/ES 校准尾部头寸"),

    # 金融工程 / 无套利
    (r"\bno[- ]?arbitrage|funding\s*rate|basis\b",
     "RWA 期货/永续的定价应以无套利资金费率关系为锚"),
    (r"\bduration|convexity|yield\s*curve\b",
     "RWA 固收通证可按久期-凸性框架管理利率敞口"),

    # DeFi / AMM 机制
    (r"\bautomated\s*market\s*maker|amm|concentrated\s*liquidity\b",
     "RWA 通证化资产可设计与现实期限错配挂钩的集中流动性 tick 区间"),
    (r"\boracle\b",
     "RWA 定价预言机应引入多源聚合与容错，避免单一价格源操纵"),
    (r"\bstablecoin\b",
     "RWA 稳定币的储备金审计与钉住维护可借鉴成熟稳定币机制"),
    (r"\bimpermanent\s*loss\b",
     "RWA LP 无常损失需考虑现实资产流动性折价，不能照搬 Crypto AMM"),
    (r"\b(liquidity\s*provider|lp\s+)\b",
     "RWA 流动性激励要对齐 LP 真实持有成本，避免空转收益"),
    (r"\bmechanism\s*design|incentive\s*compat",
     "RWA 生态治理代币经济需保证激励相容，避免道德风险"),
    (r"\bon[ -]?chain\b|blockchain\s*data\b",
     "RWA 验证与定价应尽量引入链上可核验数据，降低信息不对称"),

    # 兜底
    (r".",
     "研究方法可作为 RWA 定价/风险建模的方法学基线或对照实验"),
]


# ---------- 工具 ----------
_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|(?<=\n)")


def _split_sentences(text: str) -> list[str]:
    if not text:
        return []
    s = text.strip().replace("\r", "")
    # 摘要常出现的换行符视同句断
    raw = [x.strip() for x in _SENT_SPLIT.split(s) if x.strip()]
    out = []
    for r in raw:
        # 对超长句（未加标点）按逗号切一下兜底
        if len(r) > 220 and ", " in r:
            out.extend(x.strip() for x in r.split(", ") if x.strip())
        else:
            out.append(r)
    return out


def _match_methods(text: str) -> list[str]:
    hits = []
    seen = set()
    for pat, label in METHOD_PATTERNS:
        if re.search(pat, text, flags=re.I):
            if label not in seen:
                hits.append(label)
                seen.add(label)
    return hits


def _takeaway_for_text(text: str, max_n=2) -> list[str]:
    hits = []
    seen = set()
    for pat, tpl in TAKEAWAY_TEMPLATES:
        if re.search(pat, text, flags=re.I):
            if tpl not in seen:
                hits.append(tpl)
                seen.add(tpl)
                if len(hits) >= max_n:
                    break
    return hits


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


# ---------- 单篇：结构化三段总结 + 导读 ----------
def summarize_paper(paper) -> dict:
    """返回 {'content':..., 'method':..., 'takeaway':..., 'digest':...}。"""
    title = _clean(paper.title)
    abstract = _clean(paper.abstract)
    combined = f"{title}. {abstract}"
    sents = _split_sentences(abstract)

    # 1) 研究内容 = 摘要开头第一句/第二句 + 标题
    content_parts = []
    if title:
        content_parts.append(f"围绕《{title}》展开")
    if sents:
        # 第一句是动机/问题
        content_parts.append(sents[0])
    if len(sents) >= 2:
        # 第二句常是贡献或方法概述，取一部分
        s2 = sents[1]
        content_parts.append(s2 if len(s2) < 200 else s2[:197] + "…")
    content = _clean("。".join(content_parts)) + "。"
    content = content.replace("。。", "。").replace("：。", "：")

    # 2) 方法 = 方法词典命中 + 关键词中"方法类"补充
    method_parts = []
    methods = _match_methods(combined)
    if methods:
        method_parts.append("采用 " + "、".join(methods[:5]))
    # 扫描摘要的后半句寻找数据/样本描述
    data_sents = []
    for s in sents[2:7]:
        low = s.lower()
        if any(k in low for k in ("sample", "dataset", "panel", "backtest",
                                   "on-chain", "transaction", "minute",
                                   "daily", "monthly", "year", "period",
                                   "we use", "using ", "over ", "from ",
                                   "验证", "回测", "样本", "数据")):
            data_sents.append(s)
            if len(data_sents) >= 2:
                break
    data_text = " ".join(data_sents)
    if data_text:
        method_parts.append("基于 " + _clean(data_text)[:220])
    if not method_parts:
        # 兜底：取摘要前两句
        method_parts.append("基于常规实证/建模范式，" + (sents[1][:120] if len(sents) > 1 else sents[0][:120] if sents else "详情见原文"))
    method = "；".join(method_parts) + "。"

    # 3) 可借鉴 = TAKEAWAY_TEMPLATES 命中（排除兜底通配），最多 3 条
    takeaways = _takeaway_for_text(combined, max_n=3)
    # 如果命中兜底项且前面已有实质内容，则删掉兜底
    fallback = "研究方法可作为 RWA 定价/风险建模的方法学基线或对照实验"
    if len(takeaways) > 1 and fallback in takeaways:
        takeaways = [t for t in takeaways if t != fallback]
    if takeaways:
        takeaway = "；".join(takeaways[:3]) + "。"
    else:
        takeaway = "研究结论与方法可为 RWA/DeFi 的定价或机制设计提供对照参考。"

    # 4) 一句话导读
    kw = paper.matched_keywords
    auth = "（关注作者 " + "、".join(paper.watched_authors) + "）" if paper.watched_authors else ""
    prefix = f"命中关键词 {', '.join(kw[:4])}{auth}" if kw else auth.strip("（）")
    hint = ""
    if methods:
        hint = f"，方法含 {methods[0]}"
    digest = f"{prefix}{hint}。" if prefix.strip() else f"研究{title[:30]}。"

    return {
        "content": _clean(content),
        "method": _clean(method),
        "takeaway": _clean(takeaway),
        "digest": _clean(digest),
    }


# ---------- 整体：大总结 + 可借鉴要点 ----------
def synthesize(papers: list) -> dict:
    if not papers:
        return {"overview": "今日无入选论文。", "takeaways": []}

    kw_counter = Counter()
    method_counter = Counter()
    takeaway_bag = []
    sources = Counter()

    for p in papers:
        for k in p.matched_keywords or []:
            kw_counter[k.lower()] += 1
        methods = _match_methods(f"{p.title} {p.abstract}")
        for m in methods:
            method_counter[m] += 1
        takeaway_bag.extend(_takeaway_for_text(f"{p.title} {p.abstract}", max_n=2))
        sources[p.source or "unknown"] += 1

    # overview
    n = len(papers)
    top_kw = [k for k, _ in kw_counter.most_common(5)]
    top_methods = [m for m, _ in method_counter.most_common(4)]
    src_desc = "、".join(f"{s} {c}篇" for s, c in sources.most_common())
    kw_sent = f"热点关键词覆盖 {'、'.join(top_kw)}" if top_kw else "覆盖 RWA/DeFi 多类主题"
    m_sent = f"，主要方法包括 {'、'.join(top_methods)}" if top_methods else ""
    overview = (
        f"今日共入选 {n} 篇论文（{src_desc}），{kw_sent}{m_sent}。"
        f"整体来看，论文集中于 {'/'.join(top_kw[:3]) or '金融科技与 DeFi 方向'}，"
        f"可为 RWA 通证化定价、DeFi 机制设计、资产风险建模提供方法学参考。"
    )

    # takeaways：去重，保持 3-5 条
    seen = set()
    takeaways = []
    for t in takeaway_bag:
        if t in seen:
            continue
        seen.add(t)
        takeaways.append(t)
        if len(takeaways) >= 5:
            break
    if len(takeaways) < 3:
        takeaways.extend([
            "RWA 定价需综合流动性折价、预言机风险与跨协议传染三条主线",
            "DeFi 策略评估务必采用滚动前向回测，避免未来函数",
            "现实资产通证化设计应保证激励相容并预留风险缓冲带",
        ])
    takeaways = takeaways[:5]

    return {"overview": _clean(overview), "takeaways": [_clean(t) for t in takeaways]}
