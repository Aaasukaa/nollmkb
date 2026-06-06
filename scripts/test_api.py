"""Wiki HTTP API end-to-end test.

Usage: run from nollmkb repo root
    uv run python3 scripts/test_api.py [base_url]

Default base_url = http://127.0.0.1:8765
"""

import sys
import json
import os
import requests
from pathlib import Path

# add nollmkb root to sys.path
_NOLL_ROOT = Path(__file__).resolve().parent.parent
if str(_NOLL_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOLL_ROOT))

from config import WIKI_DIR

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
TEST_TOPIC = "test/_test_api.md"

# optional auth: set NOLLMKB_TEST_KEY env to the password if server requires auth
_SESSION = requests.Session()
_TEST_KEY = os.environ.get("NOLLMKB_TEST_KEY", "")
if _TEST_KEY:
    _SESSION.headers["Authorization"] = f"Bearer {_TEST_KEY}"

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  OK  {name}")
        passed += 1
    else:
        print(f"  FAIL {name}: {detail}")
        failed += 1


def expect_status(r, code):
    if r.status_code != code:
        return False, f"got {r.status_code}, expected {code}: {r.text[:200]}"
    return True, ""


def cleanup_test_topic():
    """Remove test file from previous run before starting."""
    test_path = f"{WIKI_DIR}/{TEST_TOPIC}"
    if os.path.exists(test_path):
        os.remove(test_path)
        print(f"  (cleanup: removed existing {test_path})")
    # also clear from cache
    from hash_db import load_hashes, save_hashes
    hashes = load_hashes()
    ws = hashes.get("wiki_state", {})
    if isinstance(ws, dict) and TEST_TOPIC in ws:
        ws.pop(TEST_TOPIC, None)
        hashes["wiki_state"] = ws
        save_hashes(hashes)


print(f"=== Wiki API test ({BASE}) ===\n")

# 0. cleanup
print("[0] Cleanup")
cleanup_test_topic()
print()

# 1. health
print("[1] Health")
r = _SESSION.get(f"{BASE}/health", timeout=10)
ok, _ = expect_status(r, 200)
check("/health returns 200", ok, r.text)

