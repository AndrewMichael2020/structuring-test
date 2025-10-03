#!/usr/bin/env python3
"""CI sanity checks for generated accident reports and manifest.

Exit codes:
 0 success
 1 failure

Checks:
 - Parse every markdown in events/reports/*.md
 - Front matter MUST contain: title, event_id
 - Optional keys allowed: date_of_event, region, audience, area
 - No unexpected keys (fail)
 - event_id uniqueness (fail on duplicates)
 - list.json (if present at reports/list.json OR reports/list.json in repo root bucket mimic):
     * Accept either array or object {reports: [...]} shape
     * Count alignment (if object.count present matches len(reports))
     * Each report id has corresponding markdown file

Warn (do not fail):
 - Missing region or date_of_event
 - Missing manifest file entirely

Environment:
  CI_STRICT_REGION=1  -> escalate empty region to failure
  CI_STRICT_DATE=1    -> escalate missing date_of_event to failure

"""
from __future__ import annotations
import json, sys, re
from pathlib import Path
import hashlib

REPORTS_DIR = Path('events/reports')
MANIFEST_PATHS = [Path('reports/list.json'), REPORTS_DIR / 'list.json']
REQUIRED = {'title', 'event_id'}
OPTIONAL = {'date_of_event', 'region', 'audience', 'area'}
ALLOWED = REQUIRED | OPTIONAL

STRICT_REGION = (Path('.').joinpath('.').exists() and ("1" == (os.getenv('CI_STRICT_REGION','0')))) if False else (os.getenv('CI_STRICT_REGION','0') in ('1','true','yes'))
STRICT_DATE = os.getenv('CI_STRICT_DATE','0') in ('1','true','yes')

errors: list[str] = []
warnings: list[str] = []

# Collect markdown reports
if not REPORTS_DIR.exists():
    warnings.append(f"Reports dir missing: {REPORTS_DIR}")
    # still continue; maybe no reports yet

md_files = sorted(p for p in REPORTS_DIR.glob('*.md') if p.is_file())
seen_ids: dict[str, Path] = {}

fm_pattern = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)

for md in md_files:
    txt = md.read_text(encoding='utf-8', errors='replace')
    m = fm_pattern.match(txt)
    if not m:
        errors.append(f"Front matter missing in {md}")
        continue
    block = m.group(1)
    meta = {}
    for line in block.splitlines():
        if not line.strip():
            continue
        if ':' not in line:
            errors.append(f"Malformed front matter line in {md}: {line!r}")
            continue
        k, v = line.split(':', 1)
        meta[k.strip()] = v.strip()
    missing = REQUIRED - meta.keys()
    if missing:
        errors.append(f"Missing required keys {missing} in {md}")
    extra = set(meta.keys()) - ALLOWED
    if extra:
        errors.append(f"Unexpected keys {extra} in {md}")
    eid = meta.get('event_id')
    if eid:
        if eid in seen_ids:
            errors.append(f"Duplicate event_id {eid} in {md} and {seen_ids[eid]}")
        else:
            seen_ids[eid] = md
    else:
        errors.append(f"event_id missing value in {md}")
    # Soft validations
    if not meta.get('region'):
        msg = f"Region empty in {md}"
        if STRICT_REGION:
            errors.append(msg)
        else:
            warnings.append(msg)
    if not meta.get('date_of_event'):
        msg = f"date_of_event empty in {md}"
        if STRICT_DATE:
            errors.append(msg)
        else:
            warnings.append(msg)

# Manifest validation
manifest_path = None
manifest_data = None
for cand in MANIFEST_PATHS:
    if cand.exists():
        manifest_path = cand
        break

if manifest_path:
    try:
        manifest_data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except Exception as e:
        errors.append(f"Failed to parse manifest {manifest_path}: {e}")
else:
    warnings.append("Manifest list.json not found (skipping manifest checks)")

manifest_ids: list[str] = []
if manifest_data is not None:
    if isinstance(manifest_data, list):
        manifest_ids = [str(x.get('id')) for x in manifest_data if isinstance(x, dict) and 'id' in x]
    elif isinstance(manifest_data, dict):
        reports = manifest_data.get('reports')
        if isinstance(reports, list):
            manifest_ids = [str(x.get('id')) for x in reports if isinstance(x, dict) and 'id' in x]
            declared_count = manifest_data.get('count')
            if isinstance(declared_count, int) and declared_count != len(reports):
                errors.append(f"Manifest count {declared_count} != len(reports) {len(reports)}")
        else:
            errors.append("Manifest object missing 'reports' list")
    else:
        errors.append(f"Manifest root must be array or object, got {type(manifest_data)}")

    # cross-verify each id has md file
    for mid in manifest_ids:
        if not (REPORTS_DIR / f"{mid}.md").exists():
            errors.append(f"Manifest references missing report markdown: {mid}.md")

# Summary
print(f"Checked {len(md_files)} markdown reports; manifest ids={len(manifest_ids)} unique_ids={len(seen_ids)}")
if warnings:
    print("Warnings:")
    for w in warnings:
        print(f"  - {w}")
if errors:
    print("Errors:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("ci_check_reports: PASS")
