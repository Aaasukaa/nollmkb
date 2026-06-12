# nollmkb

> 轻量 RAG 引擎 + LLM-Wiki 渐进式知识库。18+ 端点，2 个小模型，WebUI + API。

## 这是什么
这是一个供claude/opencode/codex调用的个人本地知识库 + 可持续积累 LLM-wiki 项目。

**支持格式**：PDF、Word (.docx)、PowerPoint (.pptx)、Excel (.xlsx)、Markdown，以及 30+ 纯文本格式 (.txt/.py/.json/.yaml/.html/.tex/.c/.cpp/.go/.rs 等)。详见 `parsers.py`。

你有几百份文档（报告、论文、PPT、会议纪要）散落在不同目录下。nollmkb 解决两个问题：

**（一）精确检索** — 用自然语言搜文档，秒级返回最相关的原文片段

**（二）渐进积累** — 让 LLM agent 把检索结果综合成 markdown 笔记，持续沉淀为可检索的知识库

具体来说：

1. **把文档读进去** — PDF、Word、PPT、代码、Markdown、纯文本，自动分块、转成向量存起来
2. **用自然语言搜索** — 像用搜索引擎一样，输入问题，返回最相关的文档片段，支持 BM25+向量混合检索 + Reranker 重排序
3. **LLM agent 可写笔记** — 提供 `/wiki/*` HTTP API，远程 agent 检索后可写入综合笔记，带 frontmatter 元数据、chunk 引用溯源、wikilink 关联图
4. **纯 API + WebUI，不内置 LLM** — nollmkb 本身不调任何大模型。检索结果喂给 ChatGPT、Claude、OpenCode 等外部 LLM，由它们生成答案或写 wiki。提供可选的浏览器界面（`/ui/login.html`）供人类用户直接搜索和查看 wiki

打个比方：nollmkb 是图书馆的检索系统 + 你的笔记本。LLM 是帮你读论文的研究生——检索系统找到原文，研究生读完后用自己的话写进笔记本，下次遇到类似问题直接翻笔记就行。

wiki 永不被 nollmkb 索引（避免退化为"另一个 vector DB"），两者分层协作：向量库负责原文检索，wiki 负责累积理解。

## 适合谁

- 有大量文档资料，希望建立一个持久化的供大模型调阅的RAG知识库
- 希望在查询知识库的过程中逐渐积累个人LLM-wiki(推荐使用obsidian查看wiki文档与双向连接，但本项目不依赖obsidian cli功能)
- 有带显卡的个人电脑(显存>4GB)
- 推荐配合Tailscale远程查询知识库

### 与类似项目对比

| | 是否需要 LLM | RAG 检索 | Agent 笔记 | 文档解析 | BM25/Reranker | 纯 API | 部署难度 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Dify / MaxKB / FastGPT** | 内置 | ✅ | ❌ | ✅ | 部分 | ❌ 含 UI | 重 (Docker) |
| **PrivateGPT** (57k ⭐) | 外部必需 | ✅ | ❌ | ✅ | ❌ | ✅ | 中 (Ollama) |
| **deep-searcher** (7.9k ⭐) | 外部必需 | ✅ | ❌ | ✅ | ❌ | ✅ | 轻 |
| **ChromaDB** (17k ⭐) | 否 | ✅ | ❌ | ❌ | ❌ | ✅ | 轻 |
| **nollmkb** | **否** | ✅ | **✅** | ✅  | ✅ | ✅ | 轻 (uv sync) |

> nollmkb 是一个**完全不需要 LLM 即可运行的 RAG 引擎**，同时提供 LLM agent 驱动的 wiki 累积笔记层。ChromaDB 是纯向量库，无文档解析和混合检索。PrivateGPT 和 DeepSearcher 虽然不内置模型，但必须接外部 LLM 才能工作。

## 定位