# 1.5 root endpoint (for remote agent onboarding)
print("\n[1.5] Root endpoint GET /")
r = _SESSION.get(f"{BASE}/", timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("/ returns 200", ok, r.text)
check("/ has endpoints.rag", "rag" in data.get("endpoints", {}))
check("/ has endpoints.wiki", "wiki" in data.get("endpoints", {}))
check("/ has agent_workflow", "agent_workflow" in data)
check("/ lists /query endpoint", any(e["path"] == "/query" for e in data["endpoints"]["rag"]))
check("/ lists /wiki/protocol endpoint", any(e["path"] == "/wiki/protocol" for e in data["endpoints"]["wiki"]))

# 1.6 /wiki/protocol endpoint (remote agent must read)
print("\n[1.6] /wiki/protocol (remote agent required)")

# default file=all: returns 3 files
r = _SESSION.get(f"{BASE}/wiki/protocol", timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("/wiki/protocol?file=all returns 200", ok, r.text)
check("has files.purpose", "purpose" in data.get("files", {}))
check("has files.schema", "schema" in data.get("files", {}))
check("has files.CLAUDE", "CLAUDE" in data.get("files", {}))
check("purpose.md content non-empty", len(data["files"].get("purpose", {}).get("content", "")) > 100)
check("schema.md content non-empty", len(data["files"].get("schema", {}).get("content", "")) > 100)
check("CLAUDE.md content non-empty", len(data["files"].get("CLAUDE", {}).get("content", "")) > 100)
check("has usage_hint", "usage_hint" in data)
# with local wiki/ present, all should be source=local (builtin fallback only for fresh deploy)
check("local files present -> all source=local", all(
    f.get("source") == "local" for f in data["files"].values()
))

# single file
r = _SESSION.get(f"{BASE}/wiki/protocol", params={"file": "CLAUDE"}, timeout=10)
data = r.json()
check("file=CLAUDE returns 200", r.status_code == 200)
check("file=CLAUDE returns file field", data.get("file") == "CLAUDE")
check("file=CLAUDE content has rule 1", "every fact must cite" in data.get("content", "").lower() or "source" in data.get("content", ""))

# invalid file
r = _SESSION.get(f"{BASE}/wiki/protocol", params={"file": "nonexistent"}, timeout=10)
check("invalid file returns error", "error" in r.json())
check("error response has available field", "available" in r.json())

# /wiki/init endpoint (skips existing by default)
r = _SESSION.post(f"{BASE}/wiki/init", timeout=10)
data = r.json()
check("/wiki/init returns 200", r.status_code == 200)
check("/wiki/init has created field", "created" in data)
check("/wiki/init has skipped field (local files -> all skipped)", "skipped" in data)
check("/wiki/init skipped >= 3 (local 3 files all skipped)", len(data.get("skipped", [])) >= 3)
check("/wiki/init returns wiki_dir", "wiki_dir" in data)

# /wiki/init?force=true should return overwritten field
r = _SESSION.post(f"{BASE}/wiki/init", params={"force": "true"}, timeout=10)
data = r.json()
check("/wiki/init?force=true returns 200", r.status_code == 200)
check("/wiki/init?force=true has overwritten field", "overwritten" in data)

# /wiki/list response contains protocol_endpoint + init_endpoint hint
r = _SESSION.get(f"{BASE}/wiki/list", timeout=10)
data = r.json()
check("/wiki/list has protocol_endpoint", data.get("protocol_endpoint") == "/wiki/protocol")
check("/wiki/list has init_endpoint", data.get("init_endpoint") == "/wiki/init")
check("/wiki/list has usage_hint", "usage_hint" in data)

# 2. list (baseline)
print("\n[2] /wiki/list (baseline)")
r = _SESSION.get(f"{BASE}/wiki/list", timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("returns count + topics fields", "count" in data and "topics" in data)
baseline_count = data.get("count", 0)
print(f"  (baseline topics count: {baseline_count})")
check("baseline topics >= 0", baseline_count >= 0)

# 3. preview create
print("\n[3] /wiki/preview (new page)")
content = """---
title: Test Page
created: 2026-06-05
last_verified: 2026-06-05
sources: []
related: []
confidence: high
type: test
search_hits: 0
---

# Test Page

This is test content.
"""
r = _SESSION.post(f"{BASE}/wiki/preview", json={"topic": TEST_TOPIC, "content": content}, timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("returns exists=False", data.get("exists") == False)
check("returns unified_diff", len(data.get("unified_diff", "")) > 0)

# 4. write preview mode
print("\n[4] /wiki/page (preview mode, confirm=false)")
r = _SESSION.post(f"{BASE}/wiki/page", json={"topic": TEST_TOPIC, "content": content, "confirm": False}, timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("preview=True", data.get("preview") == True)
check("message mentions confirm", "confirm" in data.get("message", ""))

# 5. file NOT written
test_path = f"{WIKI_DIR}/{TEST_TOPIC}"
check("preview mode did not write file", not os.path.exists(test_path))

# 6. actual write
print("\n[5] /wiki/page (persist, confirm=true)")
r = _SESSION.post(f"{BASE}/wiki/page", json={"topic": TEST_TOPIC, "content": content, "confirm": True,
                                               "source_chunks": ["test/source.pdf_1"]}, timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("preview=False", data.get("preview") == False)
check("status=ok", data.get("status") == "ok")
check("file written", os.path.exists(test_path))

# 7. read
print("\n[6] /wiki/page read")
r = _SESSION.get(f"{BASE}/wiki/page", params={"topic": TEST_TOPIC}, timeout=10)
ok, _ = expect_status(r, 200)
data = r.json()
check("content contains test text", "test content" in data.get("content", "").lower())
check("frontmatter parsed", data.get("frontmatter", {}).get("title") == "Test Page")

# 8. list (should be baseline + 1)
print("\n[7] /wiki/list (after write)")
r = _SESSION.get(f"{BASE}/wiki/list", timeout=10)
data = r.json()
check("topics count == baseline + 1", data.get("count") == baseline_count + 1, f"baseline={baseline_count}, got={data.get('count')}")
check("test topic path correct", any(t["topic"] == TEST_TOPIC for t in data["topics"]))

# 9. update (diff preview)
print("\n[8] /wiki/preview (update existing)")
new_content = content + "\n## Section 2\nUpdated content.\n"
r = _SESSION.post(f"{BASE}/wiki/preview", json={"topic": TEST_TOPIC, "content": new_content}, timeout=10)
data = r.json()
check("exists=True", data.get("exists") == True)
check("removed_lines == 0", data.get("removed_lines") == 0)
check("added_lines > 0", data.get("added_lines") > 0)

# 10. search
print("\n[9] /wiki/search")
r = _SESSION.get(f"{BASE}/wiki/search", params={"q": "test content"}, timeout=10)
data = r.json()
check("found 1 result", data.get("count") == 1)
check("snippet contains query", "test" in data["results"][0]["snippet"].lower() if data["results"] else False)

# 11. graph
print("\n[10] /wiki/graph")
r = _SESSION.get(f"{BASE}/wiki/graph", timeout=10)
data = r.json()
check("node_count >= 1", data.get("node_count", 0) >= 1)
check("edges field", "edges" in data)

# 11.5 tags: normalization + /wiki/tags endpoint
print("\n[10.5] tag normalization + /wiki/tags")

# 11.5a: /wiki/tags endpoint
r = _SESSION.get(f"{BASE}/wiki/tags", timeout=10)
data = r.json()
check("/wiki/tags returns 200", r.status_code == 200)
check("/wiki/tags has tags field", "tags" in data)
existing_tags = {t["name"] for t in data.get("tags", [])}
if data.get("count", 0) > 0:
    check("current wiki page 5 tags present", existing_tags >= {"slam", "sensor-fusion", "gaussian-splatting", "underwater-robotic", "radiance-field"})
else:
    check("empty wiki -> tags list empty", len(existing_tags) == 0)

# 11.5b: write page with messy tags, verify normalization
tag_test_topic = "test/_test_tags.md"
tag_test_content = """---
title: Tag Test
created: 2026-06-05
last_verified: 2026-06-05
sources: []
related: []
tags: []
confidence: medium
type: test
search_hits: 0
---

# Tag Test
"""
raw_messy = ["Deep Learning", "Image Stitching", "深度学习", "parallax TOLERANT", "CNNs", "image-stitching", ""]
preview_payload = {
    "topic": tag_test_topic,
    "content": tag_test_content,
    "tags": raw_messy,
    "confirm": False,
}
r = _SESSION.post(f"{BASE}/wiki/page", json=preview_payload, timeout=10)
data = r.json()
check("preview mode returns tags_normalized", "tags_normalized" in data)
norm = data.get("tags_normalized", [])
check("lowercase + hyphenate", "deep-learning" in norm)
check("image-stitching (uppercase to lowercase)", "image-stitching" in norm)
check("parallax-tolerant (space to hyphen)", "parallax-tolerant" in norm)
check("cnn (singularized)", "cnn" in norm)
check("chinese tag stripped", "深度学习" not in norm)
check("empty string removed", "" not in norm)
check("dedup (image-stitching appears once)", norm.count("image-stitching") == 1)
check("deep-learning kept (singular, not de-s-ed)", "deep-learning" in norm)

# 11.5c: persist page with tags
r = _SESSION.post(f"{BASE}/wiki/page", json={**preview_payload, "confirm": True}, timeout=10)
check("persisted tags field returned", r.json().get("tags") == norm)

# 11.5d: reading page returns normalized frontmatter.tags
r = _SESSION.get(f"{BASE}/wiki/page", params={"topic": tag_test_topic}, timeout=10)
fm = r.json().get("frontmatter", {})
check("frontmatter has tags field", "tags" in fm)
check("frontmatter.tags normalized", fm.get("tags") == norm)

# 11.5e: cleanup
r = _SESSION.post(f"{BASE}/wiki/page/delete", json={"topic": tag_test_topic, "confirm": True}, timeout=10)
check("cleanup tag test page", r.status_code == 200)

# 11.5f: /wiki/tags still works after cleanup
r = _SESSION.get(f"{BASE}/wiki/tags", timeout=10)
check("/wiki/tags ok after cleanup", r.status_code == 200)

# 12. path traversal safety
print("\n[11] Security: path traversal")
r = _SESSION.post(f"{BASE}/wiki/page", json={"topic": "../../../etc/passwd", "content": "x", "confirm": True}, timeout=10)
check("rejects .. path", r.status_code in (400, 422), f"got {r.status_code}")

r = _SESSION.post(f"{BASE}/wiki/page", json={"topic": "/etc/passwd", "content": "x", "confirm": True}, timeout=10)
check("rejects / prefix", r.status_code in (400, 422), f"got {r.status_code}")

# 13. delete preview
print("\n[12] /wiki/page/delete (preview)")
r = _SESSION.post(f"{BASE}/wiki/page/delete", json={"topic": TEST_TOPIC, "confirm": False}, timeout=10)
ok, _ = expect_status(r, 200)
check("preview=True", r.json().get("preview") == True)
check("file still exists", os.path.exists(test_path))

# 14. actual delete
print("\n[13] /wiki/page/delete (persist)")
r = _SESSION.post(f"{BASE}/wiki/page/delete", json={"topic": TEST_TOPIC, "confirm": True}, timeout=10)
ok, _ = expect_status(r, 200)
check("status=ok", r.json().get("status") == "ok")
check("file deleted", not os.path.exists(test_path))

# 15. delete non-existent
print("\n[14] /wiki/page/delete (not found)")
r = _SESSION.post(f"{BASE}/wiki/page/delete", json={"topic": TEST_TOPIC, "confirm": True}, timeout=10)
check("returns 404", r.status_code == 404, f"got {r.status_code}")

# 16. read non-existent
print("\n[15] /wiki/page (not found)")
r = _SESSION.get(f"{BASE}/wiki/page", params={"topic": TEST_TOPIC}, timeout=10)
check("returns 404", r.status_code == 404, f"got {r.status_code}")

# 17. Tailscale IP accessibility (skip unless NOLLMKB_TAILSCALE_IP is set)
_ts_ip = os.environ.get("NOLLMKB_TAILSCALE_IP", "")
if _ts_ip:
    print(f"\n[16] Via Tailscale IP ({_ts_ip})")
    r = _SESSION.get(f"http://{_ts_ip}:8765/wiki/list", timeout=10)
    ok, _ = expect_status(r, 200)
    check("Tailscale IP reachable", ok, r.text[:200])
else:
    print("\n[16] Via Tailscale IP (skipped — set NOLLMKB_TAILSCALE_IP to enable)")

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
