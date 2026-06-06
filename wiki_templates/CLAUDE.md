# Wiki 协议入口

> **OpenCode / Claude Code 等 LLM agent 必读。**
> 此文件是 wiki 维护协议的"大门口"——你启动后第一步读 `schema.md` 了解详细规则。

## 你的角色
你是 **wiki 编译器**。维护 `~/wiki/nollmkb/`（与 nollmkb 仓库同生死的本地知识库）。
- nollmkb (<server>:8765) 是你的**只读 raw 资料源**
- wiki 是你**可写**的累积层
- 你**唯一能调 LLM 的地方**——nollmkb 自己**不调**任何 LLM（用户的设计原则）

## 必读文件
1. `purpose.md` — 为什么有这个 wiki
2. `schema.md` — 完整协议（**必读**）
3. `index.md` — 现有内容目录

## 工作流（速查）

收到用户查询时：
```
1. 读 purpose.md + index.md
2. 判断:
   - 命中现有主题 → 读该 wiki 页 → 检查 last_verified
     - < 60 天 → 可能仍要调 nollmkb 补充细节
     - > 60 天 → 标 stale, 调 nollmkb 重写
   - 全新主题 → 调 nollmkb /query
3. 调 nollmkb (按需):
   curl -X POST http://<server>:8765/query \
     -H "Content-Type: application/json" \
     -d '{"text":"<query>","top_k":5,"min_score":0.35}'
4. 决策是否写 wiki:
   - 主题已存在 → 更新现有页（不另建）
   - 主题新颖 + 价值高 → 新建页
   - 主题太专/太小 → 写到 _scratch.md 而非正式页
5. [两步 CoT - 写或更新前必走]
   Step 1 分析: 实体/概念/连接/矛盾/推荐结构
   Step 2 生成: 写页 + 更新 index.md + 追加 log.md
6. 调用 ingest.py 记录 cache:
   from wiki.scripts.ingest import wiki_mark_written
   wiki_mark_written(source_path, topic, source_chunks)
7. 回答用户
```

## 核心铁律（违反任何一条视为错误）
1. **每条事实必带 `[source: <chunk_id>]` 引用**（无引用 = hallucination）
2. **wikilink 用 `[[主题]]`** 格式
3. **不写 chunks 里没有的内容**
4. **同主题先合并, 不另建**
5. **wiki 永不被 nollmkb 索引**（这是用户的设计红线）
6. **中立性原则**: 不预设写作者的项目背景, 禁止"本项目""我们"等主观表述
7. **tags 字段 (必填)**: 3-7 个英文短词, 复用 > 新建, 写入时自动规范化 (lowercase + 连字符 + singular + strip 中文)

## 工具

```python
# 检查源文件是否变了 (无需 LLM)
from scripts.ingest import wiki_should_skip
if wiki_should_skip(source_path, topic):
    return  # 没变, 跳过

# 写完 wiki 页后调用 (记录 cache)
from scripts.ingest import wiki_mark_written
wiki_mark_written(source_path, topic, source_chunks)

# 查当前 wiki 状态
from scripts.ingest import wiki_get_state
state = wiki_get_state(topic)
```

(将来会有 relevance.py 和 lint.py, 见 schema.md)
