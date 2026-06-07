"""Wiki HTTP API.

6 GET + 4 POST endpoints, exposed for remote (Tailscale) access.

GET:
  /wiki/list          list all topics
  /wiki/page          read full page
  /wiki/search        keyword search
  /wiki/graph         wikilink adjacency graph (JSON)
  /wiki/tags          all tags with counts
  /wiki/protocol      protocol docs (local > builtin) — required for remote agent

POST:
  /wiki/init          generate default protocol + skeleton files (first deploy)
  /wiki/preview       diff preview before writing
  /wiki/page          create/update (confirm=true to persist)
  /wiki/page/delete   delete (requires confirm=true)
"""

import os
import re
import logging
import difflib
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Body, Request

# cross-platform file lock (fcntl on Unix, no-op on Windows)
try:
    import fcntl

    def _lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

except ImportError:
    def _lock_file(f):
        pass  # Windows: skip locking (single-user scenario)

from config import WIKI_DIR
from hash_db import load_hashes, save_hashes, file_hash


def _user_wiki_dir(request: Request = None) -> Path:
    """Get wiki root dir for current user. Falls back to WIKI_DIR for single-user mode."""
    if request is not None:
        user = getattr(request.state, "user", "").strip()
        if user:
            return Path(WIKI_DIR) / user
    return Path(WIKI_DIR)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wiki", tags=["wiki"])


# ============== built-in default protocol (OSS-friendly: ships with wiki_templates/ in repo) ==============
# Priority: local file > nollmkb built-in default
# On first startup with empty WIKI_DIR, call POST /wiki/init to auto-generate default files
# or manually cp nollmkb/wiki_templates/* to WIKI_DIR

