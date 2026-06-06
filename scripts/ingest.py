"""Wiki ingest tool.

Reuses nollmkb hash_db for three-tier incremental caching:
- L1: mtime + size fast path
- L2: hash comparison (touched but unchanged)
- L3: content actually changed, return False to trigger rewrite

Usage:
    from scripts.ingest import wiki_should_skip, wiki_mark_written, wiki_record_source
    if wiki_should_skip(source_path, topic):
        return  # source unchanged, skip
    # ... LLM writes wiki page ...
    wiki_mark_written(source_path, topic, source_chunks)
"""

import os
import sys
from pathlib import Path

# nollmkb root dir (this file = nollmkb/scripts/ingest.py -> parent = nollmkb/)
_NOLL_ROOT = Path(__file__).resolve().parent.parent
if str(_NOLL_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOLL_ROOT))

from config import WIKI_DIR
from hash_db import load_hashes, save_hashes, file_hash  # noqa: E402

WIKI_KEY = "wiki_state"


def _wiki_state():
    """Return wiki_state section from hashes, create empty dict if missing."""
    hashes = load_hashes()
    if WIKI_KEY not in hashes or not isinstance(hashes.get(WIKI_KEY), dict):
        hashes[WIKI_KEY] = {}
        save_hashes(hashes)
    return hashes[WIKI_KEY]


def _save_wiki_state(wiki_state):
    """Persist wiki_state to hashes top-level key."""
    hashes = load_hashes()
    hashes[WIKI_KEY] = wiki_state
    hashes["_version"] = hashes.get("_version", 1)
    save_hashes(hashes)


def wiki_should_skip(source_path: str, topic: str) -> bool:
    """Check whether source_path's wiki page for topic needs rewriting.

    Reuses nollmkb three-tier caching:
    - L1: mtime+size unchanged -> skip
    - L2: hash unchanged -> skip (update mtime/size)
    - L3: hash changed -> don't skip (needs rewrite)

    Returns:
        True: source unchanged, skip
        False: source changed or first write, needs rewrite
    """
    if not os.path.exists(source_path):
        return False  # source file missing, let caller decide

    wiki_state = _wiki_state()
    cached = wiki_state.get(topic)
    if cached is None:
        return False  # first write

    st = os.stat(source_path)

    # L1: mtime+size fast path
    if cached.get("mtime") == st.st_mtime and cached.get("size") == st.st_size:
        return True

    # L2: hash comparison
    with open(source_path, "rb") as f:
        h = file_hash(f.read())
    if cached.get("hash") == h:
        # content unchanged, just update mtime/size
        cached["mtime"] = st.st_mtime
        cached["size"] = st.st_size
        wiki_state[topic] = cached
        _save_wiki_state(wiki_state)
        return True

    # L3: content actually changed
    return False


def wiki_mark_written(source_path: str, topic: str, source_chunks: list[str]) -> None:
    """Call after LLM writes a wiki page to record cache entry.

    Args:
        source_path: source file path
        topic: wiki page name (relative path under wiki/, e.g. "notes/topic.md")
        source_chunks: list of referenced nollmkb chunk IDs
    """
    st = os.stat(source_path)
    with open(source_path, "rb") as f:
        h = file_hash(f.read())

    wiki_state = _wiki_state()
    wiki_state[topic] = {
        "mtime": st.st_mtime,
        "size": st.st_size,
        "hash": h,
        "last_wiki_update": _now_iso(),
        "source_chunks": source_chunks,
    }
    _save_wiki_state(wiki_state)


def wiki_record_source(source_path: str, topic: str) -> None:
    """Record source reference without writing wiki page (for provenance tracking)."""
    if not os.path.exists(source_path):
        return
    wiki_state = _wiki_state()
    if topic in wiki_state:
        return  # already recorded

    st = os.stat(source_path)
    with open(source_path, "rb") as f:
        h = file_hash(f.read())

    wiki_state[topic] = {
        "mtime": st.st_mtime,
        "size": st.st_size,
        "hash": h,
        "last_wiki_update": _now_iso(),
        "source_chunks": [],
    }
    _save_wiki_state(wiki_state)


def wiki_get_state(topic: str = None) -> dict:
    """Look up wiki_state. topic=None returns all."""
    wiki_state = _wiki_state()
    if topic is None:
        return wiki_state
    return wiki_state.get(topic, {})


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 ingest.py <source_path> <topic>")
        print("Example: python3 ingest.py /path/to/docs/paper.pdf notes/topic.md")
        sys.exit(1)

    src, topic = sys.argv[1], sys.argv[2]
    skip = wiki_should_skip(src, topic)
    print(f"source: {src}")
    print(f"topic:  {topic}")
    print(f"skip:   {skip}  ({'cached, skip' if skip else 'needs rewrite'})")
