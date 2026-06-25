from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .pipeline import configure_logging, process_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local Windows PDF archive MVP: barcode, OCR/text, Ollama classification, metadata and sidecars.",
    )
    parser.add_argument("--config", default="config.example.yml", help="Path to YAML config.")
    parser.add_argument("--input", dest="input_dir", help="Override input directory from config.")
    parser.add_argument("--archive", dest="archive_dir", help="Override archive directory from config.")
    parser.add_argument("--dry-run", action="store_true", help="Plan actions without writing or moving files.")
    parser.add_argument("--no-llm", action="store_true", help="Disable Ollama and use keyword fallback classification.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = load_config(config_path, input_override=args.input_dir, archive_override=args.archive_dir)
    configure_logging(config.archive_dir)

    results = process_directory(config, dry_run=args.dry_run, no_llm=args.no_llm)
    if not results:
        print(f"No PDF files found in {config.input_dir}")
        return 0

    for result in results:
        target = result.target if result.target else "-"
        marker = "REVIEW" if result.review_required else result.status.upper()
        print(f"{marker}: {result.source} -> {target} ({result.message})")

    errors = [result for result in results if result.status == "error"]
    return 1 if errors else 0
