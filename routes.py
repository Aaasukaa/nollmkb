import os
import asyncio
import time
import hashlib
import contextlib
import logging
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse

from models import QueryRequest
from reranker import get_reranker
from bm25 import _bm25, _tokenize, rebuild_bm25, remove_from_bm25, reset_bm25, _ensure_bm25
from hash_db import load_hashes, save_hashes, file_hash
from parsers import EXTRACTORS, TEXT_EXTS
from config import DOCS_DIR, HASH_VERSION, COLLECTION_NAME
from indexer import get_collection, _index_file, do_scan, client, reset_collection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/")
def root():
    """Root endpoint: list all APIs (for remote agent onboarding).

    Remote agent should first GET / to see endpoint list,
    then GET /wiki/protocol to read the protocol.
    """
    return {
        "service": "TinyKB / nollmkb",
        "version": "1.0",
        "endpoints": {
            "rag": [
                {"method": "GET",  "path": "/health",    "desc": "health check"},
                {"method": "POST", "path": "/query",     "desc": "RAG search (vector + BM25 + rerank)"},
                {"method": "POST", "path": "/upload",    "desc": "upload documents"},
                {"method": "POST", "path": "/scan",      "desc": "batch scan and index"},
                {"method": "GET",  "path": "/documents", "desc": "list indexed documents"},
                {"method": "DELETE", "path": "/documents?source=X", "desc": "delete document (requires ?source)"},
            ],
            "wiki": [
                {"method": "GET",  "path": "/wiki/protocol", "desc": "required: returns protocol (CLAUDE.md + schema.md + purpose.md); falls back to builtin if local file missing"},
                {"method": "GET",  "path": "/wiki/list",     "desc": "list all topics (response includes protocol_endpoint + init_endpoint hint)"},
                {"method": "GET",  "path": "/wiki/page?topic=X", "desc": "read full page"},
                {"method": "GET",  "path": "/wiki/search?q=X", "desc": "keyword search"},
                {"method": "GET",  "path": "/wiki/graph",   "desc": "wikilink adjacency graph"},
                {"method": "GET",  "path": "/wiki/tags",    "desc": "all tags with counts (check before writing new page)"},
                {"method": "POST", "path": "/wiki/init?force=BOOL", "desc": "generate default protocol + skeleton files (skips existing)"},
                {"method": "POST", "path": "/wiki/preview", "desc": "diff preview before writing"},
                {"method": "POST", "path": "/wiki/page",    "desc": "create/update (confirm=true to persist)"},
                {"method": "POST", "path": "/wiki/page/delete", "desc": "delete (confirm=true to persist)"},
            ],
        },
        "agent_workflow": [
            "1. GET / → see all endpoints",
            "2. GET /wiki/protocol → read protocol (CLAUDE.md + schema.md + purpose.md; builtin fallback)",
            "3. GET /health → check service is up",
            "4. POST /query → search raw sources (RAG)",
            "5. GET /wiki/tags → reuse existing tags",
            "6. POST /wiki/preview → diff preview before writing",
            "7. POST /wiki/page confirm=true → persist (tags auto-normalized)",
        ],
    }


@router.get("/health")
def health():
    try:
        col = get_collection()
        return {"status": "ok", "chunks": col.count()}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, 500)


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    col = get_collection()
    hashes = load_hashes()
    results: list[dict] = []
    ok_count, skipped, failed = 0, 0, 0

    if hashes.get("_version") != HASH_VERSION:
        hashes.clear()

    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in EXTRACTORS and ext not in TEXT_EXTS:
            results.append({"file": f.filename, "status": "skipped", "reason": f"unsupported: {ext}"})
            failed += 1
            continue
        try:
            raw = await f.read()
            h = file_hash(raw)

            old = hashes.get(f.filename)
            if isinstance(old, str) and old == h:
                results.append({"file": f.filename, "status": "ok", "chunks": 0, "note": "unchanged"})
                skipped += 1
                continue
            if isinstance(old, dict) and old.get("hash") == h:
                results.append({"file": f.filename, "status": "ok", "chunks": 0, "note": "unchanged"})
                skipped += 1
                continue

            os.makedirs(DOCS_DIR, exist_ok=True)
            safe_name = os.path.basename(f.filename)
            save_path = os.path.join(DOCS_DIR, safe_name)
            with open(save_path, "wb") as fh:
                fh.write(raw)

            entry, cnt = _index_file(col, save_path, f.filename, ext, h)
            if entry:
                hashes[f.filename] = entry
                results.append({"file": f.filename, "status": "ok", "chunks": cnt})
                ok_count += 1
            else:
                results.append({"file": f.filename, "status": "failed", "reason": "index returned no entry"})
                failed += 1
        except Exception as e:
            logger.exception("upload failed: %s", f.filename)
            results.append({"file": f.filename, "status": "failed", "reason": str(e)})
            failed += 1

    hashes["_version"] = HASH_VERSION
    save_hashes(hashes)
    if ok_count:
        rebuild_bm25(col)
    return {
        "status": "ok" if failed == 0 else "partial",
        "files_processed": ok_count,
        "files_skipped": skipped,
        "files_failed": failed,
        "total_chunks": col.count(),
        "results": results,
    }


