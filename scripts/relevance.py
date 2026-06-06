#!/usr/bin/env python3
"""4-signal relevance scoring for wiki pages.

Usage:
    python3 scripts/relevance.py <topic>           # find related pages for topic
    python3 scripts/relevance.py <topic> --all     # list all pages with scores

Signals (nashsu model, pure Python, no LLM):
    1. Direct wikilink: ×3.0
    2. Source overlap (same nollmkb chunk): ×4.0 (strongest)
    3. Adamic-Adar over shared neighbors: ×1.5
    4. Type affinity (same frontmatter type): ×1.0
"""

import sys
import os
from pathlib import Path
from collections import defaultdict

_NOLL_ROOT = Path(__file__).resolve().parent.parent
if str(_NOLL_ROOT) not in sys.path:
    sys.path.insert(0, str(_NOLL_ROOT))

from config import WIKI_DIR


def _parse_frontmatter(text: str) -> dict:
    """Minimal YAML frontmatter parser (duplicated from wiki_server for self-containment)."""
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


def _get_wikilinks(text: str) -> set[str]:
    """Extract [[wikilinks]]."""
    import re
    return set(re.findall(r'\[\[([^\]]+)\]\]', text))


def build_graph(wiki_dir: str = None) -> dict:
    """Scan all .md pages, build a graph of wikilinks + sources.

    Returns:
        dict: {page_stem: {"outgoing": set, "incoming": set, "sources": set,
                           "type": str, "title": str, "path": str}}
    """
    if wiki_dir is None:
        wiki_dir = WIKI_DIR
    wiki_root = Path(wiki_dir)
    skip_names = {"purpose.md", "schema.md", "CLAUDE.md", "index.md", "log.md"}

    pages = {}
    for md in sorted(wiki_root.rglob("*.md")):
        if md.name in skip_names:
            continue
        text = md.read_text(errors="replace")
        fm = _parse_frontmatter(text)
        rel = md.relative_to(wiki_root).as_posix()
        stem = md.stem
        pages[stem] = {
            "outgoing": _get_wikilinks(text),
            "incoming": set(),
            "sources": set(fm.get("sources", []) or []),
            "type": fm.get("type", ""),
            "title": fm.get("title", stem),
            "path": rel,
        }

    # fill incoming links
    for stem in pages:
        for target in pages[stem]["outgoing"]:
            if target in pages:
                pages[target]["incoming"].add(stem)

    return pages


def relevance(page_a: str, page_b: str, pages: dict) -> float:
    """Compute 4-signal relevance between two pages.

    Returns score >= 0.  Higher = more related.
    """
    if page_a == page_b:
        return 0
    a, b = pages.get(page_a), pages.get(page_b)
    if not a or not b:
        return 0

    score = 0.0

    # 1. Direct wikilink ×3.0
    if page_b in a["outgoing"] or page_b in a["incoming"]:
        score += 3.0

    # 2. Source overlap ×4.0 (strongest — same original document)
    overlap = a["sources"] & b["sources"]
    score += 4.0 * len(overlap)

    # 3. Adamic-Adar over shared neighbors ×1.5
    nb_a = a["incoming"] | a["outgoing"]
    nb_b = b["incoming"] | b["outgoing"]
    common = nb_a & nb_b
    for n in common:
        if n in pages:
            degree = len(pages[n]["incoming"] | pages[n]["outgoing"])
            if degree > 0:
                score += 1.5 * (1.0 / max(1.0, degree))

    # 4. Type affinity ×1.0
    if a["type"] == b["type"] and a["type"]:
        score += 1.0

    return round(score, 2)


def find_related(topic: str, top_k: int = 5, wiki_dir: str = None) -> list[tuple[str, str, float]]:
    """Find top-k related pages for a topic.

    Returns:
        list of (stem, title, score) sorted by score desc.
    """
    pages = build_graph(wiki_dir)

    # try exact stem match first, then loose match
    if topic not in pages:
        topic_lower = topic.lower()
        candidates = [(s, p) for s, p in pages.items()
                      if topic_lower in s.lower() or topic_lower in p["title"].lower()]
        if candidates:
            topic = candidates[0][0]
        else:
            return []

    scored = [(target, pages[target]["title"], relevance(topic, target, pages))
              for target in pages if target != topic]
    scored.sort(key=lambda x: -x[2])
    return [(s, t, v) for s, t, v in scored[:top_k] if v > 0]


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/relevance.py <topic> [--all]")
        print("Example: python3 scripts/relevance.py 'SLAM技术路线综述'")
        sys.exit(1)

    topic = sys.argv[1]
    show_all = "--all" in sys.argv

    pages = build_graph()
    if not pages:
        print("(wiki is empty)")
        return

    if show_all:
        for stem, p in pages.items():
            rel = find_related(stem, top_k=3)
            if rel:
                print(f"\n{p.get('title', stem)} ({p['path']})")
                for r_stem, r_title, r_score in rel:
                    print(f"  {r_score:5.1f}  {r_title}  ({pages[r_stem]['path']})")
    else:
        results = find_related(topic)
        if not results:
            print(f"No related pages found for '{topic}'")
            print(f"Available pages: {', '.join(pages.keys())}")
        else:
            print(f"Related to '{topic}':")
            for stem, title, score in results:
                p = pages.get(stem, {})
                print(f"  {score:5.1f}  {title}  ({p.get('path', stem)})")


if __name__ == "__main__":
    main()
