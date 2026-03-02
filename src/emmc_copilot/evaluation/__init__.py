"""Phase 4 — RAGAS-based performance evaluation."""

from .dataset import load_ground_truth, to_ragas_dataset
from .runner import ragas_evaluate, run_agent, run_dense_rag, run_hybrid_rag
from .report import format_report

__all__ = [
    "load_ground_truth",
    "to_ragas_dataset",
    "run_dense_rag",
    "run_hybrid_rag",
    "run_agent",
    "ragas_evaluate",
    "format_report",
]
