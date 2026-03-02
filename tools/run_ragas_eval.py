"""RAGAS evaluation CLI for the eMMC Protocol Copilot.

Runs one or all pipelines against the ground truth dataset and writes
a Markdown comparison report.

Usage:
    # Full evaluation — all three pipelines (slow, ~60+ LLM calls)
    uv run python tools/run_ragas_eval.py

    # Single pipeline
    uv run python tools/run_ragas_eval.py --pipeline hybrid_rag

    # Quick smoke-test with first 3 questions
    uv run python tools/run_ragas_eval.py --pipeline hybrid_rag --sample 3

    # Custom paths
    uv run python tools/run_ragas_eval.py \\
        --gt-path data/eval/ground_truth.jsonl \\
        --output docs/ragas_eval_results.md
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

app = typer.Typer(add_completion=False)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_PIPELINES = ("dense_rag", "hybrid_rag", "agent")


@app.command()
def main(
    pipeline: str = typer.Option(
        "all",
        help="Pipeline(s) to evaluate: dense_rag | hybrid_rag | agent | all",
    ),
    gt_path: Path = typer.Option(
        Path("data/eval/ground_truth.jsonl"),
        help="Path to ground truth JSONL file",
    ),
    output: Path = typer.Option(
        Path("docs/ragas_eval_results.md"),
        help="Output path for the Markdown report",
    ),
    sample: int = typer.Option(
        0,
        help="Evaluate only the first N questions (0 = all). Use for smoke tests.",
    ),
    save_responses: bool = typer.Option(
        True,
        help="Save raw responses + contexts to data/eval/<pipeline>_responses.jsonl for debugging",
    ),
) -> None:
    """Run RAGAS evaluation and write a Markdown report."""
    from emmc_copilot.evaluation.dataset import load_ground_truth, to_ragas_dataset
    from emmc_copilot.evaluation.runner import (
        run_dense_rag,
        run_hybrid_rag,
        run_agent,
        ragas_evaluate,
    )
    from emmc_copilot.evaluation.report import format_report
    from emmc_copilot.retrieval.embedder import BGEEmbedder

    # ------------------------------------------------------------------
    # Determine which pipelines to run
    # ------------------------------------------------------------------
    if pipeline == "all":
        selected = list(_PIPELINES)
    elif pipeline in _PIPELINES:
        selected = [pipeline]
    else:
        typer.echo(f"Unknown pipeline '{pipeline}'. Choose from: {', '.join(_PIPELINES)} or 'all'")
        raise typer.Exit(1)

    # ------------------------------------------------------------------
    # Load ground truth
    # ------------------------------------------------------------------
    if not gt_path.exists():
        typer.echo(f"Ground truth file not found: {gt_path}")
        raise typer.Exit(1)

    records = load_ground_truth(gt_path)
    if sample > 0:
        records = records[:sample]
        typer.echo(f"Smoke-test mode: evaluating first {len(records)} questions.")
    else:
        typer.echo(f"Loaded {len(records)} ground truth records.")

    questions = [r["question"] for r in records]

    # ------------------------------------------------------------------
    # Shared embedder (loaded once, reused across pipelines)
    # ------------------------------------------------------------------
    typer.echo("Loading BGE-M3 embedder…")
    embedder = BGEEmbedder()
    _ = embedder.embed_query("warm up")  # trigger lazy model load
    typer.echo("Embedder ready.")

    # ------------------------------------------------------------------
    # Run pipelines
    # ------------------------------------------------------------------
    runner_map = {
        "dense_rag": run_dense_rag,
        "hybrid_rag": run_hybrid_rag,
        "agent": run_agent,
    }

    all_results = {}

    for pl in selected:
        typer.echo(f"\n{'='*60}")
        typer.echo(f"  Pipeline: {pl}  ({len(questions)} questions)")
        typer.echo(f"{'='*60}")

        run_fn = runner_map[pl]
        responses, contexts_list = run_fn(questions)

        if save_responses:
            _save_responses(pl, records, responses, contexts_list, gt_path.parent)

        typer.echo(f"  Running RAGAS metrics for [{pl}]…")
        dataset = to_ragas_dataset(records, responses, contexts_list)
        result = ragas_evaluate(dataset, embedder)
        all_results[pl] = result

        df = result.to_pandas()
        typer.echo(f"  Results summary for [{pl}]:")
        for col in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            if col in df.columns:
                typer.echo(f"    {col}: {df[col].mean():.4f}")

    # ------------------------------------------------------------------
    # Write report
    # ------------------------------------------------------------------
    typer.echo(f"\nWriting report to {output}…")
    format_report(all_results, records, output)
    typer.echo("Done.")


def _save_responses(
    pipeline: str,
    records: list[dict],
    responses: list[str],
    contexts_list: list[list[str]],
    output_dir: Path,
) -> None:
    """Persist raw pipeline outputs for debugging / re-evaluation."""
    out_path = output_dir / f"{pipeline}_responses.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for rec, resp, ctxs in zip(records, responses, contexts_list):
            f.write(json.dumps({
                "id": rec["id"],
                "question": rec["question"],
                "response": resp,
                "contexts": ctxs,
                "reference": rec.get("reference", ""),
            }, ensure_ascii=False) + "\n")
    logger.info("Responses saved to %s", out_path)


if __name__ == "__main__":
    app()