大多数本地 RAG 项目往上加 LLM、加 UI、加 Docker 变成平台。nollmkb 往下走——API 优先、与 LLM 完全解耦，提供可选的轻量 WebUI（单页面，零构建），BGE-M3 做 embedding + Reranker 排序，通过你自己的任何 LLM agent 本地或远程查询你的知识库，并积累 wiki 笔记(可选)。Wiki 子系统补齐了"查完就忘"的短板，让检索结果可累积、可溯源、可关联。。

```
                有 LLM（重）          无 LLM（轻）
                ────────              ────────
平台级   Dify / MaxKB / FastGPT     空缺
工具级   PrivateGPT / Kotaemon     nollmkb ◄  (RAG + Wiki)
库级     LangChain / LlamaIndex     ChromaDB 本体
```

## 环境要求

- Python >= 3.11
- **GPU (推荐)**: 4+ GB VRAM (BGE-M3 1.3 GB + Reranker 2 GB + PyTorch 开销)
- **CPU (不推荐)**: 在 `.env` 中设置 `NOLLMKB_DEVICE=cpu`，查询延迟显著增加
- `uv` (推荐) 或 `pip` 管理依赖
- **支持平台**: Linux / macOS / Windows（`.env` 配置方式三平台通用）

### ⚠️ 安全警告

nollmkb 默认仅监听 `127.0.0.1`（只有本机能访问），且无需认证。

**如需远程访问，务必绑定 Tailscale IP 而非 `0.0.0.0`**。`0.0.0.0` 会在所有网卡上同时监听——局域网、Tailscale、公网（如有）全部敞开，同一网段内任何人都能读写删除你的全部文档。

正确做法：服务端跑 `tailscale ip -4` 拿到 IP（类似 `100.x.x.x`），在 `.env` 里写：

```
NOLLMKB_HOST=100.x.x.x
```

这样一来只有 Tailscale 虚拟网卡在监听，局域网网卡自动关闭。如需加一层访问保护，用 `scripts/gen_token.py` 生成 bearer token（见场景三）。

> **免责声明**：本项目为个人知识管理工具，安全防护有限。开启远程访问后，**请勿**将隐私、涉密、受法规保护的敏感文档放入可检索目录。因不当使用造成的任何数据泄露或损失，项目作者不承担责任。

> **如何获取你的服务器 IP**：  
> 本机访问 → `http://127.0.0.1:8765`  
> Tailscale 访问 → 先在服务器上跑 `tailscale ip -4` 得到 IP，然后 `http://<该IP>:8765`  
> 使用 API 时把 `API.md` 里的 `<server>` 替换为你的实际 IP

## 实测规模

13,398 chunks / 查询秒回。

