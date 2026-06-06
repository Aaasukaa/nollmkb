#!/usr/bin/env python3
"""Wiki health check — 7 automated checks (pure Python, no LLM).

Usage:
    python3 scripts/lint.py                     # report mode
    python3 scripts/lint.py --json              # JSON output (for agent)

Checks:
    1. Orphan pages      — no incoming wikilinks
    2. Stale pages        — last_verified > 60 days
    3. Dead links         — wikilinks pointing to non-existent pages
    3b. Missing cross-refs — pages sharing sources but no mutual links
    4. Source drift       — referenced chunks no longer in hash_db (needs recent scan)
    5. Size outliers      — pages < 200 or > 5000 chars
    6. Missing tags       — frontmatter without tags field

Exit code: non-zero if issues found.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

_NOLL_ROOT = Path(__file__).resolve().parent.parent
if str(_NOLL_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOLL_ROOT))

from config import WIKI_DIR


def _parse_frontmatter(text):
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fm = {}
    current_list_key = None
    for line in text[4:end].split("\n"):
        if not line.strip():
            current_list_key = None
            continue
        if line.startswith("  - ") or line.startswith("- "):
            if current_list_key:
                item = line.split("- ", 1)[1].strip()
                if len(item) >= 2 and item[0] == item[-1] and item[0] in ('"', "'"):
                    item = item[1:-1]
                fm.setdefault(current_list_key, []).append(item)
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v == "":
                current_list_key = k
                fm[k] = []
            else:
                fm[k] = v
                current_list_key = None
    return fm


def _get_wikilinks(text):
    import re
    return set(re.findall(r'\[\[([^\]]+)\]\]', text))


def _all_pages():
    """Scan wiki dir, return {stem: {fields...}}."""
    wiki_root = Path(WIKI_DIR)
    skip = {"purpose.md", "schema.md", "CLAUDE.md", "index.md", "log.md"}
    pages = {}
    for md in sorted(wiki_root.rglob("*.md")):
        if md.name in skip:
            continue
        text = md.read_text(errors="replace")
        fm = _parse_frontmatter(text)
        stem = md.stem
        pages[stem] = {
            "path": md.relative_to(wiki_root).as_posix(),
            "size": len(text),
            "outgoing": _get_wikilinks(text),
            "incoming": set(),
            "sources": set(fm.get("sources", []) or []),
            "tags": fm.get("tags", []) or [],
            "title": fm.get("title", stem),
            "last_verified": fm.get("last_verified", ""),
            "confidence": fm.get("confidence", ""),
            "type": fm.get("type", ""),
        }
    # fill incoming (resolve wikilinks to stems)
    page_by_path = {p["path"]: s for s, p in pages.items()}
    for stem in pages:
        for target in pages[stem]["outgoing"]:
            resolved = _resolve_wikilink(target, pages, page_by_path)
            if resolved:
                pages[resolved]["incoming"].add(stem)
    return pages


def _days_old(date_str):
    """Return days since date_str (YYYY-MM-DD), or None if unparseable."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, AttributeError):
        return None


def check_orphans(pages):
    """Check 1: pages with no incoming wikilinks."""
    orphans = [s for s, p in pages.items() if not p["incoming"]]
    return {"label": "orphan pages (no incoming wikilinks)", "items": orphans}


def check_stale(pages, max_days=60):
    """Check 2: pages with last_verified > max_days ago."""
    stale = []
    for s, p in pages.items():
        days = _days_old(p["last_verified"])
        if days is not None and days > max_days:
            stale.append(f"{s} ({days}d old)")
    return {"label": f"stale pages (> {max_days} days)", "items": stale}


def _resolve_wikilink(target, pages, page_by_path):
    """Resolve wikilink target to page stem. Returns stem or None."""
    if target in pages:
        return target
    if target in page_by_path:
        return page_by_path[target]
    with_ext = target + ".md" if not target.endswith(".md") else target
    # match by path suffix
    for path, stem in page_by_path.items():
        if path.endswith(with_ext) or path.endswith("/" + target):
            return stem
    # match by stem at end
    t_stem = Path(target).stem
    if t_stem in pages:
        return t_stem
    return None