@router.post("/scan")
def scan_api():
    total, skipped, col = do_scan()
    rebuild_bm25(col)
    return {"status": "ok", "files_processed": total, "files_skipped": skipped, "total_chunks": col.count()}


def _do_query(req: QueryRequest) -> dict:
    t0 = time.perf_counter()
    col = get_collection()
    n = min(req.top_k, 20)

    where = None
    if req.filters:
        if len(req.filters) == 1:
            where = dict(req.filters)
        else:
            where = {"$and": [{k: v} for k, v in req.filters.items()]}

    results = col.query(query_texts=[req.text], n_results=n * 3, where=where)
    candidates = []
    seen = set()

    def _add(doc, source, chunk, score):
        key = hashlib.sha256(doc[:200].encode()).hexdigest()
        if key in seen:
            return
        seen.add(key)
        candidates.append({"source": source, "chunk": chunk, "score": score, "text": doc})

    for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0]):
        if req.dir and not meta["source"].startswith(req.dir + "/"):
            continue
        _add(doc, meta["source"], meta["chunk"], round(1 - dist, 4))

    if req.bm25:
        _ensure_bm25()
    state = _bm25
    if state is not None:
        bm25_idx, bm25_meta, bm25_texts = state
        terms = _tokenize(req.text)
        bm_results = list(bm25_idx.search(terms, n * 2))
        max_bm = bm_results[0][1] if bm_results else 1.0
        for idx, bm_score in bm_results:
            s, c, ext_val, dir_val = bm25_meta[idx]
            if req.dir and not s.startswith(req.dir + "/"):
                continue
            if req.filters:
                if "ext" in req.filters and req.filters["ext"] != ext_val:
                    continue
                if "dir" in req.filters and req.filters["dir"] != dir_val:
                    continue
                if "source" in req.filters and req.filters["source"] != s:
                    continue
            _add(bm25_texts[idx], s, c, round(bm_score / max_bm, 4))

    if req.rerank and candidates:
        reranker = get_reranker()
        pairs = [[req.text, c["text"][:1500]] for c in candidates]
        scores = reranker.predict(pairs)
        for c, s in zip(candidates, scores):
            c["score"] = round(float(s), 4)

    candidates.sort(key=lambda x: x["score"], reverse=True)

    hits = []
    for c in candidates:
        if c["score"] < req.min_score:
            continue
        hits.append(c)
        if len(hits) >= n:
            break

    if req.context:
        ids = list(dict.fromkeys(
            [f"{h['source']}_{h['chunk']-1}" for h in hits] +
            [f"{h['source']}_{h['chunk']+1}" for h in hits]
        ))
        ctx = col.get(ids=ids, include=["documents"])
        ctx_map = dict(zip(ctx["ids"], ctx["documents"] or []))
        for h in hits:
            h["context_before"] = ctx_map.get(f"{h['source']}_{h['chunk']-1}", "")
            h["context_after"] = ctx_map.get(f"{h['source']}_{h['chunk']+1}", "")

    elapsed = round((time.perf_counter() - t0) * 1000)
    return {"query": req.text, "results": hits, "elapsed_ms": elapsed}


@router.post("/query")
async def query(req: QueryRequest):
    return await asyncio.to_thread(_do_query, req)


@router.get("/documents")
def list_documents():
    col = get_collection()
    results = col.get()
    metadatas = results.get("metadatas") or []
    files = {}
    exts = {}
    dirs = {}
    for meta in metadatas:
        src = meta["source"]
        files[src] = files.get(src, 0) + 1
        if src not in exts:
            exts[src] = meta.get("ext", "")
            dirs[src] = meta.get("dir", "")
    return {"documents": [{"source": k, "chunks": v, "ext": exts[k], "dir": dirs[k]} for k, v in sorted(files.items())]}


@router.delete("/documents")
def delete_documents(source: str | None = None, confirm_all: bool = False):
    col = get_collection()
    hashes = load_hashes()

    if source is not None and not source.strip():
        return JSONResponse(
            {"error": "source cannot be empty; omit param and pass ?confirm_all=true to delete everything"},
            400,
        )

    if source is None:
        if not confirm_all:
            return JSONResponse(
                {"error": "deleting all documents requires ?confirm_all=true"},
                400,
            )
        with contextlib.suppress(Exception):
            client.delete_collection(COLLECTION_NAME)
        reset_collection()
        hashes.clear()
        col = get_collection()
        reset_bm25()
        msg = "All documents deleted"
    else:
        ids = col.get(where={"source": source})["ids"]
        if ids:
            col.delete(ids=ids)
        hashes.pop(source, None)
        remove_from_bm25(source)
        msg = f"Deleted: {source}"

    hashes["_version"] = HASH_VERSION
    save_hashes(hashes)
    return {"status": "ok", "message": msg, "total_chunks": col.count()}
