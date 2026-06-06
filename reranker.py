import torch
import threading
from config import DEVICE

_reranker = None
_lock = threading.Lock()


def get_reranker():
    global _reranker
    if _reranker is None:
        with _lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder
                try:
                    _reranker = CrossEncoder(
                        "BAAI/bge-reranker-v2-m3", device=DEVICE,
                        model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
                        local_files_only=True,
                    )
                except OSError:
                    _reranker = CrossEncoder(
                        "BAAI/bge-reranker-v2-m3", device=DEVICE,
                        model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
                    )
    return _reranker
