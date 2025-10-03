#!/usr/bin/env python3
"""Build a canonical reports/list.json from `events/reports/*.md` front-matter.

Usage:
  python scripts/build_reports_list.py [--upload]

If --upload is provided and env var GCS_BUCKET is set, the script uploads
the resulting `list.json` to `gs://<GCS_BUCKET>/reports/list.json`.
"""
from pathlib import Path
import sys
import json
import argparse
import os

import frontmatter

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / 'events' / 'reports'


def scan_reports():
    out = []
    if not REPORTS_DIR.exists():
        return out
    for p in sorted(REPORTS_DIR.glob('*.md')):
        try:
            fm = frontmatter.load(p)
            meta = fm.metadata or {}
            date_val = meta.get('date', '') or ''
            # normalize date objects to ISO strings
            try:
                if hasattr(date_val, 'isoformat'):
                    date_val = date_val.isoformat()
            except Exception:
                pass
            item = {
                'id': p.stem,
                'date': str(date_val),
                'region': meta.get('region', '') or '',
                'activity': meta.get('activity') or meta.get('audience', '') or '',
                'title': meta.get('title') or '',
                'summary': meta.get('description') or '',
            }
            out.append(item)
        except Exception:
            # best-effort: if parsing fails, include id only
            out.append({'id': p.stem})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--upload', action='store_true', help='Upload to GCS_BUCKET')
    args = ap.parse_args()

    items = scan_reports()
    # Validate shape: schema expects an array of objects with at least id, date, region, activity, title.
    # We keep items as-is; consumers should tolerate missing fields.
    data = items
    out_path = Path('/tmp/list.json')
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {out_path} ({len(items)} items)')

    if args.upload:
        bucket = os.environ.get('GCS_BUCKET')
        if not bucket:
            print('GCS_BUCKET not set; skipping upload')
            return
        dest = f'gs://{bucket}/reports/list.json'
        print(f'Uploading to {dest}...')
        import subprocess
        subprocess.check_call(['gsutil', 'cp', str(out_path), dest])
        print('Upload complete')


if __name__ == '__main__':
    main()
