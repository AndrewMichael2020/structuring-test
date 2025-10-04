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
# Attempt to load a .env file in the project directory so os.getenv sees
# local keys (e.g., GCS_BUCKET). Prefer python-dotenv if available; otherwise
# fall back to a minimal manual parser so local development still works.
try:
    from dotenv import load_dotenv  # type: ignore
    # load .env located next to this file, then fall back to working dir
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=False)
    else:
        load_dotenv(override=False)
except Exception:
    try:
        env_path = Path(__file__).resolve().parents[1] / '.env'
        if env_path.exists():
            with open(env_path, 'r', encoding='utf-8') as _f:
                for line in _f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    if k and not os.getenv(k):
                        os.environ[k] = v
    except Exception:
        pass

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
            # We intentionally do not include date in the manifest items
            # for the list page; skip normalization.
            # Try to extract Peak/Area and Activity/Style from frontmatter;
            # if missing, attempt a simple body parse for lines like:
            # - "Peak/Area: Mount Himlung" or "Peak/Area: <value>"
            body = fm.content or ''
            peak = meta.get('peak') or ''
            if not peak:
                # Look for lines like 'Peak/Area: ...' or 'Peak/Area - ...'
                m = None
                for line in body.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # strip common list markers like '- ' or '* '
                    if line.startswith('- ') or line.startswith('* '):
                        line = line[2:].strip()
                    if line.lower().startswith('peak/area:') or line.lower().startswith('peak/area -'):
                        m = line.split(':', 1)[-1].strip() if ':' in line else line.split('-', 1)[-1].strip()
                        break
                if m:
                    peak = m

            # Prefer the explicit 'Activity/Style:' line in the body when present
            activity = ''
            m2 = None
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                # strip common list markers like '- ' or '* '
                if line.startswith('- ') or line.startswith('* '):
                    line = line[2:].strip()
                if line.lower().startswith('activity/style:') or line.lower().startswith('activity/style -'):
                    m2 = line.split(':', 1)[-1].strip() if ':' in line else line.split('-', 1)[-1].strip()
                    break
            if m2:
                activity = m2
            else:
                activity = meta.get('activity') or meta.get('audience') or ''

            # Build minimal item used by the frontend list page. Include the
            # full Peak/Area and Activity/Style text (prefer body lines), the
            # frontmatter `date_of_event` if present, and the title. Exclude
            # region and summary as requested.
            # Normalize date_of_event to an ISO string if needed
            date_of_event_val = meta.get('date_of_event') or meta.get('date') or ''
            try:
                if hasattr(date_of_event_val, 'isoformat'):
                    date_of_event_val = date_of_event_val.isoformat()
            except Exception:
                date_of_event_val = str(date_of_event_val)

            item = {
                'id': p.stem,
                'title': meta.get('title') or '',
                'peak': peak,
                'date_of_event': str(date_of_event_val) if date_of_event_val is not None else '',
                # Backward compatibility: some deployed frontend bundles may still
                # look for a 'date' property; mirror date_of_event so they do not
                # render 'Invalid Date'. Once all environments use date_of_event,
                # this alias can be removed.
                'date': str(date_of_event_val) if date_of_event_val is not None else '',
                'activity': activity,
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