_DEFAULT_PROTOCOL = {
    "purpose": (
        "# Wiki 目的\n\n"
        "## 为什么有这个 wiki\n"
        "加速对**科研文档**（论文、项目资料、技术报告）的持续理解与可检索积累。\n"
        "nollmkb (默认 127.0.0.1:8765) 是 raw 资料源；本 wiki 是 LLM 综合后的累积层。\n\n"
        "## 关注范围\n"
        "- 科研领域的方法学与技术路线\n"
        "- 跨论文/跨资料的概念整理与对比\n"
        "- 实验设计、数据处理、写作方法上的常见模式\n\n"
        "## 关键问题（示例）\n"
        "1. 某子领域的经典方法 vs 最新方法各自假设和适用场景\n"
        "2. 不同方法在统一 benchmark / 数据集上的表现差异\n"
        "3. 同一技术族内的多篇工作之间的继承与改进关系\n"
        "4. 跨学科概念的共通原理\n\n"
        "## 不关注\n"
        "- 商业产品对比\n"
        "- 政策合规细节\n"
        "- 与特定应用场景强绑定的内容\n\n"
        "## 演进论题\n"
        "- 当前: 跟踪各子领域技术路线的演化, 形成可复用的方法学理解\n"
        "- 目标: 当再次遇到相似问题时, wiki 已有的整理能快速定位\n\n"
        "## 与 nollmkb 的关系\n"
        "- nollmkb: 找原文（检索层）\n"
        "- wiki: 累积理解（综合层）\n"
        "- **wiki 永不被 nollmkb 索引**\n\n"
        "## 写法原则\n"
        "- 客观陈述领域现状, 不预设特定应用场景\n"
        "- 客观联系可写 (同论文/同作者/同技术族/共享数据集)\n"
        "- 每条事实带 `[source: <chunk_id>]` 引用, 不写 chunks 里没有的内容\n"
    ),
    "schema": (
        "# Wiki 协议\n\n"
        "> LLM agent 写/读 wiki 时**必读**的协议。OpenCode/Claude Code 启动后第一步读这个文件。\n\n"
        "## 目录结构\n"
        "```\n"
        "wiki/\n"
        "├── purpose.md              # 为什么有这个 wiki\n"
        "├── schema.md               # 本文件\n"
        "├── index.md                # LLM 维护的内容目录\n"
        "├── log.md                  # append-only 操作日志\n"
        "├── notes/                  # 所有内容页统一放这里\n"
        "└── .llm-wiki/\n"
        "    └── cache.json\n"
        "```\n\n"
        "## Frontmatter (必填)\n"
        "```yaml\n"
        "---\n"
        "title: 主题名\n"
        "created: 2026-06-05\n"
        "last_verified: 2026-06-05\n"
        "sources:                          # ← 引用 nollmkb chunk ID\n"
        "  - 路径/文件.pdf_42\n"
        "related:                          # ← wikilinks\n"
        "  - \"[[相关主题]]\"\n"
        "tags:                             # ← 3-7 个, 必填\n"
        "  - \"topic-name\"\n"
        "confidence: high | medium | low\n"
        "type: concept | source-summary | comparison\n"
        "search_hits: 0\n"
        "---\n"
        "```\n\n"
        "## tags 字段\n"
        "- 类型: list[str], **必填**, 通常 **3-7 个**\n"
        "- 格式: **自由英文短语** (lowercase + 连字符 + singular)\n"
        "- **写入时自动规范化** (无需手写规范):\n"
        "  - 全部 lowercase\n"
        "  - 空格 / 下划线 → 连字符 (`-`)\n"
        "  - 多个连字符合一\n"
        "  - 去 `-s` / `-ies` 复数后缀\n"
        "  - 中文字符 strip\n"
        "  - 长度 ≤ 30 字符\n"
        "- **LLM 写新页前必查** `GET /wiki/tags` 看现有 tag, 优先复用, 仅在概念无对应时新建\n\n"
        "## 写作铁律\n"
        "1. **每条事实必带 `[source: <chunk_id>]` 引用**（强制，否则视为 hallucination）\n"
        "2. **wikilink 用 `[[主题]]` 格式**\n"
        "3. **不写 chunks 里没有的内容**\n"
        "4. **矛盾点显式标注 \"待验证\"**\n"
        "5. **同主题先合并，不另建**\n\n"
        "## 大小约束\n"
        "- 每页 200-5000 字符\n"
        "- < 200 字符 → 太小，合并\n"
        "- > 5000 字符 → 太大，拆分\n\n"
        "## 中立性原则\n"
        "- **不预设写作者的项目背景**——wiki 是知识管理, 不是项目报告\n"
        "- 禁止\"本项目\"、\"我们\"、\"在我们的工作\"等主观表述\n\n"
        "## 两步链式思考\n"
        "**Step 1 - 分析**: 列出关键实体/概念, 找出与现有 wiki 的连接\n"
        "**Step 2 - 生成**: 写或更新 wiki 页, 更新 index.md, 追加 log.md\n"
    ),
    "CLAUDE": (
        "# Wiki 协议入口\n\n"
        "> **OpenCode / Claude Code 等 LLM agent 必读。**\n\n"
        "## 你的角色\n"
        "你是 **wiki 编译器**。维护 nollmkb 的 wiki 累积笔记层。\n"
        "- nollmkb 是你的**只读 raw 资料源**\n"
        "- wiki 是你**可写**的累积层\n"
        "- 你**唯一能调 LLM 的地方**——nollmkb 自己**不调**任何 LLM\n\n"
        "## 必读文件\n"
        "1. `purpose.md` — 为什么有这个 wiki\n"
        "2. `schema.md` — 完整协议（**必读**）\n"
        "3. `index.md` — 现有内容目录\n\n"
        "## 核心铁律\n"
        "1. **每条事实必带 `[source: <chunk_id>]` 引用**（无引用 = hallucination）\n"
        "2. **wikilink 用 `[[主题]]`** 格式\n"
        "3. **不写 chunks 里没有的内容**\n"
        "4. **同主题先合并, 不另建**\n"
        "5. **wiki 永不被 nollmkb 索引**（用户的设计红线）\n"
        "6. **中立性原则**: 不预设写作者的项目背景, 禁止\"本项目\"\"我们\"等主观表述\n"
        "7. **tags 字段 (必填)**: 3-7 个英文短词, 复用 > 新建, 写入时自动规范化\n\n"
        "## 工作流\n"
        "```\n"
        "1. 读 purpose.md + index.md (一次)\n"
        "2. 判断:\n"
        "   - 命中现有主题 → 读该 wiki 页 → 检查 last_verified\n"
        "   - 全新主题 → 调 nollmkb /query\n"
        "3. 调 nollmkb (按需):\n"
        "   curl -X POST http://127.0.0.1:8765/query \\\n"
        "     -H \"Content-Type: application/json\" \\\n"
        "     -d '{\"text\":\"<query>\",\"top_k\":5}'\n"
        "4. 写前先 GET /wiki/tags 看现有 tag, 优先复用\n"
        "5. 写时用 POST /wiki/preview 看 diff\n"
        "6. 真写用 POST /wiki/page confirm=true\n"
        "7. 写完更新 index.md, 追加 log.md\n"
        "```\n"
    ),
}


