"""CLI entry point for the retrieval indexing pipeline.

Usage:
    # Index all processed JSONL files into ChromaDB
    uv run python -m emmc_copilot.retrieval.cli index \\
        --input data/processed/ \\
        --vectorstore data/vectorstore/chroma/

    # Index a single JSONL file
    uv run python -m emmc_copilot.retrieval.cli index \\
        --input data/processed/JESD84-B51_chunks.jsonl \\
        --vectorstore data/vectorstore/chroma/

    # Show collection statistics
    uv run python -m emmc_copilot.retrieval.cli stats \\
        --vectorstore data/vectorstore/chroma/
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(help="eMMC retrieval indexing pipeline", invoke_without_command=True)


@app.command()
def index(
    input: Path = typer.Option(
        Path("data/processed"),
        "--input", "-i",
        help="Path to a JSONL chunk file or directory containing *_chunks.jsonl files.",
        exists=True,
    ),
    vectorstore: Path = typer.Option(
        Path("data/vectorstore/chroma"),
        "--vectorstore", "-v",
        help="ChromaDB persistence directory.",
    ),
    model: str = typer.Option(
        "BAAI/bge-m3",
        "--model", "-m",
        help="BGE embedding model name (HuggingFace hub).",
    ),
    fp16: bool = typer.Option(True, help="Use FP16 precision for faster inference."),
    batch_size: int = typer.Option(32, help="Number of texts per embedding batch."),
) -> None:
    """Embed chunks and upsert into ChromaDB.

    Skips chunks already present in the store (idempotent).
    """
    from .embedder import BGEEmbedder
    from .indexer import EMMCIndexer
    from .vectorstore import EMMCVectorStore

    embedder = BGEEmbedder(model_name=model, use_fp16=fp16, batch_size=batch_size)
    store = EMMCVectorStore(persist_dir=vectorstore)
    indexer = EMMCIndexer(embedder, store)

    if input.is_dir():
        typer.echo(f"Indexing all *_chunks.jsonl files in: {input}")
        indexer.index_directory(input)
    else:
        typer.echo(f"Indexing: {input}")
        s = indexer.index_file(input)
        typer.echo(
            f"  total={s['total']}  searchable={s['searchable']}  "
            f"skipped={s['skipped_existing']}  indexed={s['indexed']}"
        )

    final = store.stats()
    typer.echo(f"\nChromaDB stats:")
    typer.echo(f"  emmc_docs     : {final['docs']:>6} chunks")
    typer.echo(f"  emmc_glossary : {final['glossary']:>6} chunks")


@app.command()
def stats(
    vectorstore: Path = typer.Option(
        Path("data/vectorstore/chroma"),
        "--vectorstore", "-v",
        help="ChromaDB persistence directory.",
        exists=True,
    ),
) -> None:
    """Display ChromaDB collection statistics."""
    from .vectorstore import EMMCVectorStore

    store = EMMCVectorStore(persist_dir=vectorstore)
    s = store.stats()
    typer.echo(f"emmc_docs     : {s['docs']:>6} chunks")
    typer.echo(f"emmc_glossary : {s['glossary']:>6} chunks")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
