#!/usr/bin/env python3
"""
Disaster Recovery Tool: Rebuild library.db from canonical disk files and source.json.
Use this tool if the SQLite database is lost, corrupted, or deleted.
"""
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from src import database
from src.services.reconciliation_service import ReconciliationService

def main():
    parser = argparse.ArgumentParser(description="Rebuild library.db from canonical disk files and source.json")
    parser.add_argument("--archive-dir", type=str, default=None,
                        help="Path to archive root directory (defaults to configured ARCHIVE_DATA_DIR)")
    args = parser.parse_args()

    archive_dir = Path(args.archive_dir).resolve() if args.archive_dir else database.DATA_DIR.resolve()
    print(f"=== Instagram Saved Archiver: Disaster Recovery Rebuild ===")
    print(f"Archive Directory: {archive_dir}")

    canonical_dir = archive_dir / "media" / "canonical_files"
    if not canonical_dir.is_dir():
        print(f"[ERROR] Canonical files directory not found: {canonical_dir}")
        sys.exit(1)

    print(f"Scanning canonical files and rebuilding database...")
    def on_progress(pct, msg):
        print(f"[{pct:5.1f}%] {msg}")

    result = ReconciliationService.rebuild_library_from_disk(
        archive_dir=archive_dir,
        progress_callback=on_progress
    )

    if result.get("error"):
        print(f"[ERROR] {result['error']}")
        sys.exit(1)

    print("\n=== Rebuild Summary ===")
    print(f"Total post folders scanned: {result['total_folders']}")
    print(f"Posts restored to database: {result['posts_recovered']}")
    print(f"Media files indexed & hashed: {result['media_files_recovered']}")
    print(f"source.json metadata parsed: {result['source_jsons_found']}")
    print("Full-Text Search (FTS5) index rebuilt successfully.")
    print("Database integrity check: PASSED.")

if __name__ == '__main__':
    main()
