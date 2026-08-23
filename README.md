# RWA 学术文献日报（AI 驱动版）

每天自动扫描 arXiv / NBER / SSRN / Google Scholar Alerts，按你设定的关键词、期刊优先级、作者关注列表筛选论文，用 Claude 为每篇打分，生成 HTML+Markdown 日报并发送邮件。支持 GitHub Actions 每天自动运行。

## 功能一览

| 调试项 | 在哪改 | 说明 |
| --- | --- | --- |
| 关键词列表 `keywords` | `config/config.yaml` | 每篇匹配的关键词越多，优先级越高 |
| 期刊优先级 `journal_priority` | 同上 | JFE/JF/RFS/FRL=顶档；SSRN/NBER/arXiv=次档；其它=三档 |
| 评分阈值 `scoring.threshold` | 同上 | 低于阈值的论文直接过滤 |
| 摘要风格 `summary.style` | 同上 | `short` / `detailed` / `critical` |
| 特殊关注作者 `watched_authors` | 同上 | 命中即加分且不受阈值限制 |
| AI 权重 `ai.weight` | 同上 | 0=纯规则，0.3=规则与 AI 各占 |
| 数据源开关 `sources.*.enabled` | 同上 | 哪个源不想用就置 false |

> 修改配置文件后，下次运行（GitHub Actions / 本地）自动生效，无需改代码。

## 项目结构

```
rwa-weekly/
├── config/config.yaml          # 主配置（关键词/期刊/阈值/邮箱）
├── src/
│   ├── config_loader.py        # 配置加载与容错
│   ├── fetchers/               # 四个数据源
│   │   ├── base.py             # Paper 数据模型
│   │   ├── arxiv_fetcher.py
│   │   ├── nber_fetcher.py
│   │   ├── ssrn_fetcher.py
│   │   └── scholar_fetcher.py
│   ├── scoring.py              # 规则评分 + 关键词/作者匹配
│   ├── llm.py                  # Claude 评分/导读/Top-picks
│   ├── citation_graph.py      # Semantic Scholar 引用关系图
│   ├── report.py               # HTML/Markdown 报告
│   ├── email_sender.py         # SMTP 邮件
│   └── main.py                 # 主入口
├── templates/report.html.j2    # HTML 模板
├── .github/workflows/weekly-report.yml
├── requirements.txt
└── .env.example
```

## 评分机制

每篇论文最终分数 = 规则分（权重占 `1-ai.weight`）与 AI 分（占 `ai.weight`）的加权融合。

规则分四项合计 0-100：

- **关键词 (40)**：命中 3 个即满分，鼓励多维度匹配。
- **期刊优先级 (30)**：顶档 30 / 次档 20 / 三档 10。
- **作者权威度 (20)**：每命中一个关注作者 +10，上限 20。
- **时效性 (10)**：7 天内 10 分，14 天内 5 分。

AI 分由 Claude 综合摘要、命中关键词、期刊档位、关注作者给出 0-100 的相关性判断。可在配置中关闭 AI（`ai.enabled=false`），此时走纯规则评分。

## 本地运行

```bash
cd rwa-weekly
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 填入密钥
# 按需修改 config/config.yaml
python -m src.main
```

报告输出到 `reports/report-YYYY-MM-DD.{html,md}`。不配 SMTP 时跳过邮件，仅生成文件。

## GitHub Actions 自动运行

1. 把本项目推到 GitHub 仓库。
2. 在仓库 **Settings → Secrets and variables → Actions** 添加：
   - `ANTHROPIC_API_KEY`（若开启 AI）
   - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USE_SSL` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM`
   - （可选）`SCHOLAR_IMAP_USER` / `SCHOLAR_IMAP_PASS`
3. 工作流默认每天北京时间 09:00 运行（cron `0 1 * * *` UTC）。也可在 Actions 页面点 **Run workflow** 手动触发。
4. 运行结束会把 `reports/` 下生成的日报提交回仓库。

## 接入 Google Scholar Alerts（可选）

Scholar 不提供公开 API，本系统通过解析告警邮件实现：

1. 在 [Google Scholar Alerts](https://scholar.google.com) 用一个专用邮箱创建关键词告警。
2. 在 `.env` 填 `SCHOLAR_IMAP_USER` / `SCHOLAR_IMAP_PASS`（应用专用密码）。
3. 在 `config/config.yaml` 设 `sources.scholar.enabled: true`，确认 `imap_host` 正确。

## 数据源说明

- **arXiv**：通过官方 API，按 `q-fin.*` 等分类拉取最近 N 天论文，最稳定。
- **NBER**：解析各研究方向的 RSS，含标题/摘要/链接，作者字段尽力提取。
- **SSRN**：基于关键词搜索页 HTML 解析，**结构易变**，失败时自动降级为空，不影响其它源。
- **Semantic Scholar**：用于引用关系图，免费、按 arXiv id 查询，自动限速。
- **Google Scholar**：见上节。

## 常见调整

- 噪音太多 → 调高 `scoring.threshold`，或精简 `keywords`，或移除某 arXiv 分类。
- 漏掉好论文 → 调低阈值，或增加关键词，或把作者加入 `watched_authors`。
- 想要更全的摘要 → `summary.style: critical` 并保持 `ai.enabled: true`。
- 控制 API 成本 → 调小 `ai.max_papers_to_score`，或直接 `ai.enabled: false`。
