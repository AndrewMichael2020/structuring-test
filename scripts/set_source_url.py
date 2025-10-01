#!/usr/bin/env python3
"""Set or correct a source_url in artifacts.db.

Usage:
  scripts/set_source_url.py --old-url <OLD> --new-url <NEW> [--db PATH] [--backup PATH] [--dry-run]
  scripts/set_source_url.py --artifact-path <ART_PATH> --new-url <NEW> [--db PATH] [--backup PATH] [--dry-run]

This script updates the `artifacts` table's `source_url` and `domain` fields. It writes a small JSON backup of the change.
"""
import argparse
import sqlite3
import json
from urllib.parse import urlparse
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description='Update artifact source_url in artifacts.db')
grp = parser.add_mutually_exclusive_group(required=True)
grp.add_argument('--old-url', help='Existing (current) source_url value to replace')
grp.add_argument('--artifact-path', help='Path to artifact dir containing accident_info.json')
parser.add_argument('--new-url', required=True, help='New canonical source URL (must be http/https)')
parser.add_argument('--db', default='artifacts.db', help='Path to sqlite DB')
parser.add_argument('--backup', default='scripts/set_source_url.backup.json', help='Backup JSON path')
parser.add_argument('--dry-run', action='store_true')
args = parser.parse_args()

if not args.new_url.lower().startswith(('http://','https://')):
    print('ERROR: --new-url must be an http(s) URL')
    sys.exit(2)

new_domain = urlparse(args.new_url).netloc

con = sqlite3.connect(args.db)
con.row_factory = sqlite3.Row
cur = con.cursor()

# figure target old_source
old_source = None
if args.old_url:
    old_source = args.old_url
else:
    p = Path(args.artifact_path)
    if not p.exists():
        print('ERROR: artifact path not found:', args.artifact_path)
        sys.exit(2)
    ai = p / 'accident_info.json'
    if not ai.exists():
        print('ERROR: accident_info.json not found in', p)
        sys.exit(2)
    # try to read its source_url
    try:
        a = json.loads(ai.read_text(encoding='utf-8'))
        found = a.get('source_url')
        if not found:
            print('artifact JSON has no source_url; will use artifact path to find row')
            old_source = None
        else:
            old_source = found
    except Exception as e:
        print('ERROR reading artifact json:', e)
        sys.exit(2)

# look up by old_source if provided
row = None
if old_source:
    cur.execute('SELECT source_url, domain, artifact_json FROM artifacts WHERE source_url = ?', (old_source,))
    row = cur.fetchone()
else:
    # try to match by artifact_json contents (mountain_name + ts) or by artifact path domain
    # first, attempt to parse artifact JSON and search by title/extracted_at
    try:
        a = json.loads((Path(args.artifact_path) / 'accident_info.json').read_text(encoding='utf-8'))
    except Exception:
        a = {}
    title = a.get('article_title')
    extracted_at = a.get('extracted_at')
    if title or extracted_at:
        q = 'SELECT source_url, domain, artifact_json FROM artifacts WHERE 1=1'
        params = []
        if title:
            q += " AND json_extract(artifact_json, '$.article_title') = ?"
            params.append(title)
        if extracted_at:
            q += " AND json_extract(artifact_json, '$.extracted_at') = ?"
            params.append(extracted_at)
        cur.execute(q, params)
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
        elif len(rows) > 1:
            print('Multiple DB rows match artifact JSON; please use --old-url to disambiguate')
            for r in rows:
                print(' -', r['source_url'], 'domain=', r['domain'])
            sys.exit(2)
    if row is None:
        # fallback: derive domain from artifact path and try to find a row with that domain and similar extracted_at
        try:
            domain_from_path = Path(args.artifact_path).parts[-2]
        except Exception:
            domain_from_path = None
        if domain_from_path:
            cur.execute('SELECT source_url, domain, artifact_json FROM artifacts WHERE domain = ? LIMIT 1', (domain_from_path,))
            row = cur.fetchone()

if not row:
    print('No matching DB row found for the given artifact / old-url')
    sys.exit(1)

old = row['source_url']
old_domain = row['domain']

print('Found DB row:')
print('  source_url:', old)
print('  domain    :', old_domain)
print('  new source:', args.new_url)
print('  new domain :', new_domain)

backup = {'old_source_url': old, 'old_domain': old_domain, 'new_source_url': args.new_url, 'new_domain': new_domain}

if args.dry_run:
    print('Dry run; not modifying DB. Backup would be:')
    print(json.dumps(backup, indent=2))
    sys.exit(0)

# perform update
try:
    cur.execute('UPDATE artifacts SET source_url = ?, domain = ? WHERE source_url = ?', (args.new_url, new_domain, old))
    con.commit()
    print('Updated DB row: set source_url ->', args.new_url)
    Path(args.backup).write_text(json.dumps(backup, indent=2), encoding='utf-8')
    print('Wrote backup to', args.backup)
except Exception as e:
    print('Failed to update DB:', e)
    sys.exit(1)

con.close()
