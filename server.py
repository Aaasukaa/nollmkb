#!/usr/bin/env python3
"""FastAPI + ChromaDB + sentence-transformers BGE-M3 RAG + wiki service"""
import secrets
import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routes import router
from wiki_server import router as wiki_router
from indexer import get_collection, do_scan
from bm25 import rebuild_bm25
from logging_config import configure_logging
from config import DEVICE, HOST, PORT, API_KEY_HASH

app = FastAPI(title="nollmkb")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if API_KEY_HASH:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ")
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if not secrets.compare_digest(token_hash, API_KEY_HASH):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(router)
app.include_router(wiki_router)

if __name__ == "__main__":
    import torch
    import logging
    import uvicorn

    log_path = configure_logging()
    logger = logging.getLogger("nollmkb")
    logger.info("log file: %s", log_path)

    get_collection()
    total, skipped, _ = do_scan()
    logger.info("startup scan: %d new, %d skipped", total, skipped)
    rebuild_bm25(get_collection())
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    logger.info("BM25 index built, starting uvicorn")
    uvicorn.run(app, host=HOST, port=PORT)