_DEFAULT_SKELETON = {
    "index": (
        "# Wiki 内容目录\n\n"
        "> LLM 维护。每次新建/删除/合并页面时同步更新。\n\n"
        "## notes/\n\n"
        "(建站初期，尚无页面)\n"
    ),
    "log": (
        "# Wiki 操作日志\n\n"
        "> append-only。格式: `[YYYY-MM-DD] action | topic | 简述`\n\n"
    ),
}


def _load_protocol_file(name: str) -> dict:
    """Load a single protocol file. Priority: shared/ local > built-in default."""
    shared = Path(WIKI_DIR) / "shared"
    local_path = shared / f"{name}.md"
    if local_path.exists():
        return {
            "source": "local",
            "path": f"shared/{name}.md",
            "content": local_path.read_text(encoding="utf-8"),
        }
    if name in _DEFAULT_PROTOCOL:
        return {
            "source": "builtin",
            "path": f"wiki_templates/{name}.md",
            "content": _DEFAULT_PROTOCOL[name],
        }
    return {
        "source": "missing",
        "path": f"{name}.md",
        "content": "",
        "warning": "file not found (neither local nor builtin)",
    }


def _resolve_template(name: str) -> str:
    """Read template from wiki_templates/ in repo (for initial local file generation)."""
    # repo template location: nollmkb/wiki_templates/<name>.md
    template_path = Path(__file__).parent / "wiki_templates" / f"{name}.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    # fallback to built-in constants (protocol) or skeleton defaults
    return _DEFAULT_PROTOCOL.get(name) or _DEFAULT_SKELETON.get(name, "")


# ============== utility functions ==============

def _safe_topic(topic: str) -> str:
    """Path safety check. Prevents directory traversal on write."""
    if not topic:
        raise HTTPException(400, "topic cannot be empty")
    if ".." in topic.split("/"):
        raise HTTPException(400, "topic contains illegal ..")
    if topic.startswith("/"):
        raise HTTPException(400, "topic cannot start with /")
    if not topic.endswith(".md"):
        topic = topic + ".md"
    return topic


def _abs_topic_path(topic: str, request: Request = None) -> Path:
    """Return (_user_wiki_dir(request) / topic) and verify it does not escape user dir."""
    safe = _safe_topic(topic)
    wiki_root = _user_wiki_dir(request).resolve()
    path = (wiki_root / safe).resolve()
    if not str(path).startswith(str(wiki_root) + os.sep) and path != wiki_root:
        raise HTTPException(400, f"path escape: {topic}")
    return path


