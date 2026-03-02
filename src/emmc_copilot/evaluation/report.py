"""RAGAS evaluation report formatter.

Generates a Markdown report from one or more EvaluationResult objects,
including a pipeline comparison summary table, a by-question-type breakdown,
and a per-question detail table for the primary (hybrid_rag) pipeline.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragas import EvaluationResult

# Canonical metric column names as returned by RAGAS 0.4.x
_METRIC_COLS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
_METRIC_LABELS = {
    "faithfulness": "Faithfulness",
    "answer_relevancy": "AnswerRelevancy",
    "context_precision": "ContextPrecision",
    "context_recall": "ContextRecall",
}
_PIPELINE_LABELS = {
    "dense_rag": "Dense-only RAG (baseline)",
    "hybrid_rag": "Hybrid RAG (BGE-M3 + BM25 + RRF)",
    "agent": "LangGraph Agent (4 tools)",
}


def _fmt(v: float | None) -> str:
    """Format a metric value as a 4-decimal string, or '—' if None / NaN."""
    if v is None:
        return "—"
    try:
        if v != v:  # NaN check
            return "—"
        return f"{v:.4f}"
    except (TypeError, ValueError):
        return "—"


def _mean(series) -> float | None:
    """Return the mean of a pandas Series, or None if all NaN."""
    try:
        val = float(series.mean())
        if val != val:
            return None
        return val
    except Exception:
        return None


def format_report(
    results: dict[str, "EvaluationResult"],
    records: list[dict],
    output_path: Path,
) -> None:
    """Write a Markdown RAGAS evaluation report.

    Args:
        results:     Dict mapping pipeline label → EvaluationResult.
                     Keys should be one or more of: "dense_rag", "hybrid_rag", "agent".
        records:     Ground truth records list (from dataset.load_ground_truth).
        output_path: Path to write the .md report.
    """
    lines: list[str] = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines += [
        "# RAGAS 评测报告",
        "",
        f"**生成时间**: {now}  ",
        f"**评测样本数**: {len(records)}  ",
        f"**评测 Pipeline**: {', '.join(results.keys())}  ",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------------------------
    # 1. Pipeline comparison summary table
    # ------------------------------------------------------------------
    lines += [
        "## 一、汇总指标对比（各 Pipeline）",
        "",
        "| Pipeline | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |",
        "|----------|:------------:|:---------------:|:----------------:|:-------------:|",
    ]

    pipeline_scores: dict[str, dict[str, float | None]] = {}
    for label, result in results.items():
        df = result.to_pandas()
        scores: dict[str, float | None] = {}
        for col in _METRIC_COLS:
            scores[col] = _mean(df[col]) if col in df.columns else None
        pipeline_scores[label] = scores

        display = _PIPELINE_LABELS.get(label, label)
        row = " | ".join(_fmt(scores[c]) for c in _METRIC_COLS)
        lines.append(f"| {display} | {row} |")

    lines += ["", ""]

    # ------------------------------------------------------------------
    # 2. By-type breakdown (hybrid_rag only, most informative)
    # ------------------------------------------------------------------
    if "hybrid_rag" in results:
        df = results["hybrid_rag"].to_pandas()
        # Attach question type from records
        types = [r.get("type", "unknown") for r in records[:len(df)]]
        df = df.copy()
        df["_type"] = types

        lines += [
            "## 二、按问题类型聚合（hybrid_rag）",
            "",
            "*注：计算题和边界题的 Recall 指标可能因答案较短而偏低，重点关注 factual / comparison 类。*",
            "",
            "| Type | N | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall |",
            "|------|:-:|:------------:|:---------------:|:----------------:|:-------------:|",
        ]

        for qtype in ["factual", "calculation", "comparison", "edge_case"]:
            sub = df[df["_type"] == qtype]
            if sub.empty:
                continue
            n = len(sub)
            row_vals = " | ".join(
                _fmt(_mean(sub[c])) if c in sub.columns else "—"
                for c in _METRIC_COLS
            )
            lines.append(f"| `{qtype}` | {n} | {row_vals} |")

        lines += ["", ""]

    # ------------------------------------------------------------------
    # 3. Delta table (Hybrid vs Dense)
    # ------------------------------------------------------------------
    if "dense_rag" in pipeline_scores and "hybrid_rag" in pipeline_scores:
        d_scores = pipeline_scores["dense_rag"]
        h_scores = pipeline_scores["hybrid_rag"]

        lines += [
            "## 三、Hybrid vs Dense 提升量（Δ）",
            "",
            "| 指标 | Dense-only | Hybrid RAG | Δ |",
            "|------|:----------:|:----------:|:-:|",
        ]
        for col in _METRIC_COLS:
            d_val = d_scores.get(col)
            h_val = h_scores.get(col)
            if d_val is not None and h_val is not None:
                delta = h_val - d_val
                sign = "+" if delta >= 0 else ""
                lines.append(
                    f"| {_METRIC_LABELS[col]} | {_fmt(d_val)} | {_fmt(h_val)} | {sign}{delta:.4f} |"
                )
            else:
                lines.append(f"| {_METRIC_LABELS[col]} | {_fmt(d_val)} | {_fmt(h_val)} | — |")

        lines += ["", ""]

    # ------------------------------------------------------------------
    # 4. Per-question detail (hybrid_rag)
    # ------------------------------------------------------------------
    if "hybrid_rag" in results:
        df = results["hybrid_rag"].to_pandas()
        lines += [
            "## 四、逐题评分明细（hybrid_rag）",
            "",
            "| ID | Type | Faithfulness | AnswerRelevancy | ContextPrecision | ContextRecall | 问题摘要 |",
            "|----|------|:------------:|:---------------:|:----------------:|:-------------:|----------|",
        ]
        for i, (_, row) in enumerate(df.iterrows()):
            rec = records[i] if i < len(records) else {}
            qid = rec.get("id", f"Q{i+1:02d}")
            qtype = rec.get("type", "—")
            q_short = rec.get("question", "")[:30] + ("…" if len(rec.get("question", "")) > 30 else "")
            scores_str = " | ".join(
                _fmt(row.get(c)) if c in df.columns else "—"
                for c in _METRIC_COLS
            )
            lines.append(f"| {qid} | `{qtype}` | {scores_str} | {q_short} |")

        lines += ["", ""]

    # ------------------------------------------------------------------
    # 5. Disclaimer
    # ------------------------------------------------------------------
    lines += [
        "---",
        "",
        "## 免责声明",
        "",
        "> 本评测中担任 Judge（裁判）和 Generator（生成器）的模型均为 **DeepSeek**，",
        "> 指标可能包含一定的「自我偏好偏差」（Self-Preference Bias）。",
        "> 本报告的核心价值在于：**相同模型基座下，不同检索策略之间的相对性能提升（Δ）对比**，",
        "> 绝对分值仅供参考，不代表在独立第三方 Judge 下的客观评分。",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to: {output_path}")
