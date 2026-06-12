# nollmkb API

## 远程访问

```
IP:   <your-server>
端口: 8765
协议: HTTP
认证: 可选 Bearer token (auth/users.toml)
```

> **安全提示**：远程访问时把 `NOLLMKB_HOST` 设为 Tailscale IP（如 `100.x.x.x`），不要用 `0.0.0.0`。`0.0.0.0` 会同时在局域网上开放，同网段内任何人都能访问。

### 认证

nollmkb 使用统一的 bearer token 认证。管理员通过 `scripts/gen_token.py` 生成 token 分发给用户，用户不需要自己记密码。

**管理员生成 token**：

```bash
# 终端运行
uv run python3 scripts/gen_token.py alice
# 输出:
#   Token: nkb_alice_X8q2mK9p4L5v...
#   Hash:  c71386f14555a2f687...
```
把 `Hash:` 行写入 `auth/users.toml`，把 `Token:` 行（如 `nkb_alice_X8q2mK9p...`）发给 alice。

**用户使用**：

```bash
curl -H "Authorization: Bearer nkb_alice_X8q2mK9p4L5v..." http://<server>:8765/health
```

> `.env` 里不存任何 token 或 hash。`auth/users.toml` 只存 hash，不存 token 原文。偷看 `users.toml` 的人拿不到可用的 token。token 泄露时可在 `users.toml` 中删除对应行来吊销。更改后需重启服务。

```bash
curl -H "Authorization: Bearer nkb_alice_xxx" http://<server>:8765/health
```

不设 key 时无需此头，行为不变。

## 接口

### 0. 服务根（远程 agent 必读）

```
GET http://<server>:8765/
```

返回所有可用端点 + 推荐 agent 工作流。**远程 agent 第一步应调用此端点**了解服务全貌。

返回:
```json
{
  "service": "TinyKB / nollmkb",
  "endpoints": {
    "rag": [{"method": "GET", "path": "/health", "desc": "..."}, ...],
    "wiki": [{"method": "GET", "path": "/wiki/protocol", "desc": "★ 必读..."}, ...]
  },
  "agent_workflow": ["1. GET /", "2. GET /wiki/protocol", "3. GET /health", ...]
}
```

### 1. 健康检查

```
GET http://<server>:8765/health
```

返回: `{"status":"ok","chunks":<文档chunk总数>}`

### 2. 查询

```
POST http://<server>:8765/query
Content-Type: application/json

{
  "text": "<你的问题>",
  "top_k": 5,
  "dir": "<可选: 限定检索目录，如 '论文' 或 '项目/2025'>",
  "filters": {"ext": ".pdf", "dir": "论文"},
  "min_score": 0.35
}
```

| 参数 | 必填 | 默认 | 说明 |
|------|:--:|------|------|
| text | 是 | - | 查询文本 |
| top_k | 否 | 5 | 返回数量，范围 1-20 |
| dir | 否 | - | 限定检索子目录（前缀匹配） |
| filters | 否 | - | metadata 多维过滤，如 `{"ext":".pdf","dir":"论文"}` |
| min_score | 否 | 0.0 | 最低相关度（0-1） |
| rerank | 否 | true | 启用 cross-encoder 重排序 |
| context | 否 | false | 附加前后 chunk 上下文 |
| bm25 | 否 | true | 混入 BM25 关键词召回 |

**filters 支持的字段:** `ext`（文件后缀）、`dir`（顶级目录）、`source`（文档路径）

返回:

```json
{
  "query": "<你问的问题>",
  "results": [
    {
      "source": "任务书.pdf",
      "chunk": 12,
      "score": 0.64,
      "text": "<匹配的文档片段>",
      "context_before": "<上一段文本，仅 context=true 时返回>",
      "context_after": "<下一段文本，仅 context=true 时返回>"
    }
  ],
  "elapsed_ms": 127
}
```

`score` 为余弦相似度（0-1），`elapsed_ms` 为查询耗时（毫秒）。

**自动去重**：相同文本只返回 score 最高的一条，避免同一文件在多目录下重复占位。

### 3. 上传文档

```
POST http://<server>:8765/upload
Content-Type: multipart/form-data

 files: <pdf/docx/pptx/txt/md/py/json/csv/html 等>
```

