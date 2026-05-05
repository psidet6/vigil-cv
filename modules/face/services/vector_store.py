"""Pluggable vector search abstraction for face embeddings.

Uses **hnswlib** when available for O(log N) approximate nearest-neighbor
search.  Falls back transparently to numpy brute-force (exact) search when
hnswlib is not installed.

Usage::

    from modules.face.services.vector_store import VectorIndex

    idx = VectorIndex(dim=512)
    idx.build(embeddings_matrix)           # np.ndarray  (N, 512)
    labels, scores = idx.query(probe, k=5) # probe: (512,) float32

Both backends return **cosine similarity** scores in descending order.
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from shared.config.config import logger

# ---------------------------------------------------------------------------
# Abstract interface (for type hints only)
# ---------------------------------------------------------------------------


class _Index(Protocol):
    def build(self, matrix: np.ndarray) -> None: ...
    def query(self, probe: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]: ...
    @property
    def size(self) -> int: ...


# ---------------------------------------------------------------------------
# hnswlib backend
# ---------------------------------------------------------------------------

_HAS_HNSWLIB = False
try:
    import hnswlib as _hnswlib

    _HAS_HNSWLIB = True
except ImportError:
    _hnswlib = None  # type: ignore[assignment]


class _HnswIndex:
    """hnswlib-backed approximate nearest-neighbor index (inner-product space)."""

    def __init__(self, dim: int, ef_construction: int = 200, M: int = 16):
        self._dim = dim
        self._ef_construction = ef_construction
        self._M = M
        self._index: _hnswlib.Index | None = None
        self._size = 0

    def build(self, matrix: np.ndarray) -> None:
        n = matrix.shape[0]
        idx = _hnswlib.Index(space="ip", dim=self._dim)
        idx.init_index(max_elements=max(n, 1), ef_construction=self._ef_construction, M=self._M)
        if n > 0:
            idx.add_items(matrix.astype(np.float32), np.arange(n))
        idx.set_ef(max(50, min(n, 200)))
        self._index = idx
        self._size = n

    def query(self, probe: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        if self._index is None or self._size == 0:
            return np.array([], dtype=np.int64), np.array([], dtype=np.float32)
        k = min(k, self._size)
        labels, distances = self._index.knn_query(probe.reshape(1, -1).astype(np.float32), k=k)
        # hnswlib "ip" returns 1-cos for normalized vectors; convert to similarity.
        scores = 1.0 - distances[0]
        return labels[0].astype(np.int64), scores.astype(np.float32)

    @property
    def size(self) -> int:
        return self._size


# ---------------------------------------------------------------------------
# numpy brute-force fallback
# ---------------------------------------------------------------------------


class _NumpyIndex:
    """Exact brute-force cosine search via matrix multiplication."""

    def __init__(self, dim: int):
        self._dim = dim
        self._matrix: np.ndarray = np.empty((0, dim), dtype=np.float32)

    def build(self, matrix: np.ndarray) -> None:
        self._matrix = matrix.astype(np.float32)

    def query(self, probe: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        if self._matrix.size == 0:
            return np.array([], dtype=np.int64), np.array([], dtype=np.float32)
        scores = self._matrix @ probe.astype(np.float32)
        k = min(k, len(scores))
        top_idx = np.argpartition(scores, -k)[-k:]
        top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
        return top_idx.astype(np.int64), scores[top_idx].astype(np.float32)

    @property
    def size(self) -> int:
        return self._matrix.shape[0]


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


class VectorIndex:
    """Facade that picks the best available backend automatically."""

    def __init__(self, dim: int = 512):
        self._lock = threading.Lock()
        if _HAS_HNSWLIB:
            logger.info("VectorIndex: using hnswlib backend")
            self._impl: _Index = _HnswIndex(dim)
        else:
            logger.info("VectorIndex: hnswlib not installed, using numpy brute-force")
            self._impl = _NumpyIndex(dim)

    def build(self, matrix: np.ndarray) -> None:
        with self._lock:
            self._impl.build(matrix)

    def query(self, probe: np.ndarray, k: int = 5) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            return self._impl.query(probe, k)

    @property
    def size(self) -> int:
        return self._impl.size

    @property
    def backend(self) -> str:
        return "hnswlib" if isinstance(self._impl, _HnswIndex) else "numpy"
