import os
import time
import contextlib
import threading
import logging
import chromadb
from config import DOCS_DIR, KB_DIR, HASH_VERSION, EMBED_BATCH
from embedding import embed_fn
from parsers import extract, EXTRACTORS, TEXT_EXTS
from chunker import chunk_blocks, chunk_text
from hash_db import load_hashes, save_hashes, file_hash
from config import COLLECTION_NAME

logger = logging.getLogger(__name__)

client = chromadb.PersistentClient(path=KB_DIR)
_col = None
_lock = threading.Lock()


def get_collection(name=COLLECTION_NAME):
    global _col
    if _col is None:
        with _lock:
            if _col is None:
                _col = client.create_collection(name, embedding_function=embed_fn, get_or_create=True, metadata={"hnsw:space": "cosine"})
    return _col


def _index_file(col, fpath, key, ext, h):
    text = extract(fpath, ext)
    if text is None:
        return None, 0
    if isinstance(text, list):
        if not text:
            return None, 0
        chunks = chunk_blocks(text)
    else:
        if not text.strip():
            return None, 0
        chunks = chunk_text(text)

    old_ids = col.get(where={"source": key})["ids"]
    if old_ids:
        col.delete(ids=old_ids)

    dir_name = key.split(os.sep)[0] if os.sep in key else ""
    for i in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[i:i+EMBED_BATCH]
        col.add(
            documents=batch,
            metadatas=[{"source": key, "chunk": i+j, "path": fpath, "ext": ext, "dir": dir_name} for j in range(len(batch))],
            ids=[f"{key}_{i+j}" for j in range(len(batch))]
        )
    st = os.stat(fpath)
    return {"mtime": st.st_mtime, "size": st.st_size, "hash": h}, len(chunks)


def _prepare_chunks(fpath, key, ext):
    col = get_collection()
    text = extract(fpath, ext)
    if text is None:
        return None, 0
    if isinstance(text, list):
        if not text:
            return None, 0
        chunks = chunk_blocks(text)
    else:
        if not text.strip():
            return None, 0
        chunks = chunk_text(text)

    old_ids = col.get(where={"source": key})["ids"]
    if old_ids:
        col.delete(ids=old_ids)
    return chunks, fpath


def _flush_chunks(col, pending):
    for i in range(0, len(pending), EMBED_BATCH):
        batch = pending[i:i+EMBED_BATCH]
        col.add(
            documents=[b[0] for b in batch],
            metadatas=[b[1] for b in batch],
            ids=[b[2] for b in batch]
        )


def do_scan():
    t0 = time.perf_counter()
    col = get_collection()
    hashes = load_hashes()

    if hashes.get("_version") != HASH_VERSION:
        logger.info("Cache version changed, rebuilding...")
        hashes.clear()
        with contextlib.suppress(Exception):
            client.delete_collection(COLLECTION_NAME)
        reset_collection()
        col = get_collection()

    all_files = []
    for root, _, files in os.walk(DOCS_DIR):
        for fname in sorted(files):
            ext = os.path.splitext(fname)[1].lower()
            if not fname.startswith(".") and not fname.startswith("~$") and (ext in EXTRACTORS or ext in TEXT_EXTS):
                all_files.append(os.path.join(root, fname))

    total, skipped = 0, 0
    pending = []

    for idx, fpath in enumerate(all_files, 1):
        key = os.path.relpath(fpath, DOCS_DIR)
        from config import SCAN_STATUS
        SCAN_STATUS["current"] = idx
        SCAN_STATUS["total"] = len(all_files)
        SCAN_STATUS["current_file"] = key
        ext = os.path.splitext(key)[1].lower()
        pct = f"{idx}/{len(all_files)}"
        st = os.stat(fpath)
        cache = hashes.get(key)

        top_dir = key.split(os.sep)[0] if os.sep in key else ""
        def _index(chunks, h):
            nonlocal total
            for i, c in enumerate(chunks):
                pending.append((c,
                    {"source": key, "chunk": i, "path": fpath, "ext": ext, "dir": top_dir},
                    f"{key}_{i}"))
            if len(pending) >= EMBED_BATCH:
                _flush_chunks(col, pending)
                pending.clear()
            st2 = os.stat(fpath)
            hashes[key] = {"mtime": st2.st_mtime, "size": st2.st_size, "hash": h}
            total += 1
            return len(chunks)

        if isinstance(cache, str):
            raw = open(fpath, "rb").read()
            h = file_hash(raw)
            if h == cache:
                hashes[key] = {"mtime": st.st_mtime, "size": st.st_size, "hash": h}
                skipped += 1
                logger.info("[%s] SKIP %s (cached)", pct, key)
            else:
                chunks, _ = _prepare_chunks(fpath, key, ext)
                if chunks:
                    cnt = _index(chunks, h)
                    logger.info("[%s] OK  %s (%d chunks)", pct, key, cnt)
                else:
                    skipped += 1
                    logger.warning("[%s] FAIL %s (empty or parse error)", pct, key)
            continue

        if isinstance(cache, dict) and cache.get("mtime") == st.st_mtime and cache.get("size") == st.st_size:
            skipped += 1
            logger.info("[%s] SKIP %s (fast)", pct, key)
            continue

        if isinstance(cache, dict):
            raw = open(fpath, "rb").read()
            h = file_hash(raw)
            if cache.get("hash") == h:
                hashes[key]["mtime"] = st.st_mtime
                hashes[key]["size"] = st.st_size
                skipped += 1
                logger.info("[%s] SKIP %s (touched)", pct, key)
                continue
            chunks, _ = _prepare_chunks(fpath, key, ext)
            if chunks:
                cnt = _index(chunks, h)
                logger.info("[%s] OK  %s (%d chunks)", pct, key, cnt)
            else:
                skipped += 1
                logger.warning("[%s] FAIL %s (empty or parse error)", pct, key)
            continue

        raw = open(fpath, "rb").read()
        h = file_hash(raw)
        chunks, _ = _prepare_chunks(fpath, key, ext)
        if chunks:
            cnt = _index(chunks, h)
            logger.info("[%s] OK  %s (%d chunks)", pct, key, cnt)
        else:
            skipped += 1
            logger.warning("[%s] FAIL %s (empty or parse error)", pct, key)

    if pending:
        _flush_chunks(col, pending)

    hashes["_version"] = HASH_VERSION
    save_hashes(hashes)
    elapsed = round(time.perf_counter() - t0, 1)
    logger.info("Done: %d new, %d skipped (%.1fs)", total, skipped, elapsed)
    return total, skipped, col


def reset_collection():
    """Clear cached collection so get_collection() re-creates it."""
    global _col
    _col = None
