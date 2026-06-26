from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

from .config import load_config
from .pipeline import configure_logging, process_directory
from .review_queue import finalize_review_item, review_queue_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local Windows PDF archive MVP: barcode, OCR/text, Ollama classification, metadata and sidecars.",
    )
    parser.add_argument("--config", default="config.example.yml", help="Path to YAML config.")
    parser.add_argument("--input", dest="input_dir", help="Override input directory from config.")
    parser.add_argument("--archive", dest="archive_dir", help="Override archive directory from config.")
    parser.add_argument("--dry-run", action="store_true", help="Plan actions without writing or moving files.")
    parser.add_argument("--no-llm", action="store_true", help="Disable Ollama and use keyword fallback classification.")
    parser.add_argument(
        "--queue-review",
        action="store_true",
        help="Analyze PDFs and put drafts into the manual review queue instead of final archiving.",
    )
    parser.add_argument("--list-review-queue", action="store_true", help="Print pending manual review queue items.")
    parser.add_argument("--include-completed-review", action="store_true", help="Include approved items in queue output.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON for queue commands.")
    parser.add_argument("--approve-review", metavar="ID", help="Approve one manual review queue item by ID.")
    parser.add_argument("--review-date", help="Manual document date in YYYY-MM-DD format.")
    parser.add_argument("--review-category-id", help="Manual category id, or a custom category id/name.")
    parser.add_argument("--review-category-name", help="Manual category display name for custom categories.")
    parser.add_argument("--review-barcode", help="Manual barcode value.")
    parser.add_argument("--review-sender", help="Manual sender/organization.")
    parser.add_argument("--review-title", help="Manual document title.")
    parser.add_argument("--review-filename-title", help="Manual short title used in the final file name.")
    parser.add_argument(
        "--review-gui",
        action="store_true",
        help="Start the primitive Windows Forms review GUI from tools/review_gui.ps1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = load_config(config_path, input_override=args.input_dir, archive_override=args.archive_dir)

    if args.list_review_queue:
        snapshot = review_queue_snapshot(config, include_completed=args.include_completed_review)
        if args.json:
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            if not snapshot["items"]:
                print("No pending review queue items.")
            for item in snapshot["items"]:
                print(
                    f"{item['status']}: {item['id']} | {item['document_date'] or 'undated'} | "
                    f"{item['category_folder'] or item['category_id']} | {item['original_filename']}"
                )
        return 0

    if args.approve_review:
        configure_logging(config.archive_dir)
        result = finalize_review_item(
            config,
            args.approve_review,
            {
                "document_date": args.review_date,
                "category_id": args.review_category_id,
                "category_name": args.review_category_name,
                "barcode": args.review_barcode,
                "sender": args.review_sender,
                "title": args.review_title,
                "short_filename_title": args.review_filename_title,
            },
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"APPROVED: {result['id']} -> {result['target_pdf']}")
        return 0

    if args.review_gui:
        return start_review_gui(config_path)

    configure_logging(config.archive_dir)

    results = process_directory(config, dry_run=args.dry_run, no_llm=args.no_llm, queue_review=args.queue_review)
    if not results:
        print(f"No PDF files found in {config.input_dir}")
        return 0

    for result in results:
        target = result.target if result.target else "-"
        marker = "QUEUE" if result.status == "queued_review" else "REVIEW" if result.review_required else result.status.upper()
        print(f"{marker}: {result.source} -> {target} ({result.message})")

    errors = [result for result in results if result.status == "error"]
    return 1 if errors else 0


def start_review_gui(config_path: Path) -> int:
    script = Path(__file__).resolve().parents[1] / "tools" / "review_gui.ps1"
    if not script.exists():
        raise FileNotFoundError(f"Review GUI script not found: {script}")

    if platform.system().lower() != "windows":
        print("The WinForms review GUI is intended for Windows.")
        print(f"Run on Windows: powershell -ExecutionPolicy Bypass -File {script} -Config {config_path} -Python {sys.executable}")
        return 0

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Config",
        str(config_path),
        "-Python",
        sys.executable,
    ]
    return subprocess.call(command)
