"""BGE-M3 embedding wrapper using sentence-transformers.

FlagEmbedding 1.3.x is incompatible with transformers>=5 due to a removed
symbol in the reranker submodule (is_torch_fx_available). sentence-transformers
5.x supports the same BAAI/bge-m3 model via the standard HuggingFace backend
and is fully compatible with the current dependency stack.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Default model and batching constants
_DEFAULT_MODEL = "BAAI/bge-m3"
_DEFAULT_BATCH_SIZE = 32


class BGEEmbedder:
    """Thin wrapper around SentenceTransformer for BGE-M3 dense embedding.

    Lazy-loads the model on first call to :meth:`embed` so import time
    stays fast even when the GPU driver is slow to initialise.

    Output vectors are L2-normalised (unit sphere), making cosine similarity
    equivalent to dot-product — the default for Chroma's "cosine" HNSW index.

    Usage::

        embedder = BGEEmbedder()
        vecs = embedder.embed(["text A", "text B"])  # list[list[float]], dim=1024
    """

    def __init__(
        self,
        model_name: str = _DEFAULT_MODEL,
        use_fp16: bool = True,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
        self._model = None  # lazy init

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    @property
    def model(self):
        """Load and cache the SentenceTransformer model on first access."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import

            logger.info("Loading BGE-M3 via sentence-transformers: %s", self._model_name)
            self._model = SentenceTransformer(
                self._model_name,
                model_kwargs={"torch_dtype": "float16"} if self._use_fp16 else {},
            )
            logger.info("BGE-M3 model loaded (dim=1024).")
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode *texts* and return L2-normalised dense vectors.

        Texts are processed in batches of :attr:`_batch_size` to avoid OOM.
        Empty input returns an empty list.
        """
        if not texts:
            return []

        vecs = self.model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,   # L2 normalise → cosine ≡ dot-product
            show_progress_bar=False,
        )
        return vecs.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Convenience method for single-query embedding."""
        return self.embed([text])[0]
