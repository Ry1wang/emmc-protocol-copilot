"""Ground truth dataset loader for RAGAS evaluation.

Loads data/eval/ground_truth.jsonl and assembles RAGAS EvaluationDataset
from pipeline-generated responses and contexts.
"""

from __future__ import annotations

import json
from pathlib import Path

from ragas import EvaluationDataset, SingleTurnSample


def load_ground_truth(path: Path) -> list[dict]:
    """Load ground_truth.jsonl and return a list of raw record dicts.

    Each record has: id, type, version, question, reference, notes (optional).
    """
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def to_ragas_dataset(
    records: list[dict],
    responses: list[str],
    contexts: list[list[str]],
) -> EvaluationDataset:
    """Assemble a RAGAS EvaluationDataset from ground truth records + pipeline outputs.

    Args:
        records:   List of ground truth dicts (from load_ground_truth).
        responses: LLM-generated answers, one per record.
        contexts:  Retrieved context strings, one list[str] per record.

    Returns:
        EvaluationDataset ready for ragas.evaluate().
    """
    if not (len(records) == len(responses) == len(contexts)):
        raise ValueError(
            f"Length mismatch: records={len(records)}, "
            f"responses={len(responses)}, contexts={len(contexts)}"
        )

    samples = [
        SingleTurnSample(
            user_input=rec["question"],
            response=resp,
            retrieved_contexts=ctxs,
            reference=rec.get("reference", ""),
        )
        for rec, resp, ctxs in zip(records, responses, contexts)
    ]
    return EvaluationDataset(samples=samples)
