import jieba
import math
import threading


class BM25Index:
    def __init__(self, docs):
        self.docs = docs
        self.n = len(docs)
        self.avgdl = sum(len(d) for d in docs) / self.n if self.n else 1
        self.df = {}
        self.tf = []
        for doc in docs:
            freq = {}
            for t in doc:
                freq[t] = freq.get(t, 0) + 1
            self.tf.append(freq)
            for t in freq:
                self.df[t] = self.df.get(t, 0) + 1
        self.k1 = 1.5
        self.b = 0.75

    def search(self, terms, top_k=20):
        if not self.docs:
            return []
        scores = []
        for i in range(self.n):
            s = self._score(terms, i)
            if s > 0:
                scores.append((i, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _score(self, terms, idx):
        dl = len(self.docs[idx])
        s = 0.0
        for t in terms:
            if t not in self.df:
                continue
            tf = self.tf[idx].get(t, 0)
            idf = math.log((self.n - self.df[t] + 0.5) / (self.df[t] + 0.5) + 1)
            s += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return s


# _bm25 = (BM25Index, meta_list, texts_list) immutable snapshot, or None
_bm25 = None
# authority lists — mutated by rebuild/remove/reset, snapshotted by _ensure_bm25
_bm25_meta = []
_bm25_texts = []


def _tokenize(text):
    return [w for w in jieba.cut(text) if len(w.strip()) > 1]


_build_lock = threading.Lock()


def _ensure_bm25():
    """Lazy-rebuild BM25 index. Only one thread rebuilds; others fall back to vector-only.

    Non-blocking: threads that lose the race skip BM25 entirely for this query.
    The winner builds locally then atomically assigns _bm25 to the immutable
    (index, meta, texts) tuple — in-flight queries holding the old tuple stay safe.
    """
    global _bm25
    if _bm25 is None and _bm25_texts:
        if _build_lock.acquire(blocking=False):
            try:
                if _bm25 is None and _bm25_texts:
                    meta_snap = list(_bm25_meta)
                    texts_snap = list(_bm25_texts)
                    idx = BM25Index([_tokenize(d) for d in texts_snap])
                    _bm25 = (idx, meta_snap, texts_snap)
            finally:
                _build_lock.release()


def rebuild_bm25(col):
    global _bm25, _bm25_meta, _bm25_texts
    r = col.get(include=["documents", "metadatas"])
    docs = r.get("documents") or []
    metas = r.get("metadatas") or []
    _bm25_meta = [(m["source"], m["chunk"], m.get("ext", ""), m.get("dir", "")) for m in metas]
    _bm25_texts = docs
    _bm25 = (BM25Index([_tokenize(d) for d in docs]), list(_bm25_meta), list(_bm25_texts))


def remove_from_bm25(source: str):
    """Remove all chunks of a given source from the authority lists.

    Invalidates _bm25 so the next query lazy-rebuilds from the updated lists.
    Old _bm25 tuples stay alive for in-flight queries (COW).
    """
    global _bm25, _bm25_meta, _bm25_texts
    if not _bm25_meta:
        return
    before = len(_bm25_meta)
    keep = [(m, t) for m, t in zip(_bm25_meta, _bm25_texts) if m[0] != source]
    if len(keep) < before:
        _bm25_meta = [k[0] for k in keep]
        _bm25_texts = [k[1] for k in keep]
        _bm25 = None


def reset_bm25():
    """Clear the in-memory BM25 index (for delete-all)."""
    global _bm25, _bm25_meta, _bm25_texts
    _bm25 = None
    _bm25_meta = []
    _bm25_texts = []