def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter parser (no pyyaml dependency).

    Supports:
    - key: value          (scalar)
    - key:                (nested list, subsequent - items)
    """
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    fm = {}
    current_list_key = None
    for line in text[4:end].split("\n"):
        if not line.strip():
            current_list_key = None
            continue
        # list item
        if line.startswith("  - ") or line.startswith("- "):
            if current_list_key:
                item = line.split("- ", 1)[1].strip()
                # strip outer quotes (ASCII single/double, also curly)
                if len(item) >= 2 and item[0] == item[-1] and item[0] in ('"', "'", '\u201c', '\u201d', '\u2018', '\u2019'):
                    item = item[1:-1]
                fm.setdefault(current_list_key, []).append(item)
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                # start of nested list
                current_list_key = k
                fm[k] = []
            else:
                fm[k] = v
                current_list_key = None
    return fm


def _scan_pages(request: Request = None) -> list[Path]:
    """Scan user wiki dir for all .md files, skipping meta files."""
    wiki_root = _user_wiki_dir(request)
    skip_names = {"purpose.md", "schema.md", "CLAUDE.md", "index.md", "log.md"}
    pages = []
    if not wiki_root.exists():
        return pages
    for p in wiki_root.rglob("*.md"):
        if p.name in skip_names:
            continue
        pages.append(p)
    return sorted(pages, key=lambda x: str(x))


def _get_wikilinks(text: str) -> set[str]:
    """Extract [[wikilinks]]."""
    return set(re.findall(r'\[\[([^\]]+)\]\]', text))


def _diff_preview(old: str, new: str, n_context: int = 3) -> dict:
    """Generate unified diff preview."""
    diff = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="current",
        tofile="proposed",
        n=n_context,
    ))
    return {
        "added_lines": sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
        "removed_lines": sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
        "unified_diff": "".join(diff),
    }


def _normalize_tag(tag: str) -> str:
    """Normalize a single tag.

    Rules:
    - lowercase
    - spaces → hyphens (-)
    - collapse multiple hyphens
    - strip -s / -es plural suffixes
    - strip CJK characters
    - strip surrounding whitespace
    - truncate to 30 chars
    """
    if not tag or not isinstance(tag, str):
        return ""

    t = tag.strip()

    # strip CJK characters (range \u4e00-\u9fff and fullwidth symbols)
    t = re.sub(r'[\u4e00-\u9fff\uff00-\uffef\u3000-\u303f]', '', t)

    if not t:
        return ""

    # lowercase
    t = t.lower()

    # spaces and underscores → hyphens
    t = re.sub(r'[\s_]+', '-', t)

    # collapse multiple hyphens
    t = re.sub(r'-+', '-', t)

    # strip leading/trailing hyphens
    t = t.strip('-')

    # strip -s / -es plurals (simple rules, does not handle -ies / -ss / -us etc.)
    if t.endswith('ies') and len(t) > 4:
        t = t[:-3] + 'y'
    elif t.endswith('es') and len(t) > 4 and not t.endswith('-ses') and not t.endswith('-shes') and not t.endswith('-ches') and not t.endswith('-xes'):
        t = t[:-2]
    elif t.endswith('s') and len(t) > 3 and not t.endswith('-ss') and not t.endswith('-us') and not t.endswith('-is'):
        t = t[:-1]

    # truncate
    if len(t) > 30:
        t = t[:30].rstrip('-')

    return t


def _normalize_tags(tags: list) -> list[str]:
    """Normalize tag list: strip empties, dedupe, preserve order."""
    if not isinstance(tags, list):
        return []
    seen = set()
    result = []
    for raw in tags:
        norm = _normalize_tag(raw)
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)
    return result


def _collect_all_tags(request: Request = None) -> dict[str, int]:
    """Scan all wiki pages, collect tags with counts."""
    from collections import Counter
    counter = Counter()
    for p in _scan_pages(request):
        text = p.read_text(errors="replace")
        fm = _parse_frontmatter(text)
        for t in fm.get("tags", []) or []:
            if isinstance(t, str) and t.strip():
                counter[t.strip()] += 1
    return dict(counter.most_common())


def _inject_tags_into_frontmatter(content: str, tags: list[str]) -> str:
    """Inject tags into .md frontmatter.

    Behavior:
    - If content already has frontmatter (---...---), replace/add tags field
    - If no frontmatter, prepend one
    """
    if not tags:
        return content

    # build YAML-formatted tags field
    tags_yaml_lines = ["tags:"]
    for t in tags:
        tags_yaml_lines.append(f"  - {t}")
    tags_yaml = "\n".join(tags_yaml_lines)

    if content.startswith("---\n"):
        # has frontmatter, replace tags: lines
        end = content.find("\n---\n", 4)
        if end == -1:
            return content
        fm_block = content[4:end]

        # remove existing tags: section
        lines = fm_block.split("\n")
        new_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("tags:"):
                # skip existing tags: section (including its list items)
                i += 1
                while i < len(lines) and (lines[i].startswith("  - ") or lines[i].startswith("    ")):
                    i += 1
                continue
            new_lines.append(line)
            i += 1

        new_fm = "\n".join(new_lines).rstrip("\n")
        # append tags section at end of frontmatter
        new_content = "---\n" + new_fm + "\n" + tags_yaml + "\n---\n" + content[end+5:]
        return new_content
    else:
        # no frontmatter, prepend one
        return "---\n" + tags_yaml + "\n---\n\n" + content


# ============== GET endpoints ==============

@router.get("/list")
def wiki_list(request: Request):
    """List all wiki topics with frontmatter summary."""
    wiki_root = _user_wiki_dir(request)
    pages = _scan_pages(request)
    items = []
    for p in pages:
        rel = p.relative_to(wiki_root).as_posix()
        text = p.read_text(errors="replace")
        fm = _parse_frontmatter(text)
        items.append({
            "topic": rel,
            "title": fm.get("title", rel),
            "type": fm.get("type", "unknown"),
            "last_verified": fm.get("last_verified", ""),
            "confidence": fm.get("confidence", ""),
            "size": p.stat().st_size,
        })
    return {
        "count": len(items),
        "topics": items,
        "protocol_endpoint": "/wiki/protocol",
        "init_endpoint": "/wiki/init",
        "usage_hint": "First-time access: GET /wiki/protocol to read CLAUDE.md + schema.md + purpose.md (falls back to builtin if no local files)",
    }


@router.get("/page")
def wiki_page(request: Request, topic: str = Query(..., description="relative path under wiki/, with or without .md")):
    """Read full page content + parsed frontmatter."""
    wiki_root = _user_wiki_dir(request)
    path = _abs_topic_path(topic, request)
    if not path.exists():
        raise HTTPException(404, f"topic not found: {topic}")
    text = path.read_text(errors="replace")
    st = path.stat()
    return {
        "topic": path.relative_to(wiki_root).as_posix(),
        "content": text,
        "frontmatter": _parse_frontmatter(text),
        "mtime": st.st_mtime,
        "size": st.st_size,
    }


@router.get("/search")
def wiki_search(request: Request, q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    """Keyword search frontmatter + body. Returns snippet with context."""
    wiki_root = _user_wiki_dir(request)
    q_lower = q.lower()
    results = []
    for p in _scan_pages(request):
        text = p.read_text(errors="replace")
        text_lower = text.lower()
        if q_lower not in text_lower:
            continue
        idx = text_lower.find(q_lower)
        start = max(0, idx - 80)
        end = min(len(text), idx + len(q) + 80)
        snippet = text[start:end].replace("\n", " ")
        rel = p.relative_to(wiki_root).as_posix()
        fm = _parse_frontmatter(text)
        results.append({
            "topic": rel,
            "title": fm.get("title", rel),
            "snippet": f"...{snippet}...",
            "match_in": "frontmatter" if q_lower in str(fm).lower() else "body",
        })
        if len(results) >= limit:
            break
    return {"query": q, "count": len(results), "results": results}


@router.get("/graph")
def wiki_graph(request: Request):
    """Return wikilink adjacency graph (D3/visualization-friendly).

    Wikilink resolution strategy: prefer exact path matches,
    fall back to stem-only matching across directories.
    """
    wiki_root = _user_wiki_dir(request)
    pages = _scan_pages(request)
    nodes = []
    page_data = {}
    page_paths_by_stem: dict[str, list[str]] = {}  # stem -> [relative path]

    for p in pages:
        rel = p.relative_to(wiki_root).as_posix()
        text = p.read_text(errors="replace")
        fm = _parse_frontmatter(text)
        page_data[rel] = {
            "outgoing": _get_wikilinks(text),
            "metadata": fm,
        }
        # index stem (filename without .md extension) -> path list
        stem = Path(rel).stem
        page_paths_by_stem.setdefault(stem, []).append(rel)
        nodes.append({
            "id": rel,
            "title": fm.get("title", rel),
            "type": fm.get("type", "unknown"),
        })

    # pre-build set of all relative paths for fast lookup
    all_paths = set(page_data.keys())

    edges = []
    for src, data in page_data.items():
        for tgt in data["outgoing"]:
            tgt_name = tgt if tgt.endswith(".md") else tgt + ".md"
            # 1) exact path match
            if tgt_name in all_paths:
                resolved = tgt_name
            # 2) bare topic name (same-name file in any directory)
            elif tgt in page_paths_by_stem:
                resolved = page_paths_by_stem[tgt][0]  # first match
            else:
                # 3) keep as-is, shown as orphan node in graph
                resolved = tgt_name
            edges.append({
                "source": src,
                "target": resolved,
                "weight": 1.0,
            })

    return {"node_count": len(nodes), "edge_count": len(edges), "nodes": nodes, "edges": edges}


@router.get("/tags")
def wiki_tags(request: Request):
    """Return all tags used across wiki pages with counts, sorted by count desc.

    LLM agent must call this before writing: reuse existing tags,
    only create new ones when no match exists.
    """
    counts = _collect_all_tags(request)
    tags = [{"name": name, "count": cnt} for name, cnt in counts.items()]
    return {"count": len(tags), "tags": tags}


@router.get("/protocol")
def wiki_protocol(request: Request, file: str = Query("all", description="file name: purpose | schema | CLAUDE | all")):
    """Return wiki protocol text (for remote LLM agent to read).

    Priority: local WIKI_DIR/<name>.md > nollmkb built-in default.
    - Falls back to nollmkb/wiki_templates/ or built-in constants when local file missing (OSS-friendly)
    - To persist defaults locally: call POST /wiki/init to generate template files in WIKI_DIR

    The remote agent learns from this endpoint:
    - wiki writing rules (schema.md: frontmatter spec + rules)
    - wiki purpose (purpose.md: scope + neutrality principle)
    - agent workflow (CLAUDE.md: workflow + tool usage)

    Args:
        file: "all" (default) returns all 3; or "purpose" / "schema" / "CLAUDE" for a single one
    """
    valid_names = list(_DEFAULT_PROTOCOL.keys())

    if file == "all":
        result = {}
        for name in valid_names:
            result[name] = _load_protocol_file(name)
        return {
            "wiki_dir": str(Path(WIKI_DIR)),
            "files": result,
            "usage_hint": "Read CLAUDE.md for workflow, schema.md for writing rules, purpose.md for scope",
        }

    if file not in valid_names:
        return {
            "error": f"unknown file: {file}",
            "available": valid_names + ["all"],
        }

    entry = _load_protocol_file(file)
    return {
        "file": file,
        **entry,
    }


@router.post("/init")
def wiki_init(request: Request, force: bool = Query(False, description="overwrite existing files")):
    """Generate default files: protocol files → WIKI_DIR/shared/, skeleton → user dir.

    Protocol files (purpose.md / schema.md / CLAUDE.md): shared across all users.
    Skeleton files (index.md / log.md): per-user initial state maintained by LLM agent.

    Default behavior: skip existing files (protects user customizations).
    force=True: overwrite (use with caution).
    """
    created = []
    skipped = []
    overwritten = []

    shared_dir = Path(WIKI_DIR) / "shared"
    user_dir = _user_wiki_dir(request)

    # protocol files → shared/ (multi-user)
    for name in _DEFAULT_PROTOCOL.keys():
        local_path = shared_dir / f"{name}.md"
        content = _resolve_template(name)

        if not content:
            continue

        if local_path.exists():
            if not force:
                skipped.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))
                continue
            overwritten.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))
        else:
            created.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

    # skeleton files → user dir
    for name, default_content in _DEFAULT_SKELETON.items():
        local_path = user_dir / f"{name}.md"
        content = _resolve_template(name) or default_content

        if not content:
            continue

        if local_path.exists():
            if not force:
                skipped.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))
                continue
            overwritten.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))
        else:
            created.append(str(local_path.relative_to(Path(WIKI_DIR)).as_posix()))

        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content, encoding="utf-8")

    return {
        "wiki_dir": str(Path(WIKI_DIR)),
        "created": created,
        "skipped": skipped,
        "overwritten": overwritten,
        "hint": "Protocol files are shared; skeleton files are per-user. Use force=true to overwrite.",
    }


@router.post("/preview")
def wiki_preview(payload: dict = Body(...), request: Request = None):
    """Diff preview before writing. Does not modify any files.

    Body: {"topic": "notes/topic-name", "content": "---\\n...\\n---\\nbody"}
    """
    topic = payload.get("topic", "")
    new_content = payload.get("content", "")
    if not topic or new_content is None:
        raise HTTPException(400, "requires topic and content fields")

    wiki_root = _user_wiki_dir(request)
    path = _abs_topic_path(topic, request)
    exists = path.exists()
    old_content = path.read_text(errors="replace") if exists else ""

    diff = _diff_preview(old_content, new_content)

    return {
        "topic": path.relative_to(wiki_root).as_posix() if exists else _safe_topic(topic),
        "exists": exists,
        "old_size": len(old_content),
        "new_size": len(new_content),
        "added_lines": diff["added_lines"],
        "removed_lines": diff["removed_lines"],
        "unified_diff": diff["unified_diff"],
        "message": "Confirm with confirm=true via POST /wiki/page",
    }


# ============== POST endpoints ==============

@router.post("/page")
def wiki_write(payload: dict = Body(...), request: Request = None):
    """Create or update a wiki page.

    Body: {
        "topic": "notes/topic-name",
        "content": "---\\n...\\n---\\nbody",
        "source_chunks": ["path/file.pdf_42"],  # optional
        "tags": ["Deep Learning", "Parallax"],   # optional, auto-normalized
        "confirm": false                        # must be true to persist, default preview
    }
    """
    topic = payload.get("topic", "")
    new_content = payload.get("content", "")
    source_chunks = payload.get("source_chunks", [])
    raw_tags = payload.get("tags", [])
    confirm = payload.get("confirm", False)

    # tag normalization (preflight, regardless of confirm)
    norm_tags = _normalize_tags(raw_tags) if isinstance(raw_tags, list) else []

    if not topic or new_content is None:
        raise HTTPException(400, "requires topic and content fields")
    if not isinstance(source_chunks, list):
        raise HTTPException(400, "source_chunks must be a list")

    wiki_root = _user_wiki_dir(request)
    path = _abs_topic_path(topic, request)

    if not confirm:
        # preview mode
        exists = path.exists()
        old_content = path.read_text(errors="replace") if exists else ""
        diff = _diff_preview(old_content, new_content)
        return {
            "preview": True,
            "topic": path.relative_to(wiki_root).as_posix(),
            "exists": exists,
            "old_size": len(old_content),
            "new_size": len(new_content),
            "added_lines": diff["added_lines"],
            "removed_lines": diff["removed_lines"],
            "unified_diff": diff["unified_diff"],
            "tags_normalized": norm_tags,
            "tags_raw": raw_tags if isinstance(raw_tags, list) else [],
            "message": "preview mode, not written. Add confirm=true to persist",
        }

    # persist: lock → write → update cache
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")

    # if tags provided, inject them into frontmatter
    # (ensures LLM-supplied .md content has correct tags, avoids format errors)
    write_content = new_content
    if norm_tags:
        write_content = _inject_tags_into_frontmatter(new_content, norm_tags)

    try:
        with open(lock_path, "w") as lf:
            _lock_file(lf)
            try:
                path.write_text(write_content, encoding="utf-8")
                logger.info(f"wiki write: {path} ({len(write_content)} bytes, tags={norm_tags})")
            except Exception as e:
                logger.exception("wiki write failed")
                raise HTTPException(500, f"write failed: {e}")

        # update cache
        if source_chunks and path.exists():
            try:
                hashes = load_hashes()
                wiki_state = hashes.get("wiki_state", {})
                if not isinstance(wiki_state, dict):
                    wiki_state = {}
                st = path.stat()
                with open(path, "rb") as f:
                    h = file_hash(f.read())
                wiki_state[path.relative_to(wiki_root).as_posix()] = {
                    "mtime": st.st_mtime,
                    "size": st.st_size,
                    "hash": h,
                    "last_wiki_update": _now_iso(),
                    "source_chunks": source_chunks,
                }
                hashes["wiki_state"] = wiki_state
                hashes["_version"] = hashes.get("_version", 1)
                save_hashes(hashes)
            except Exception:
                logger.exception("cache update failed (file written successfully)")
    finally:
        if lock_path.exists():
            lock_path.unlink()

    return {
        "preview": False,
        "status": "ok",
        "topic": path.relative_to(wiki_root).as_posix(),
        "size": path.stat().st_size,
        "tags": norm_tags,
    }


@router.post("/page/delete")
def wiki_delete(payload: dict = Body(...), request: Request = None):
    """Delete a wiki page. Requires confirm=true."""
    topic = payload.get("topic", "")
    confirm = payload.get("confirm", False)

    if not topic:
        raise HTTPException(400, "requires topic field")

    wiki_root = _user_wiki_dir(request)
    path = _abs_topic_path(topic, request)
    if not path.exists():
        raise HTTPException(404, f"topic not found: {topic}")

    rel = path.relative_to(wiki_root).as_posix()

    if not confirm:
        return {
            "preview": True,
            "topic": rel,
            "size": path.stat().st_size,
            "message": "preview mode, not deleted. Add confirm=true to persist",
        }

    try:
        path.unlink()
        # remove from cache
        hashes = load_hashes()
        wiki_state = hashes.get("wiki_state", {})
        if isinstance(wiki_state, dict) and rel in wiki_state:
            wiki_state.pop(rel, None)
            hashes["wiki_state"] = wiki_state
            save_hashes(hashes)
        logger.info(f"wiki delete: {path}")
    except Exception as e:
        logger.exception("wiki delete failed")
        raise HTTPException(500, f"delete failed: {e}")

    return {"status": "ok", "deleted": rel}


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")
