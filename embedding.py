import torch
import threading
from sentence_transformers import SentenceTransformer
from config import EMBED_MODEL
from config import EMBED_BATCH
from config import DEVICE

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    _model = SentenceTransformer(
                        EMBED_MODEL, device=DEVICE,
                        model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
                        local_files_only=True,
                    )
                except OSError:
                    _model = SentenceTransformer(
                        EMBED_MODEL, device=DEVICE,
                        model_kwargs={"torch_dtype": torch.float16} if DEVICE == "cuda" else {},
                    )
    return _model


class STEmbedding:
    def __init__(self):
        _get_model()
        self.name = f"st/{EMBED_MODEL}"

    def embed_documents(self, inputs):
        return _get_model().encode(
            inputs, batch_size=EMBED_BATCH, normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def embed_query(self, input):
        if isinstance(input, list):
            input = input[0]
        return self.embed_documents([str(input)])

    def __call__(self, input):
        return self.embed_documents(input)


embed_fn = STEmbedding()
