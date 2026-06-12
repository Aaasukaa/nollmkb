#!/usr/bin/env python3
"""FastAPI + ChromaDB + sentence-transformers BGE-M3 RAG + wiki service"""
import socket
import sys

from config import HOST, PORT
from logging_config import configure_logging


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


if __name__ == "__main__":
    if _port_in_use(HOST, PORT):
        sys.stderr.write(f"Error: port {PORT} is already in use — nollmkb may already be running.\n")
        sys.stderr.write("Stop it first, or use a different port.\n")
        sys.exit(1)

# ---- heavy imports below ----
import secrets
import hashlib
import time
from pathlib import Path

_sessions: dict[str, dict] = {}
_users_cache: dict[str, str] = {}  # token_hash → username, loaded once on startup
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from routes import router
from wiki_server import router as wiki_router
from indexer import get_collection, do_scan
from bm25 import rebuild_bm25
from config import DEVICE

app = FastAPI(title="nollmkb")


def _load_users() -> dict[str, str]:
    """Load users.toml [users] into {token_hash: username}. Returns {} if file missing or empty."""
    import tomllib
    from config import USERS_FILE as _USERS_FILE
    try:
        with open(_USERS_FILE, "rb") as f:
            raw = tomllib.load(f).get("users", {})
        # invert: users.toml stores {user: hash}, we need {hash: user}
        return {v: k for k, v in raw.items()}
    except Exception:
        return {}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # paths that never require auth
    if request.url.path in ("/auth/login", "/favicon.ico") or request.url.path.startswith("/ui/"):
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ")

    # Channel 1: session token (WebUI users, 24h)
    if token and token in _sessions:
        session = _sessions[token]
        if time.time() < session["expires"]:
            session["expires"] = time.time() + 86400
            request.state.user = session["user"]
            return await call_next(request)
        del _sessions[token]

    # Channel 2: bearer token (agent / curl)
    if token:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        user = _users_cache.get(token_hash)
        if user:
            request.state.user = user
            return await call_next(request)

    # No auth configured or token invalid
    if not _users_cache:
        request.state.user = ""
        return await call_next(request)

    return JSONResponse({"error": "unauthorized"}, status_code=401)


app.include_router(router)
app.include_router(wiki_router)

from fastapi.staticfiles import StaticFiles
import os as _os

_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_static_dir):
    app.mount("/ui", StaticFiles(directory=_static_dir, html=True), name="ui")


@app.post("/auth/login")
async def auth_login(payload: dict):
    bearer = payload.get("token", "")
    if not bearer:
        return JSONResponse({"error": "token required"}, 400)

    # verify token against users.toml
    h = hashlib.sha256(bearer.encode()).hexdigest()
    user = _users_cache.get(h)
    if not user:
        return JSONResponse({"error": "invalid token"}, 401)

    session = secrets.token_urlsafe(32)
    _sessions[session] = {"user": user, "expires": time.time() + 86400}
    return {"token": session, "user": user, "expires_in": 86400}


if __name__ == "__main__":
    import logging
    import torch
    import uvicorn

    log_path = configure_logging()
    logger = logging.getLogger("nollmkb")
    logger.info("log file: %s", log_path)

    _users_cache = _load_users()
    if _users_cache:
        logger.info("users loaded: %s", ", ".join(_users_cache.values()))
    else:
        logger.info("no users configured — auth disabled")

    get_collection()
    total, skipped, _ = do_scan()
    logger.info("startup scan: %d new, %d skipped", total, skipped)
    rebuild_bm25(get_collection())
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    logger.info("BM25 index built, starting uvicorn")
    uvicorn.run(app, host=HOST, port=PORT)
