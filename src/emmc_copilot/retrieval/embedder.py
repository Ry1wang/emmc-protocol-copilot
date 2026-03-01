"""BGE-M3 embedding wrapper using FlagEmbedding."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# Default model and batching constants
_DEFAULT_MODEL = "BAAI/bge-m3"
_DEFAULT_BATCH_SIZE = 32
_MAX_LENGTH = 8192  # BGE-M3 max token length


class BGEEmbedder:
    """Thin wrapper around BGEM3FlagModel for dense embedding.

    Lazy-loads the model on first call to :meth:`embed` so import time
    stays fast even when the GPU driver is slow to initialise.

    Usage::

        embedder = BGEEmbedder()
        vecs = embedder.embed(["text A", "text B"])  # list[list[float]]
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
        """Load and cache the BGEM3FlagModel on first access."""
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # heavy import

            logger.info("Loading BGE-M3 model: %s (fp16=%s)", self._model_name, self._use_fp16)
            self._model = BGEM3FlagModel(self._model_name, use_fp16=self._use_fp16)
            logger.info("BGE-M3 model loaded.")
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Encode *texts* and return dense vectors as a list of float lists.

        Texts are processed in batches of :attr:`batch_size` to avoid OOM.
        Empty input returns an empty list.
        """
        if not texts:
            return []

        all_vecs: list[list[float]] = []
        total = len(texts)
        processed = 0

        for start in range(0, total, self._batch_size):
            batch = texts[start : start + self._batch_size]
            result = self.model.encode(
                batch,
                batch_size=self._batch_size,
                max_length=_MAX_LENGTH,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            vecs = result["dense_vecs"]  # numpy array (batch, 1024)
            all_vecs.extend(vecs.tolist())
            processed += len(batch)
            logger.debug("Embedded %d / %d texts", processed, total)

        return all_vecs

    def embed_query(self, text: str) -> list[float]:
        """Convenience method for single-query embedding."""
        return self.embed([text])[0]
