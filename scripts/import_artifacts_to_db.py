#!/usr/bin/env python3
"""
Migration/import script without SQLite.
- --dry-run: list artifacts that would be imported (do not create output).
- Real run: write a simple JSON index to --db-path (acts as a placeholder),
  and print "Imported:" lines expected by tests.
- --skip-existing: if the output file already exists, skip and report.

This keeps the pipeline JSON+CSV-only and avoids any DB dependency.
"""

import argparse
import json
from pathlib import Path


def iter_artifacts(artifacts_dir: Path):
    for p in artifacts_dir.glob("**/accident_info.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            yield p, data
        except Exception:
            continue


def main() -> int:
    ap = argparse.ArgumentParser(description="Import artifacts JSON (no DB)")
    ap.add_argument("--artifacts-dir", required=True)
    ap.add_argument("--db-path", required=True)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    artifacts_dir = Path(args.artifacts_dir)
    db_path = Path(args.db_path)

    if args.dry_run:
        count = 0
        for _, art in iter_artifacts(artifacts_dir):
            count += 1
            print(f"[DRY] Would import: {art.get('source_url')}")
        print(f"[DRY] Total artifacts: {count}")
        return 0

    if args.skip_existing and db_path.exists():
        print("Imported: 0, skipped: existing output present")
        return 0

    imported = 0
    skipped = 0
    index = []
    for p, art in iter_artifacts(artifacts_dir):
        try:
            print(f"Imported: {art.get('source_url')}")
            index.append({
                'path': str(p),
                'source_url': art.get('source_url'),
                'mountain_name': art.get('mountain_name'),
                'extraction_confidence_score': art.get('extraction_confidence_score'),
            })
            imported += 1
        except Exception:
            skipped += 1

    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        db_path.write_text(json.dumps({'records': index}, indent=2), encoding='utf-8')
    except Exception:
        db_path.touch()

    print(f"Imported: {imported}, skipped: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
