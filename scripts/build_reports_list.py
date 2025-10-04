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
import re
import traceback
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


_PEAK_RE = re.compile(r'^peak/area\s*[:\-]\s*(.+)$', re.IGNORECASE)
_ACTIVITY_RE = re.compile(r'^activity/style\s*[:\-]\s*(.+)$', re.IGNORECASE)


def _load_frontmatter_lenient(path: Path):
    """A permissive front matter parser for simple key: value lines.

    Handles cases where standard YAML parsing fails due to unquoted colons in values
    (e.g., 'date_of_event: Specific date known (month/day: August 12, year unknown)').

    Returns (meta: dict, body: str) or (None, None) if the file does not appear
    to contain a front matter block.
    """
    try:
        raw = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return None, None
    if not raw.startswith('---'):
        return None, None
    parts = raw.split('\n')
    # Find second delimiter line index
    delim_indices = [i for i, line in enumerate(parts) if line.strip() == '---']
    if len(delim_indices) < 2:
        return None, None
    start, end = delim_indices[0], delim_indices[1]
    fm_lines = parts[start + 1:end]
    body = '\n'.join(parts[end + 1:])
    meta = {}
    current_key = None
    multiline_buffer = []
    for line in fm_lines:
        raw_line = line.rstrip('\n')
        if not raw_line.strip() or raw_line.strip().startswith('#'):
            continue
        # Very simple multi-line value support: if line is indented and we have a current key
        if raw_line.startswith((' ', '\t')) and current_key:
            multiline_buffer.append(raw_line.strip())
            continue
        # flush previous multiline
        if current_key and multiline_buffer:
            meta[current_key] = ' '.join(multiline_buffer).strip()
            multiline_buffer = []
            current_key = None
        if ':' in raw_line:
            k, v = raw_line.split(':', 1)
            k = k.strip()
            v = v.strip()
            # Remove surrounding quotes if present
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            meta[k] = v
            current_key = k
        else:
            # line without colon – ignore (could be malformed)
            continue
    if current_key and multiline_buffer:
        meta[current_key] = ' '.join(multiline_buffer).strip()
    return meta, body


def _fallback_minimal_item(p: Path):
    """Attempt to extract a minimal title (and maybe crude activity/peak) if frontmatter parsing fails.

    Strategy:
    - Read raw text
    - Strip BOM
    - Remove a malformed leading front matter block if present (--- ... ---) without parsing
    - Use first non-empty, non-delimiter line as title (strip leading '#' or list bullet) preserving original case
    - Try to find Peak/Area and Activity/Style lines heuristically
    """
    try:
        raw = p.read_text(encoding='utf-8', errors='replace').lstrip('\ufeff').strip()
    except Exception:
        return {'id': p.stem}
    if not raw:
        return {'id': p.stem}
    # Remove malformed front matter quickly if it obviously starts with '---' *and* contains another '---' later.
    if raw.startswith('---'):
        parts = raw.split('---', 2)
        if len(parts) > 2:
            raw = parts[2].strip()
    lines = [l.strip() for l in raw.splitlines()]
    # Derive title
    title = p.stem
    for l in lines:
        if not l:
            continue
        if l.startswith('---'):
            # skip stray delimiter lines
            continue
        # Trim markdown heading markers & list bullets
        cleaned = l.lstrip('#').lstrip('*').lstrip('-').strip()
        if cleaned:
            title = cleaned
            break
    peak = ''
    activity = ''
    for l in lines:
        m = _PEAK_RE.match(l)
        if m:
            peak = m.group(1).strip()
            break
    for l in lines:
        m = _ACTIVITY_RE.match(l)
        if m:
            activity = m.group(1).strip()
            break
    return {
        'id': p.stem,
        'title': title,
        'peak': peak,
        'date_of_event': '',
        'date': '',
        'activity': activity,
    }


def scan_reports():
    out = []
    if not REPORTS_DIR.exists():
        return out
    for p in sorted(REPORTS_DIR.glob('*.md')):
        try:
            try:
                fm = frontmatter.load(p)
                meta = fm.metadata or {}
                body = fm.content or ''
            except Exception as yaml_err:
                # Attempt lenient parse before giving up
                meta, body = _load_frontmatter_lenient(p)
                if meta is None:
                    raise yaml_err
            peak = meta.get('peak') or ''
            if not peak:
                # search body lines
                for line in body.splitlines():
                    raw_line = line.strip()
                    if not raw_line:
                        continue
                    if raw_line.startswith('- ') or raw_line.startswith('* '):
                        raw_line = raw_line[2:].strip()
                    m = _PEAK_RE.match(raw_line)
                    if m:
                        peak = m.group(1).strip()
                        break
            activity = ''
            for line in body.splitlines():
                raw_line = line.strip()
                if not raw_line:
                    continue
                if raw_line.startswith('- ') or raw_line.startswith('* '):
                    raw_line = raw_line[2:].strip()
                m = _ACTIVITY_RE.match(raw_line)
                if m:
                    activity = m.group(1).strip()
                    break
            if not activity:
                activity = meta.get('activity') or meta.get('audience') or ''

            date_of_event_val = meta.get('date_of_event') or meta.get('date') or ''
            try:
                if hasattr(date_of_event_val, 'isoformat'):
                    date_of_event_val = date_of_event_val.isoformat()
            except Exception:
                date_of_event_val = str(date_of_event_val)

            title = meta.get('title') or ''
            if not title:
                # fallback to first heading in body
                for l in body.splitlines():
                    stripped = l.strip()
                    if not stripped:
                        continue
                    if stripped.startswith('#'):
                        title = stripped.lstrip('#').strip()
                        break
                if not title:
                    title = p.stem

            item = {
                'id': p.stem,
                'title': title,
                'peak': peak,
                'date_of_event': str(date_of_event_val) if date_of_event_val is not None else '',
                'date': str(date_of_event_val) if date_of_event_val is not None else '',
                'activity': activity,
            }
            out.append(item)
        except Exception as e:  # noqa: BLE001
            # Log warning and attempt deeper fallback extraction
            print(f"[WARN] Failed to parse front matter for {p.name}: {e}", file=sys.stderr)
            # Optionally include stack for debugging noisy parse issues
            if os.getenv('LIST_BUILDER_DEBUG') == '1':
                traceback.print_exc()
            out.append(_fallback_minimal_item(p))
    # Post-filter: ensure at least title present; if missing, attempt fallback again
    cleaned = []
    for item in out:
        if 'title' not in item or not item.get('title'):
            # Try to enrich
            enriched = _fallback_minimal_item(REPORTS_DIR / f"{item['id']}.md")
            # Merge keeping any existing values
            merged = {**enriched, **item}
            if not merged.get('title'):
                merged['title'] = merged['id']
            cleaned.append(merged)
        else:
            cleaned.append(item)
    return cleaned


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--upload', action='store_true', help='Upload to GCS_BUCKET')
    ap.add_argument('--bucket', help='Explicit bucket name (overrides GCS_BUCKET env)')
    args = ap.parse_args()

    items = scan_reports()
    # Optionally drop entries that somehow are still only id (should be rare now)
    filtered = [it for it in items if any(k for k in ('title','activity','peak') if it.get(k))]
    if len(filtered) != len(items):
        print(f"[WARN] Dropped {len(items)-len(filtered)} empty items from manifest", file=sys.stderr)
    data = filtered
    out_path = Path('/tmp/list.json')
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {out_path} ({len(data)} items)')

    if args.upload:
        bucket = args.bucket or os.environ.get('GCS_BUCKET')
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
