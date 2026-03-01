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


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (semantic or technical)."),
    n: int = typer.Option(3, help="Number of results to return."),
    version: str | None = typer.Option(None, "--v", help="Filter by eMMC version (e.g. '5.1')."),
    collection: str = typer.Option("docs", help="Collection to search: 'docs' or 'glossary'."),
    vectorstore: Path = typer.Option(
        Path("data/vectorstore/chroma"),
        "--vectorstore", "-v",
        help="ChromaDB persistence directory.",
    ),
) -> None:
    """Perform semantic search against the eMMC knowledge base."""
    from .embedder import BGEEmbedder
    from .vectorstore import EMMCVectorStore

    embedder = BGEEmbedder()
    store = EMMCVectorStore(persist_dir=vectorstore)

    typer.echo(f"\n🔍 Query: {query}")
    query_vec = embedder.embed_query(query)

    # Filtering
    where = None
    if version:
        where = {"version": version}

    results = store.query(query_vec, n_results=n, where=where, collection=collection)

    if not results:
        typer.echo(typer.style("No results found.", fg=typer.colors.RED))
        return

    for i, res in enumerate(results, 1):
        meta = res["metadata"]
        dist = res["distance"]
        typer.echo(f"\n[{i}] " + typer.style(f"Distance: {dist:.4f}", fg=typer.colors.CYAN))
        typer.echo(
            typer.style(f"Source: {meta['source']} (v{meta['version']})", fg=typer.colors.BRIGHT_BLACK) +
            typer.style(f" | Page: {meta['page_start']}", fg=typer.colors.BRIGHT_BLACK)
        )
        
        # Path string
        path = meta.get("section_path", "").replace("/", " > ")
        title = meta.get("section_title", "Untitled")
        typer.echo(typer.style(f"Path: {path or 'Root'} > {title}", fg=typer.colors.YELLOW))
        
        # Content snippet
        text = res["document"]
        if len(text) > 800:
            text = text[:800] + "..."
        typer.echo("-" * 40)
        typer.echo(text)
        typer.echo("-" * 40)


@app.command("build-bm25")
def build_bm25(
    input: Path = typer.Option(
        Path("data/processed"),
        "--input", "-i",
        help="Directory containing *_chunks.jsonl files.",
        exists=True,
    ),
    output: Path = typer.Option(
        Path("data/vectorstore/bm25"),
        "--output", "-o",
        help="Directory to write corpus.pkl.",
    ),
) -> None:
    """Build a BM25 keyword index from processed JSONL chunk files.

    Iterates over all *_chunks.jsonl files in --input, indexes non-front-matter
    chunks, and saves the corpus to <output>/corpus.pkl.
    """
    from .bm25_index import BM25Corpus

    jsonl_paths = sorted(input.glob("*_chunks.jsonl"))
    if not jsonl_paths:
        typer.echo(typer.style(f"No *_chunks.jsonl files found in {input}", fg=typer.colors.RED))
        raise typer.Exit(1)

    typer.echo(f"Found {len(jsonl_paths)} JSONL file(s): {[p.name for p in jsonl_paths]}")
    corpus = BM25Corpus.build_from_jsonl(jsonl_paths)

    output.mkdir(parents=True, exist_ok=True)
    pkl_path = output / "corpus.pkl"
    corpus.save(pkl_path)

    typer.echo(
        typer.style(f"\nBM25 index built: {len(corpus)} chunks indexed", fg=typer.colors.GREEN)
    )
    typer.echo(f"Saved to: {pkl_path}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