## 快速开始
使用uv管理python虚拟环境(可选) -> [uv官方安装教程](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# 1. 部署
git clone https://github.com/Aaasukaa/nollmkb.git
cd nollmkb
uv sync # 非必须，不想用uv可选用conda等一切你喜欢的方式管理python环境

# 2. 配置 (可选, 选一种即可)
# 运行交互式配置向导(推荐):
uv run python3 scripts/setup.py
# 或者手动编辑.env配置:
# Linux/Macos
cp .env.example .env
# Windows PowerShell
Copy-Item .env.example .env
# Windows 命令提示符 (cmd)
copy .env.example .env

# 3. 放文档 (在 nollmkb/ 同级目录)
mkdir ../inputs && cp /your/docs/* ../inputs/

# 4. 启动 (首次自动扫描入库)
uv run python3 server.py # (首次启动服务会自动从 HuggingFace 下载模型, 这一步国内网络环境可能有点慢，有条件配合魔法或者设置镜像源)
```

### 目录布局

nollmkb 启动时自动读 `.env`，不用 `export`。改了保存就行。

```
mykb/                        ← 你建的任意文件夹
├── nollmkb/                 ← 克隆下来的代码
├── inputs/                  ← 放你要检索的文档（默认）
├── chromadb_storage/        ← 向量库数据（自动创建）
├── wiki/                    ← wiki 笔记（自动创建）
└── logs/                    ← 日志文件（自动创建）
```

### 可配项

所有配置都在 `.env` 中设置。**不写就用默认值**，什么都不配也能跑。

| 在 .env 里写 | 默认 | 说明 |
|-------------|------|------|
| `NOLLMKB_HOST=100.x.x.x` | `127.0.0.1` | 远程访问改 Tailscale IP（`tailscale ip -4` 查看）。**不要写 `0.0.0.0`** |
| `NOLLMKB_DOCS_DIR=/path/` | `../inputs` | 文档目录 |
| `NOLLMKB_KB_DIR=/path/` | `../chromadb_storage` | ChromaDB 向量库存储 |
| `NOLLMKB_WIKI_DIR=/path/` | `../wiki` | wiki 笔记目录 |
| `NOLLMKB_HASH_FILE=/path/` | `<KB_DIR>/file_hashes.json` | 入库去重缓存 |
| `NOLLMKB_COLLECTION=nollmkb` | `nollmkb` | ChromaDB collection 名 |
| `NOLLMKB_LOG_DIR=/path/` | `../logs` | 日志目录 |
| `NOLLMKB_DEVICE=cpu` | `cuda` | 没显卡改成 `cpu`（不推荐）|
| `NOLLMKB_USERS_FILE=/path/` | `auth/users.toml` | bearer token 用户配置（用 `scripts/gen_token.py` 生成）|

### 进阶：修改代码常量

`config.py` 中还有一组不受 `.env` 控制的常量，需要直接改源码：

```python
EMBED_MODEL = "BAAI/bge-m3"   # embedding 模型，和rerank模型一样可自定义
CHUNK_SIZE = 1500             # 分块大小，每次查询命中返回的文字长度
CHUNK_OVERLAP = 100           # 块重叠字符数
EMBED_BATCH = 128             # embedding 批次大小（该数字仅在初次建立向量库时生效，过大会占用较多显存,过小第一次建立向量库会比较慢）
TOP_K = 5                     # 查询返回数
```

### 常见场景

**场景一：我就本机用，什么都不想配**

```bash
uv run python3 server.py
# 服务跑在 127.0.0.1:8765，只有本机能访问
```

**场景二：希望其他电脑用户也能远程访问（推荐 Tailscale 建立虚拟局域网）**

```bash
tailscale ip -4        # 拿到 IP（类似 100.x.x.x）
```
在 `.env` 里写 `NOLLMKB_HOST=100.x.x.x`（填你实际的 Tailscale IP）。其他电脑访问 `http://100.x.x.x:8765`。

**为什么不用 `0.0.0.0`**：它会同时在局域网网卡上监听，同网段任何人都能访问。绑定 Tailscale IP 只开放虚拟网卡，更安全。

设置用户访问密钥：
```bash
# 生成一个 bearer token
uv run python3 scripts/gen_token.py alice
# 把输出的 Hash 行写入 auth/users.toml，Token 发给用户
```
用户请求时加 `-H "Authorization: Bearer nkb_alice_..."`。`users.toml` 只存 hash，不存 token。

## 使用

nollmkb 的核心交互方式是通过 LLM agent（OpenCode、Claude Code、Codex 等）——把 `API.md` 丢给 agent，它就能自己调接口。也提供可选的浏览器界面（`http://<服务器>:8765/ui/login.html`）供人类用户直接搜索和查看 wiki。

### 给 agent 接入

将 `API.md` 的内容（或直接给 URL）粘贴给 agent，让它读一遍。agent 会按如下流程工作：

```
1. GET /           → 看到所有端点
2. GET /wiki/protocol → 读 wiki 协议（CLAUDE.md + schema.md + purpose.md）
3. GET /health     → 确认服务可用
```

之后你就可以用自然语言提需求，agent 自动调接口完成。

### 你能做什么

| 场景 | 你输入 | agent 执行 |
|------|--------|-----------|
| **搜索文档** | "关于 SLAM 技术路线有哪些资料" | `POST /query` 检索向量库，返回原文片段 |
| **限定范围搜** | "只看 PDF 论文里的图像拼接方法" | `POST /query` + `filters={"ext":".pdf","dir":"论文"}` |
| **写篇综述** | "基于检索结果写一篇 SLAM 技术路线综述，存到 wiki" | 检索 → 综合 → `POST /wiki/page` 写入笔记 |
| **查 wiki 笔记** | "我之前整理的 SLAM 笔记有哪些" | `GET /wiki/list` → `GET /wiki/page` |
| **搜 wiki** | "wiki 里有没有关于 NeRF 的内容" | `GET /wiki/search?q=NeRF` |
| **更新旧笔记** | "SLAM 综述里关于 3DGS 的部分过时了，更新一下" | 检索新资料 → `POST /wiki/preview` 看 diff → `POST /wiki/page confirm=true` 真写 |
| **看知识图谱** | "wiki 里各主题之间怎么关联的" | `GET /wiki/graph` 返回 wikilink 邻接图 |
| **新增文档** | "把这个 PDF 加到库里" | `POST /upload` 或放 `inputs/` 目录 → `POST /scan` |
| **管理文档** | "库里有哪些文档 / 删掉那个" | `GET /documents` / `DELETE /documents?source=...` |

### 使用 WebUI

nollmkb 自带一个轻量的浏览器界面（零构建，打开即用），适合非技术用户或偶尔想直接查看的场景。

**启动后访问**：`http://<服务器IP>:8765/ui/login.html`

**首次使用**：

1. `uv run python3 scripts/gen_token.py alice` 生成 token，把 hash 写入 `auth/users.toml`（编辑后需重启服务）
2. 浏览器打开登录页，输入 token
3. 进入搜索页后，先在"文档管理"页上传文档，点击"开始建库"
4. 建库完成后即可搜索

**6 个功能页面**：

| 页面 | 地址 | 功能 |
|------|------|------|
| 登录 | `/ui/login.html` | 用户认证，获取 session token |
| 搜索 | `/ui/search.html` | 自然语言搜索，支持混合/语义/关键词三种模式 + 重排序 + 文件类型筛选 |
| Wiki | `/ui/wiki-list.html` | 查看自己的 wiki 笔记列表 + D3.js 知识图谱 |
| 阅读 | `/ui/wiki-read.html?topic=xxx` | 阅读笔记全文 |
| 编辑 | `/ui/wiki-edit.html?topic=xxx` | 修改笔记正文（frontmatter 只读） |
| 文档 | `/ui/documents.html` | 拖拽上传、文档列表、删除、扫描进度 |

**与 agent 的关系**：WebUI 和 agent 走同一套 API，共享向量库。agent 负责创建和更新 wiki 笔记（需要 LLM 综合检索结果），WebUI 负责人直接搜索和阅读。两者互不干扰。wiki 笔记按用户隔离，多人共用时互不可见。

## API

```bash
# 查询
curl -X POST http://localhost:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"某型号传感器精度是多少？","top_k":5,"min_score":0.35,"rerank":true,"context":true}'

# metadata 多维度过滤
curl -X POST http://localhost:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"深度学习方法","filters":{"ext":".pdf","dir":"论文"}}'

# 限定目录（向下兼容）
curl -X POST http://localhost:8765/query \
  -H "Content-Type: application/json" \
  -d '{"text":"图像分割","dir":"论文"}'

# 批量扫描
curl -X POST http://localhost:8765/scan

# 扫描进度 / 待处理文件数
curl http://localhost:8765/scan/status
curl http://localhost:8765/scan/pending

# 用户登录
curl -X POST http://localhost:8765/auth/login \
  -H "Content-Type: application/json" \
  -d '{"user":"alice","password":"xxx"}'

# 文档列表
curl http://localhost:8765/documents

# 上传
curl -F "files=@doc.pdf" http://localhost:8765/upload

# 删除
curl -X DELETE "http://localhost:8765/documents?source=论文/某论文.pdf"

# 健康检查
curl http://localhost:8765/health

# 根端点 (远程 agent 必读 - 列出所有端点 + 推荐工作流)
curl http://localhost:8765/

# === Wiki (6 GET + 4 POST 端点) ===
# 协议 (远程 agent 第一步: 读 CLAUDE.md / schema.md / purpose.md)
curl http://localhost:8765/wiki/protocol

curl http://localhost:8765/wiki/list                    # 列主题 (含 protocol_endpoint 提示)
curl "http://localhost:8765/wiki/page?topic=notes/xxx" # 读
curl "http://localhost:8765/wiki/search?q=xxx"          # 搜
curl http://localhost:8765/wiki/graph                  # 知识图
curl http://localhost:8765/wiki/tags                   # 标签
curl -X POST "http://localhost:8765/wiki/init?force=true" # 初始化 wiki
curl -X POST http://localhost:8765/wiki/page \
  -H "Content-Type: application/json" \
  -d '{"topic":"notes/xxx","content":"---\n...\n---","tags":["Deep Learning"],"confirm":true}'
```

详见 [API.md](API.md)。

| 参数 | 默认 | 说明 |
|------|------|------|
| `text` | (必填) | 查询文本 |
| `top_k` | 5 | 返回数量，范围 1-20 |
| `dir` | — | 限定检索子目录（前缀匹配，下行兼容） |
| `filters` | — | metadata 多维过滤，如 `{"ext":".pdf","dir":"论文"}` |
| `min_score` | 0.0 | 最低余弦相似度 |
| `rerank` | true | BGE Reranker 重排序 |
| `context` | false | 返回前后相邻 chunk |
| `bm25` | true | 混入 BM25 关键词召回 |

## 技术栈

| 组件 | 选型 | 占用 |
|------|------|------|
| Embedding | sentence-transformers BGE-M3 (1024 维, fp16) | ~1.3 GB VRAM |
| Reranker | BGE-Reranker-v2-m3 (懒加载) | ~2.0 GB VRAM |
| 向量库 | ChromaDB (Cosine) | ~200 MB 磁盘 |
| 文档解析 | PyMuPDF (双栏识别) / python-docx / python-pptx / openpyxl | — |
| 纯文本/MD | block-packing 段落边界；txt/py/json 等 30+ 格式 | — |
| 服务 | FastAPI + Uvicorn | ~2.3 GB RAM |
| Wiki | `wiki_server.py` (FastAPI router) + fcntl + `hash_db` 三级缓存 | 极小 |

## Wiki 子系统

`wiki/` 目录是 LLM 综合的累积笔记层（**仅 markdown 文件**），与 ChromaDB 完全解耦：

- **物理位置**：`wiki/{user}/notes/*.md`（默认 `../wiki`，env `NOLLMKB_WIKI_DIR` 可配根目录；多用户架构：协议共享、笔记隔离）
- **协议文件**：`wiki/shared/{purpose,schema,CLAUDE}.md`（可通过 `POST /wiki/init` 一键生成，或从 `wiki_templates/` 复制到 `wiki/shared/`）
- **协议远程访问**：远程 agent 通过 `GET /wiki/protocol` 端点读取（本地文件优先，缺失时 fallback nollmkb 内置默认）
- **元数据**：每页 frontmatter (YAML)，含 title / created / last_verified / sources (nollmkb chunk 引用) / related (wikilinks) / confidence / type / tags
- **骨架文件**：`wiki/{user}/{index,log}.md`（agent 自觉维护，服务端不做自动更新）
- **Tag 系统**：自由英文短语，写入时自动规范化 (lowercase + 连字符 + singular + 去重 + strip 中文)
- **增量缓存**：复用 `hash_db.py` 的三级增量 (mtime+size → hash → 重写)，加 `wiki_state` 顶层 key
- **安全**：路径防越权（拒绝 `..` / `/` 开头）+ fcntl 文件锁
- **写入流程**：预览 (`confirm=false` 显示 diff) → 真写 (`confirm=true`)
- **与 nollmkb 关系**：nollmkb **不索引** wiki（避免退化为"另一个 vector DB"），wiki 也**不写回** nollmkb

**远程 agent 推荐工作流**（详见 `GET /` 根端点）：
1. `GET /` → 看到所有端点
2. `GET /wiki/protocol` → 读 CLAUDE.md + schema.md + purpose.md
3. `GET /health` → 服务可用
4. `POST /query` → 查 raw 资料
5. `GET /wiki/tags` → 复用现有 tag
6. `POST /wiki/preview` → 写前 diff 预览
7. `POST /wiki/page confirm=true` → 真写

完整协议见 [API.md](API.md)。

## 性能测试

Ubuntu + A100 40GB。

| 模式 | 首次 | 后续平均 |
|------|------|------|
| Reranker 开（默认） | ~10,000ms | ~500ms |
| Reranker 关 | ~80ms | ~80ms |

### 资源占用（实际测量）

| 资源 | 占用 | 明细 |
|------|------|------|
| 显存 | 4 GB | BGE-M3 1.3 GB + Reranker 2.0 GB + PyTorch 运行时开销 |
| 内存 | 2.3 GB | BM25 索引 + ChromaDB + Reranker + Python 运行 |
| 磁盘 | ~200 MB | chroma.sqlite3 + file_hashes.json + wiki/ |

## 为什么轻

| 功能 | 大多数项目 | nollmkb |
|------|-----------|--------|
| LLM 回答 | 内置大模型 | 无——LLM 远程 HTTP 接入 |
| 分块 | 多种可选 | block-packing 段落边界 + 重叠 |
| 去重 | 无 | 入库三级 (mtime+size→hash) + 查询文本哈希 |
| Rerank | 少数有 | cross-encoder 重排序 |
| 混合检索 | 少数有 | BM25 关键词 + 向量语义互补 |
| Context | 几乎无 | 可选返回前后 chunk |
| 监控 | 各种 SDK | logging |

LLM 不内嵌是最关键的设计决策——它把显存需求压在 4 GB 以内，换来同类方案 1/3 的资源占用。LLM 调用方（OpenCode、ChatGPT、Claude）通过 HTTP 查询 API，自然衔接。

## 类似项目

| | nollmkb | chromadb-mcp | PrivateGPT |
|---|---|---|---|
| API | 9 (RAG) + 10 (Wiki) | 通用向量 API | 完整但重 |
| 去重 | 三级 | 无 | 无 |
| Reranker | ✅ | ❌ | 含 LLM |
| Context | ✅ | ❌ | ❌ |
| 千万 token | ✅ 未测极限 | ✅ | ✅ |

## 项目结构

```
nollmkb/
├── server.py          入口：FastAPI 创建 + 启动逻辑
├── config.py          路径/模型/分块常量 (全部 env override)
├── logging_config.py  日志：RotatingFileHandler 10MB×3 + console
├── models.py          请求模型 (QueryRequest)
├── embedding.py       sentence-transformers BGE-M3 (fp16, GPU/CPU 自适应)
├── reranker.py        BGE-Reranker-v2-m3 懒加载
├── bm25.py            BM25 关键词索引 (jieba 分词)
├── hash_db.py         文件去重缓存 (含 wiki_state 顶层 key)
├── parsers.py         文档解析 (pdf/docx/pptx/xlsx/md/txt 等 30+ 格式)
├── chunker.py         文本分块 (block-packing 段落边界)
├── indexer.py         ChromaDB 初始化 + 扫描/索引引擎
├── routes.py          9 个 RAG API 端点 + GET / 根端点
├── wiki_server.py     10 个 Wiki API 端点 (6 GET + 4 POST)
├── scripts/           LLM agent 工具脚本
│   ├── ingest.py      增量缓存判断 (源文件是否变化)
│   ├── test_api.py    Wiki HTTP API 测试 (96 断言)
│   ├── relevance.py   4-信号相关性查找 (不调 LLM)
│   └── lint.py        7 项 wiki 健康检查 (不调 LLM)
├── wiki_templates/    默认协议 + 骨架模板 (随仓分发)
│   ├── purpose.md / schema.md / CLAUDE.md  (3 协议)
│   └── index.md / log.md                   (2 骨架)
├── static/               WebUI 静态文件 (6 HTML 页面)
├── auth/                 用户配置
│   └── users.toml.example  token hash 配置模板
├── .env.example           env 配置示例
└── LICENSE            MIT
```

## 行为流程

### 启动

1. 初始化 ChromaDB collection（默认 `nollmkb`，cosine 距离）
2. 自动扫描 `inputs/`：mtime+size 快速路径 → hash 校验 → 新文件解析/分块/向量化入库
3. 构建 BM25 倒排索引（jieba 分词，常驻内存）
4. Uvicorn 启动（默认监听 `127.0.0.1:8765`，`.env` 中 `NOLLMKB_HOST` 可改）

### 查询（POST /query）

```
向量检索(top_k×3, where 预过滤) → BM25(top_k×2) → 合并去重(200字hash)
  → dir 后过滤 → Reranker 重排序 → min_score 过滤
  → [可选] context 窗口 → 返回 top_k
```

- **向量检索**：BGE-M3 1024 维 + cosine 搜索
- **分块**：PDF/DOCX block-packing 段落边界（200-3000 字符，~100 字符重叠），双栏 PDF 自动检测；PPTX/XLSX 结构化提取
- **BM25**：jieba 中文分词 + 字面关键词匹配
- **去重**：两路结果取前 200 字 SHA256，相同文本只留一条
- **Reranker**（默认开）：BGE-Reranker-v2-m3 对每个 query-doc 对精确打分
- **context**（默认关）：可选返回命中 chunk 的前后相邻 chunk
- **异步**：query 端点为 `async def` + `asyncio.to_thread`，不阻塞事件循环

### 入库

启动时自动扫描 `inputs/`，三级缓存判断，只处理有变化的文件：

| 层级 | 判断条件 | 动作 |
|------|---------|------|
| L1 | mtime + size 不变 | 跳过（文件都不打开，最快） |
| L2 | mtime 变了但 hash 不变 | 跳过（文件被 touch 过，内容未改） |
| L3 | hash 变了 | 重新解析 → 分块 → BGE-M3 向量化 → 覆盖入库 |
| 新 | 无缓存记录 | 解析 → 分块 → BGE-M3 向量化 → 入库 |

入库后自动重建 BM25 索引。

### 数据流

```
文档 ─→ fitz/docx/pptx 解析 ─→ block-packing 分块 ─→ BGE-M3 embedding ─→ ChromaDB
                                                      ext/dir ────────────→ metadata
query ─→ BGE-M3 向量化 ─→ cosine 搜索 (where 过滤) ─┐
                                                     ├→ 合并去重 ─→ dir ─→ Reranker ─→ 返回
query ─→ jieba 分词 ─→ BM25 搜索 ───────────────────┘
```

### Wiki（POST /wiki/page）

```
LLM agent 读 chunks ─→ 写 markdown
   ↓
预览 (confirm=false) ─→ diff 对比 ─→ 用户确认
   ↓
真写 (confirm=true) ─→ fcntl 加锁 ─→ 写文件 ─→ 自动规范化 tags ─→ 更新 hash_db
```

## 致谢

本项目基于以下优秀开源项目构建：

| 项目 | 用途 |
|------|------|
| [ChromaDB](https://github.com/chroma-core/chroma) | 向量数据库 (embedding 存储 + 检索) |
| [sentence-transformers](https://github.com/UKPLab/sentence-transformers) | BGE-M3 embedding + Reranker |
| [FastAPI](https://github.com/fastapi/fastapi) | HTTP API 框架 |
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | PDF 解析 (双栏识别) |
| [jieba](https://github.com/fxsjy/jieba) | 中文分词 (BM25) |
| [LLM-Wiki](https://github.com/nashsu/llm_wiki) | Wiki 协议|

## 许可

MIT
