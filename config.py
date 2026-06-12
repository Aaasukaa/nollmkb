"""nollmkb configuration.

Path priority: env var > relative default.

Env vars:
- NOLLMKB_DOCS_DIR:   raw document directory
- NOLLMKB_KB_DIR:     ChromaDB storage directory
- NOLLMKB_HASH_FILE:  incremental index cache
- NOLLMKB_WIKI_DIR:   wiki notes root directory
- NOLLMKB_COLLECTION: ChromaDB collection name (default nollmkb)

Default layout: nollmkb/ is sibling to inputs/, chromadb_storage/, wiki/
(common monorepo pattern).
   parent/
   ├── nollmkb/             ← repo root
   ├── inputs/              ← default DOCS_DIR
   ├── chromadb_storage/    ← default KB_DIR
   └── wiki/                ← default WIKI_DIR

To customize: copy .env.example to .env and edit paths, or:
   export NOLLMKB_DOCS_DIR=/path/to/inputs
   export NOLLMKB_KB_DIR=/path/to/chroma
   export NOLLMKB_WIKI_DIR=/path/to/wiki
   python server.py
"""

import os
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from .env into os.environ.

    Only sets keys not already present in os.environ,
    so shell exports take priority over .env file.
    """
    env_path = Path(__file__).resolve().parent / path
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip().lstrip("#").strip()
        if not k or k in os.environ:
            continue
        v = v.strip().strip('"').strip("'")
        os.environ[k] = v


_load_dotenv()

# parent dir of nollmkb/ (where inputs/, chromadb_storage/, wiki/ live)
_DEFAULT_PARENT = str(Path(__file__).resolve().parent.parent)


def _resolve_path(env_var: str, default: str) -> str:
    """Priority: env var > hardcoded default."""
    return os.environ.get(env_var, default)


# --- path config (env override) ---
DOCS_DIR = _resolve_path("NOLLMKB_DOCS_DIR", f"{_DEFAULT_PARENT}/inputs")
KB_DIR = _resolve_path("NOLLMKB_KB_DIR", f"{_DEFAULT_PARENT}/chromadb_storage")
HASH_FILE = _resolve_path("NOLLMKB_HASH_FILE", f"{KB_DIR}/file_hashes.json")
WIKI_DIR = _resolve_path("NOLLMKB_WIKI_DIR", f"{_DEFAULT_PARENT}/wiki")

# --- ChromaDB collection name (env override) ---
COLLECTION_NAME = _resolve_path("NOLLMKB_COLLECTION", "nollmkb")

# --- user management ---
USERS_FILE = _resolve_path("NOLLMKB_USERS_FILE", f"{Path(__file__).resolve().parent}/auth/users.toml")

# --- model / chunking config (constants, no paths) ---
HASH_VERSION = 3
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 100
MIN_CHUNK = 200
MAX_CHUNK = CHUNK_SIZE * 2
EMBED_MODEL = "BAAI/bge-m3"
EMBED_DIM = 1024
EMBED_BATCH = 128
TOP_K = 5
DEVICE = _resolve_path("NOLLMKB_DEVICE", "cuda")  # "cuda" or "cpu"
HOST = _resolve_path("NOLLMKB_HOST", "127.0.0.1")
PORT = 8765

SCAN_STATUS = {"running": False, "current": 0, "total": 0, "current_file": "", "last_result": ""}