### 4. 批量扫描入库

```
POST http://<server>:8765/scan
```

扫描服务器 inputs/ 目录下所有文件，自动去重增量入库。

### 4.1 扫描状态

```
GET http://<server>:8765/scan/status
```

返回当前扫描进度：`{"running": bool, "current": int, "total": int, "current_file": "...", "last_result": "..."}`。

### 4.2 待处理文件数

```
GET http://<server>:8765/scan/pending
```

快速统计 inputs/ 目录下待处理文件数（不解析、不 embedding）。返回 `{"pending": <数量>}`。

### 5. 文档列表

```
GET http://<server>:8765/documents
```

返回每份文档的名称、chunk 数、文件后缀和所属目录。

```json
{"documents": [{"source": "论文/某论文.pdf", "chunks": 42, "ext": ".pdf", "dir": "论文"}, ...]}
```

### 6. 删除文档

```
DELETE http://<server>:8765/documents?source=论文/某论文.pdf
```

删除指定文件的所有 chunk。省略 `source` 则清空全部。

### 6.5 认证（会话登录）

bearer token 认证方式：

- **Agent/curl**：直接 `Authorization: Bearer <token>`，服务端从 `auth/users.toml` 查 hash → 用户名
- **WebUI 登录**：向 `/auth/login` 发送 token 换取 24h session token（避免频繁传输原始 token）

```
POST http://<server>:8765/auth/login
Content-Type: application/json

Body: {"token": "nkb_alice_X8q2mK9p..."}
```

返回：`{"token": "...", "user": "用户名", "expires_in": 86400}`

所有请求带 `Authorization: Bearer <token>` 即可。登录页免认证。

### 7. Wiki 系统（6 GET + 4 POST）

`wiki/` 目录下的 LLM 综合笔记，6 GET + 4 POST 端点。详细协议通过 **`GET /wiki/protocol`** 远程获取（不需读本地文件）。

#### 7.1 列出主题
```
GET /wiki/list
```
返回 `{count, topics: [{topic, title, type, last_verified, confiance, size}], protocol_endpoint, usage_hint}`

**响应里的 `protocol_endpoint: "/wiki/protocol"` 提示远程 agent 必先读协议。**

#### 7.2 读协议（远程 agent 必读）
```
GET /wiki/protocol
GET /wiki/protocol?file=CLAUDE
GET /wiki/protocol?file=schema
GET /wiki/protocol?file=purpose
```

远程 agent 通过本端点**远程读取** wiki 系统协议（不需访问本地文件系统）：
- `purpose.md` — wiki 存在的目的 + 关注范围 + 中立性原则
- `schema.md` — frontmatter 规范 + 写作铁律 + 大小约束
- `CLAUDE.md` — LLM agent 工作流 + 工具调用
- `?file=...` 指定单个；不传 = 3 个全返回
- 本地文件在 `wiki/shared/` 目录（多用户共享），缺失时 fallback 到 repo wiki_templates 内置默认

返回:
```json
{
  "wiki_dir": "/.../mykdb/wiki",
  "files": {
    "purpose": {"source": "local or builtin", "path": "shared/purpose.md", "content": "..."},
    "schema":  {"source": "local or builtin", "path": "shared/schema.md",  "content": "..."},
    "CLAUDE":  {"source": "local or builtin", "path": "shared/CLAUDE.md",  "content": "..."}
  },
  "usage_hint": "Read CLAUDE.md for workflow, schema.md for writing rules, purpose.md for scope"
}
```

#### 7.3 初始化协议文件

```
POST /wiki/init
POST /wiki/init?force=true
```

生成 wiki 默认文件（幂等：已有文件自动跳过，`?force=true` 覆盖）：

- **协议文件** → `wiki/shared/`（所有用户共享，人人可定制）：
  - `purpose.md` — wiki 目的与关注范围
  - `schema.md` — 页面规范与写作铁律
  - `CLAUDE.md` — LLM agent 工作流入口

- **骨架文件** → `wiki/{user}/`（当前认证用户的私有目录）：
  - `index.md` — 内容目录（空，agent 自觉维护）
  - `log.md` — append-only 操作日志（空，agent 自觉维护）