def check_dead_links(pages):
    """Check 3: wikilinks pointing to non-existent pages."""
    page_by_path = {p["path"]: s for s, p in pages.items()}
    dead = []
    for src, p in pages.items():
        for target in p["outgoing"]:
            if _resolve_wikilink(target, pages, page_by_path) is None:
                dead.append(f"{src} -> [[{target}]]")
    return {"label": "dead wikilinks", "items": dead}


def check_missing_crossrefs(pages):
    """Check 3b: pages sharing sources but no mutual wikilink."""
    page_by_path = {p["path"]: s for s, p in pages.items()}
    missing = []
    stems = list(pages.keys())
    for i, a in enumerate(stems):
        for b in stems[i+1:]:
            sa, sb = pages[a]["sources"], pages[b]["sources"]
            if not sa or not sb:
                continue
            overlap = sa & sb
            if overlap:
                # check if a links to b or b links to a
                a_links_b = any(_resolve_wikilink(t, pages, page_by_path) == b
                                for t in pages[a]["outgoing"])
                b_links_a = any(_resolve_wikilink(t, pages, page_by_path) == a
                                for t in pages[b]["outgoing"])
                if not a_links_b and not b_links_a:
                    missing.append(f"{a} <-> {b} (share {len(overlap)} source(s))")
    return {"label": "missing cross-refs (shared sources, no mutual link)", "items": missing}


def check_source_drift(pages):
    """Check 4: referenced chunks whose source files have been removed or changed.

    Requires a recent do_scan() to have populated hash_db.
    """
    try:
        from hash_db import load_hashes
    except ImportError:
        return {"label": "source drift (hash_db unavailable)", "items": []}

    hashes = load_hashes()
    drifted = []
    for stem, p in pages.items():
        for chunk_id in p["sources"]:
            # chunk_id format: path/file.pdf_N
            source = "_".join(chunk_id.split("_")[:-1]) if "_" in chunk_id else chunk_id
            if source and source not in hashes:
                drifted.append(f"{stem}: {chunk_id} (source not in index)")
    return {"label": "source drift (chunks not in index)", "items": drifted}


def check_size_outliers(pages, min_size=200, max_size=5000):
    """Check 5: pages outside [min_size, max_size] char range."""
    outliers = []
    for s, p in pages.items():
        if p["size"] < min_size:
            outliers.append(f"{s} ({p['size']} chars, too small)")
        elif p["size"] > max_size:
            outliers.append(f"{s} ({p['size']} chars, too large)")
    return {"label": f"size outliers (< {min_size} or > {max_size} chars)", "items": outliers}


def check_missing_tags(pages):
    """Check 6: pages without tags in frontmatter."""
    missing = [s for s, p in pages.items() if not p["tags"]]
    return {"label": "missing tags (frontmatter.tags empty)", "items": missing}


def run_all():
    pages = _all_pages()
    if not pages:
        return {"pages": 0, "checks": []}

    checks = [
        check_orphans(pages),
        check_stale(pages),
        check_dead_links(pages),
        check_missing_crossrefs(pages),
        check_source_drift(pages),
        check_size_outliers(pages),
        check_missing_tags(pages),
    ]

    return {
        "pages": len(pages),
        "checks": checks,
    }


def main():
    json_mode = "--json" in sys.argv

    result = run_all()

    if json_mode:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result["pages"] == 0:
            print("(wiki is empty)")
            return

        issues_total = sum(len(c["items"]) for c in result["checks"])
        print(f"Wiki lint: {result['pages']} pages, {issues_total} issue(s)\n")

        for c in result["checks"]:
            label = c["label"]
            items = c["items"]
            icon = "✗" if items else "✓"
            print(f"  {icon} {label}")
            if items:
                for item in items:
                    print(f"      {item}")

    # exit code: non-zero if issues found
    total = sum(len(c["items"]) for c in result["checks"])
    sys.exit(1 if total > 0 else 0)


if __name__ == "__main__":
    main()
