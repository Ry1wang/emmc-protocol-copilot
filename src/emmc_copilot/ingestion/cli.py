"""CLI entry point for the ingestion pipeline.

Usage:
    uv run python -m emmc_copilot.ingestion.cli ingest \\
        --pdf docs/protocol/JESD84-B51.pdf \\
        --output data/processed/

    # Ingest all PDFs in a directory:
    uv run python -m emmc_copilot.ingestion.cli ingest \\
        --pdf docs/protocol/ \\
        --output data/processed/
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer

from .pipeline import IngestionPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

app = typer.Typer(help="eMMC document ingestion pipeline", invoke_without_command=True)


@app.command()
def ingest(
    pdf: Path = typer.Argument(
        ...,
        help="Path to a PDF file or a directory containing PDF files.",
        exists=True,
    ),
    output: Path = typer.Option(
        Path("data/processed"),
        help="Output directory for JSONL chunk files.",
    ),
) -> None:
    """Parse, classify, and chunk eMMC PDF documents.

    Writes one JSONL file per PDF to --output, e.g.
    data/processed/JESD84-B51_chunks.jsonl
    """
    # Collect PDFs
    if pdf.is_dir():
        pdfs = sorted(pdf.glob("*.pdf"))
        if not pdfs:
            typer.echo(f"No PDF files found in {pdf}", err=True)
            raise typer.Exit(1)
    else:
        pdfs = [pdf]

    output.mkdir(parents=True, exist_ok=True)
    pipeline = IngestionPipeline()

    for pdf_path in pdfs:
        typer.echo(f"\n{'='*60}")
        typer.echo(f"Processing: {pdf_path.name}")
        typer.echo(f"{'='*60}")

        try:
            result = pipeline.run(pdf_path)
        except Exception as exc:
            typer.echo(f"[ERROR] Failed to process {pdf_path.name}: {exc}", err=True)
            raise typer.Exit(1) from exc

        # Write JSONL
        stem = pdf_path.stem
        out_file = output / f"{stem}_chunks.jsonl"
        count = 0
        with out_file.open("w", encoding="utf-8") as f:
            for chunk in result.chunks:
                f.write(json.dumps(chunk.model_dump(), ensure_ascii=False) + "\n")
                count += 1

        # Summary
        stats = result.stats()
        typer.echo(f"\nOutput: {out_file}")
        typer.echo(f"Stats:")
        for key, val in stats.items():
            typer.echo(f"  {key:20s}: {val}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