返回:
```json
{
  "wiki_dir": "/.../mykdb/wiki",
  "created": ["shared/purpose.md", "shared/schema.md", "shared/CLAUDE.md", "user007/index.md", "user007/log.md"],
  "skipped": [],
  "overwritten": [],
  "hint": "Protocol files are shared; skeleton files are per-user. Use force=true to overwrite."
}
```

> 首次部署时调用此端点生成 wiki 骨架，无需手动创建 protocol 文件。

#### 7.4 读页
```
GET /wiki/page?topic=notes/图像拼接技术路线综述
```
返回 `{topic, content (完整 md), frontmatter (解析后), mtime, size}`

#### 7.5 关键词搜
```
GET /wiki/search?q=深度监督&limit=10
```
返回 `{query, count, results: [{topic, title, snippet, match_in}]}`

#### 7.6 知识图
```
GET /wiki/graph
```
返回 `{node_count, edge_count, nodes, edges}` — 用于 D3/可视化或跨页 wikilink 关系分析。

#### 7.7 标签统计
```
GET /wiki/tags
```
返回 `{count, tags: [{name, count}]}` — 所有页面用过的 tag + 计数。LLM agent 写新页前必调，优先复用现有 tag。

#### 7.8 写前预览（diff）
```
POST /wiki/preview
Body: {"topic": "notes/xxx", "content": "---...---正文"}
```
返回 `{exists, old_size, new_size, added_lines, removed_lines, unified_diff}`。**不写入**任何文件，安全对比。

#### 7.9 创建/更新页（含 diff preview 双模式）
```
POST /wiki/page
Body: {
  "topic": "notes/xxx",
  "content": "---\ntitle: ...\n---\n正文",
  "source_chunks": ["文献/某论文.pdf_42"],  // 可选
  "tags": ["Deep Learning", "Parallax"],     // 可选，自动规范化
  "confirm": false                          // 默认只预览
}
```

**`confirm: false` 时**返回 diff 预览（同 7.8）。
**`confirm: true` 时**真正写入，**自动规范化**：
- 文件 fcntl 文件锁防并发损坏
- 路径安全检查（拒绝 `..` / `/` 开头）
- 自动更新 `hash_db` 的 `wiki_state` 段
- 自动注入规范化后的 `tags` 到 frontmatter

返回的 `tags_normalized` 是规范化结果（lowercase + 连字符 + singular + 去重 + 去中文）。

#### 7.10 删除页
```
POST /wiki/page/delete
Body: {"topic": "notes/xxx", "confirm": true}
```
`confirm: false` 只预览（不删），`confirm: true` 真删并从 cache 清除。

### Wiki 安全机制
- **路径越权防护**：`..` 和 `/` 开头的 topic 一律拒绝
- **并发写锁**：fcntl LOCK_EX
- **写入时规范化**：tags 字段自动 lowercase + 连字符 + singular + 中文 strip
- **缓存一致性**：`wiki_state` 复用 nollmkb 的 `hash_db`（mtime+size + hash 三级）
- **失败回滚**：文件先写、cache 后写；cache 失败时文件可重试

## 调用示例

