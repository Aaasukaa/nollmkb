from config import CHUNK_SIZE, CHUNK_OVERLAP, MIN_CHUNK, MAX_CHUNK


def chunk_text(text):
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP
    if len(chunks) > 1 and len(chunks[-1]) < MIN_CHUNK:
        chunks[-2] += "\n" + chunks[-1]
        chunks.pop()
    return chunks


def chunk_blocks(blocks, chunk_size=1500):
    """Pack blocks into chunks at paragraph boundaries, with overlap for continuity."""
    chunks, buf = [], ""
    for b in blocks:
        oversized = len(b) > chunk_size

        if oversized and buf:
            chunks.append(buf.strip())
            buf = _tail_overlap(buf)
        if oversized:
            pieces = _hard_split(b, chunk_size)
            fixed = []
            for p in pieces:
                if fixed and len(p) < MIN_CHUNK:
                    fixed[-1] += "\n" + p
                else:
                    fixed.append(p)
            chunks.extend(fixed)
            continue

        if not buf:
            buf = b
            continue

        if len(buf + "\n" + b) <= chunk_size:
            buf += "\n" + b
            continue

        if len(buf) < MIN_CHUNK:
            buf += "\n" + b
            if len(buf) > MAX_CHUNK:
                pieces = _hard_split(buf, MAX_CHUNK)
                chunks.extend(pieces[:-1])
                buf = _merge_overlap(pieces[-1], "")
            continue

        chunks.append(buf.strip())
        buf = _tail_overlap(buf)
        if buf:
            buf += "\n" + b
        else:
            buf = b

    if buf.strip():
        if len(buf) < MIN_CHUNK and chunks:
            chunks[-1] += "\n" + buf.strip()
        else:
            chunks.append(buf.strip())

    result = []
    for c in chunks:
        if result and len(c) < MIN_CHUNK:
            result[-1] += "\n" + c
        else:
            result.append(c)
    capped = []
    for c in result:
        while len(c) > MAX_CHUNK:
            split_at = MAX_CHUNK
            while split_at > MAX_CHUNK // 2 and c[split_at] != "\n":
                split_at -= 1
            if split_at > MAX_CHUNK // 2:
                capped.append(c[:split_at].strip())
                c = c[split_at:].strip()
            else:
                capped.append(c[:MAX_CHUNK].strip())
                c = c[MAX_CHUNK:].strip()
        if c.strip():
            capped.append(c.strip())
    result = []
    for c in capped:
        if result and len(c) < MIN_CHUNK:
            result[-1] += "\n" + c
        else:
            result.append(c)
    return result


def _tail_overlap(text, overlap=100):
    """Return last ~overlap chars of text starting at natural boundary."""
    if len(text) <= overlap:
        return ""
    start = len(text) - overlap
    while start > 0 and text[start] not in "\n。！？. ":
        start -= 1
    return text[max(start-1, 0):].strip()


def _merge_overlap(tail, head, overlap=100):
    """Merge tail overlap with head block."""
    if not tail:
        return head
    tail_overlap = _tail_overlap(tail, overlap)
    if head:
        return (tail_overlap + "\n" + head) if tail_overlap else head
    return tail_overlap


def _hard_split(text, limit):
    seps = ["\n\n", "\n", "。", "！", "？", ". ", "，", ", ", " "]
    for sep in seps:
        if sep in text:
            pieces = [p.strip() for p in text.split(sep) if p.strip()]
            result = []
            for p in pieces:
                if len(p) <= limit:
                    result.append(p)
                else:
                    for i in range(0, len(p), limit):
                        result.append(p[i:i+limit])
            return result
    return [text[i:i+limit] for i in range(0, len(text), limit)]
