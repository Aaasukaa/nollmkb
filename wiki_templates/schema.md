# Wiki 协议

> LLM agent 写/读 wiki 时**必读**的协议。OpenCode/Claude Code 启动后第一步读这个文件。

## 目录结构
```
wiki/
├── purpose.md              # 为什么有这个 wiki (你已写)
├── schema.md               # 本文件
├── index.md                # LLM 维护的内容目录
├── log.md                  # append-only 操作日志
├── notes/                  # 所有内容页统一放这里
├── queries/                # 值得保留的问答 (可选)
└── .llm-wiki/
    └── cache.json          # 复用 nollmkb hash_db
```

## 页面规范

### Frontmatter (必填)
```yaml
---
title: 某技术路线综述
created: 2026-06-05
last_verified: 2026-06-05
sources:                              # ← 引用 nollmkb chunk ID
  - 文献/某论文.pdf_42
related:                              # ← wikilinks
  - "[[相关方法对比]]"
tags:                                 # ← 3-7 个, 必填
  - "method-survey"
  - "deep-learning"
confidence: high | medium | low
type: entity | concept | source-summary | comparison
search_hits: 0                        # 累计命中次数
---
```

### tags 字段
- 类型: list[str], **必填**, 通常 **3-7 个**
- 格式: **自由英文短语** (lowercase + 连字符 + singular)
- **写入时自动规范化** (无需手写规范):
  - 全部 lowercase
  - 空格 / 下划线 → 连字符 (`-`)
  - 多个连字符合一
  - 去 `-s` / `-ies` 复数后缀
  - 中文字符 strip
  - 长度 ≤ 30 字符
- **LLM 写新页前必查** `GET /wiki/tags` 看现有 tag, 优先复用, 仅在概念无对应时新建
- 例: `["image-stitching", "deep-learning", "parallax"]`

### 写作铁律
1. **每条事实必带 `[source: <chunk_id>]` 引用**（强制，否则视为 hallucination）
2. **wikilink 用 `[[主题]]` 格式**（不是 `[主题](主题.md)`）
3. **不写 chunks 里没有的内容**（LLM 不补充"常识"）
4. **矛盾点显式标注 "待验证"**
5. **现有主题必须先合并，不另建**（写新页前先 `grep` `~/wiki/`）

### 大小约束
- 每页 200-5000 字符
- < 200 字符 → 太小，合并到上级主题
- > 5000 字符 → 太大，拆分子主题

### 中立性原则
- **不预设写作者的项目背景**——wiki 是知识管理, 不是项目报告
- 禁止"本项目"、"我们"、"在我们的工作"等主观表述

## 工作流（LLM agent 必读）

### 收到用户查询时
1. 读 `purpose.md` + `index.md`（一次）
2. 判断：
   - **命中现有主题** → 读该 wiki 页 → 检查 `last_verified`
     - < 60 天 → 直接用，可能调 nollmkb 补充细节
     - > 60 天 → 标 stale，调 nollmkb 重写
   - **全新主题** → 直接调 nollmkb /query
3. 调 nollmkb（按需）：
   ```bash
   curl -X POST http://<server>:8765/query \
     -H "Content-Type: application/json" \
     -d '{"text":"<query>","top_k":5,"min_score":0.35}'
   ```
4. 决策是否写 wiki（**默认开 + 主题够新**）：
   - 主题已存在 → 更新现有页（**不另建**）
   - 主题新颖 → 检查是否有"已存在但同义"页 → 没有则新建
   - 主题太小/太专 → 写到 `_scratch.md` 而非正式页

### 两步链式思考 (nashsu 模式)

**Step 1 - 分析**:
- 列出关键实体/概念
- 找出与现有 wiki 的连接（补充/矛盾）
- 推荐结构（新建/更新/合并）

**Step 2 - 生成**:
- 写或更新 wiki 页（含 frontmatter + wikilinks + 引用）
- 更新 `index.md`（新增/修改时）
- 追加 `log.md`（按 `[YYYY-MM-DD] action | topic` 格式）

## 工具调用
- `python3 scripts/ingest.py` — 检查 source 是否变化（**不调 LLM**）
- `python3 scripts/relevance.py <topic>` — 找相关页（不调 LLM）
- `python3 scripts/lint.py` — 7 项健康检查（1-3, 6-7 不调 LLM；4-5 调）

## 维护节奏
- **周跑**: `lint.py` 的 1-3, 6-7（自动，无 LLM）
- **月跑**: `lint.py` 的 4-5（手动，调 LLM 审）
- **事件触发**: nollmkb 添加新文档时，跑 ingest