```bash
# 如设置了认证, 所有请求追加:
#   -H "Authorization: Bearer <bearer_token>"

# 查询
curl -X POST http://<server>:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"某型号传感器精度是多少？"}'

# 限定目录 + 过滤低分
curl -X POST http://<server>:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"深度学习方法","dir":"论文","min_score":0.4}'

# metadata 多维过滤
curl -X POST http://<server>:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"图像分割","filters":{"ext":".pdf","dir":"论文"}}'

# 上传
curl -F "files=@/path/to/doc.pdf" http://<server>:8765/upload

# 扫描
curl -X POST http://<server>:8765/scan

# 扫描进度
curl http://<server>:8765/scan/status
curl http://<server>:8765/scan/pending

# 登录 (用 bearer token 换 session token)
curl -X POST http://<server>:8765/auth/login \
  -H "Content-Type: application/json" \
  -d '{"token":"nkb_alice_X8q2mK9p4L5v..."}'

# 查文档列表
curl http://<server>:8765/documents

# 删文件
curl -X DELETE "http://<server>:8765/documents?source=论文/某论文.pdf"

# === Wiki 示例 ===
# ★ 必读: 远程 agent 第一步, 拿协议
curl http://<server>:8765/wiki/protocol

# ★ 首次部署: 生成 wiki 骨架文件 (幂等, 已有文件自动跳过)
curl -X POST http://<server>:8765/wiki/init
curl -X POST "http://<server>:8765/wiki/init?force=true"  # 强制覆盖已有文件

# 列主题
curl http://<server>:8765/wiki/list

# 读
curl "http://<server>:8765/wiki/page?topic=notes/图像拼接技术路线综述"

# 搜
curl "http://<server>:8765/wiki/search?q=深度监督"

# 图谱
curl http://<server>:8765/wiki/graph

# 标签
curl http://<server>:8765/wiki/tags

# 写：先预览
curl -X POST http://<server>:8765/wiki/page \
  -H "Content-Type: application/json" \
  -d '{"topic":"notes/新主题","content":"---\ntitle: ...\n---\n正文","tags":["Deep Learning","Parallax"]}'
# 看 diff 满意后再 confirm=true
curl -X POST http://<server>:8765/wiki/page \
  -H "Content-Type: application/json" \
  -d '{"topic":"notes/新主题","content":"...","tags":["Deep Learning"],"source_chunks":["文献/某论文.pdf_42"],"confirm":true}'

# 删
curl -X POST http://<server>:8765/wiki/page/delete \
  -H "Content-Type: application/json" \
  -d '{"topic":"notes/旧主题","confirm":true}'
```

## 技术栈

- 向量库: ChromaDB (cosine 距离)
- Embedding: sentence-transformers BGE-M3 (1024 维)
- 文档解析: PyMuPDF / python-docx / python-pptx / openpyxl + 纯文本 30+ 格式
- 分块: block-packing 段落边界（200-3000 字符，~100 重叠），PDF/DOCX/PPTX/MD 统一
- 服务: FastAPI + Uvicorn
- 去重入库: mtime+size 快速路径 → hash 校验（600+ 文件 <1s）
- 去重查询: 文本哈希过滤相同内容

## Wiki 子系统

`wiki/` 目录是 LLM 综合的累积笔记层，与 ChromaDB 完全解耦：多用户架构，协议文件共享（shared/），笔记按用户隔离（{user}/notes/）：
- 物理位置: `mykdb/wiki/{user}/notes/*.md`（env `NOLLMKB_WIKI_DIR` 可配根目录）
- 元数据: frontmatter (YAML)，含 title / created / last_verified / sources (nollmkb chunk 引用) / related (wikilinks) / confidence / type / tags
- 协议文件: `wiki/shared/purpose.md` (为什么) / `wiki/shared/schema.md` (怎么写) / `wiki/shared/CLAUDE.md` (LLM agent 入口)
- 骨架文件: `wiki/{user}/index.md` (内容目录) / `wiki/{user}/log.md` (操作日志)
- 协议远程访问: 通过 `GET /wiki/protocol` 端点读取（本地文件优先，缺失时 fallback 内置默认）
- tag 系统: 自由英文短语，写入时自动规范化 (lowercase + 连字符 + singular + 去重 + strip 中文)
- 缓存: 复用 `hash_db.py` 的三级增量判断 (mtime+size → hash → 重写)，加 `wiki_state` 顶层 key
- 路径: `_safe_topic()` 防越权 (`..` 和 `/` 开头拒绝)
- 并发: fcntl 文件锁
- 写入流程: 预览 (`confirm=false`) → diff 对比 → 真写 (`confirm=true`) → 自动更新 cache
- 与 nollmkb 关系: nollmkb **不索引** wiki（避免退化为"另一个 vector DB"），wiki 也**不写回** nollmkb
- **工具脚本**（纯 Python，不调 LLM）:
  - `python3 scripts/relevance.py <topic>` — 4-信号相关性查找相关页（直接链接 + 来源重叠 + Adamic-Adar + 类型亲和）
  - `python3 scripts/lint.py` — 7 项 wiki 健康检查（孤页/过期/死链/缺交叉引用/来源漂移/大小异常/缺 tags），支持 `--json` 输出
