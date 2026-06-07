#!/usr/bin/env python3
"""FastAPI + ChromaDB + sentence-transformers BGE-M3 RAG + wiki service"""
import socket
import sys

from config import HOST, PORT  # no heavy deps
from logging_config import configure_logging  # no model loading


def _port_in_use(host: str, port: int) -> bool:
    """Check if a service is already listening on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


if __name__ == "__main__":
    if _port_in_use(HOST, PORT):
        sys.stderr.write(f"Error: port {PORT} is already in use — nollmkb may already be running.\n")
        sys.stderr.write("Stop it first, or use a different port.\n")
        sys.exit(1)

# ---- heavy imports below (model loading happens here) ----
import secrets
import hashlib
import time
import secrets as _secrets

_sessions: dict[str, dict] = {}
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routes import router
from wiki_server import router as wiki_router
from indexer import get_collection, do_scan
from bm25 import rebuild_bm25
from config import DEVICE, API_KEY_HASH

app = FastAPI(title="nollmkb")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # paths that never require auth
    if request.url.path in ("/auth/login", "/favicon.ico") or request.url.path.startswith("/ui/"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")

    token = auth.removeprefix("Bearer ")
    if token and token in _sessions:
        session = _sessions[token]
        if time.time() < session["expires"]:
            session["expires"] = time.time() + 86400
            request.state.user = session["user"]
            return await call_next(request)
        del _sessions[token]

    if API_KEY_HASH:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if not secrets.compare_digest(token_hash, API_KEY_HASH):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        request.state.user = ""
        return await call_next(request)

    request.state.user = ""
    return await call_next(request)


app.include_router(router)
app.include_router(wiki_router)

from fastapi.staticfiles import StaticFiles
import os as _os

_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_static_dir):
    app.mount("/ui", StaticFiles(directory=_static_dir, html=True), name="ui")

from config import USERS_FILE


@app.post("/auth/login")
async def auth_login(payload: dict):
    import tomllib
    user = payload.get("user", "")
    password = payload.get("password", "")
    if not user or not password:
        return JSONResponse({"error": "user and password required"}, 400)

    try:
        with open(USERS_FILE, "rb") as f:
            users = tomllib.load(f).get("users", {})
    except Exception:
        return JSONResponse({"error": "user config not found"}, 500)

    expected_hash = users.get(user)
    if not expected_hash:
        return JSONResponse({"error": "invalid credentials"}, 401)

    pw_hash = hashlib.sha256(password.encode()).hexdigest()
    if not secrets.compare_digest(pw_hash, expected_hash):
        return JSONResponse({"error": "invalid credentials"}, 401)

    token = _secrets.token_urlsafe(32)
    _sessions[token] = {
        "user": user,
        "expires": time.time() + 86400,
    }
    return {"token": token, "user": user, "expires_in": 86400}

if __name__ == "__main__":
    import logging
    import torch
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
