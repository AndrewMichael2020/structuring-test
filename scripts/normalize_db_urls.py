"""Normalize artifacts.db source_url and domain where source_url is not a canonical URL.

For each row in artifacts:
- If source_url starts with http(s)://, skip.
- Else, try to parse artifact_json and look for a valid URL in common fields: artifact_json.get('source_url'), artifact_json.get('related_articles_urls') etc.
- If a candidate URL is found, UPDATE the row's source_url and domain, and record the change in a backup JSON file.

Run: python scripts/normalize_db_urls.py
"""
import sqlite3
import json
import re
from urllib.parse import urlparse
from pathlib import Path
from datetime import datetime

DB = 'artifacts.db'
backup = []

url_re = re.compile(r'https?://[^\s\"\'>)]+')

def parse_iso(dt_str):
    try:
        return datetime.fromisoformat(dt_str.replace('Z','+00:00'))
    except Exception:
        return None

def find_candidate_in_artifacts(db_art):
    """Search artifacts/*/*/accident_info.json for a matching artifact by simple heuristics."""
    mount = db_art.get('mountain_name')
    fatalities = db_art.get('num_fatalities')
    conf = db_art.get('extraction_confidence_score')
    extracted_at = db_art.get('extracted_at')
    cand = None
    best_score = 0
    for p in Path('artifacts').rglob('accident_info.json'):
        try:
            a = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        score = 0
        if mount and a.get('mountain_name') and mount.lower() == str(a.get('mountain_name')).lower():
            score += 3
        if fatalities is not None and a.get('num_fatalities') is not None and int(fatalities) == int(a.get('num_fatalities')):
            score += 2
        if conf is not None and a.get('extraction_confidence_score') is not None:
            try:
                if abs(float(conf) - float(a.get('extraction_confidence_score'))) < 0.1:
                    score += 1
            except Exception:
                pass
        # timestamp proximity
        try:
            db_t = parse_iso(extracted_at) if extracted_at else None
            a_t = parse_iso(a.get('extracted_at')) if a.get('extracted_at') else None
            if db_t and a_t:
                delta = abs((db_t - a_t).total_seconds())
                if delta < 300:
                    score += 2
                elif delta < 3600:
                    score += 1
        except Exception:
            pass
        if score > best_score:
            best_score = score
            cand = (a, p)
    return cand, best_score

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT source_url, domain, artifact_json FROM artifacts')
rows = cur.fetchall()
updates = 0
for r in rows:
    src = r['source_url']
    if isinstance(src, str) and src.lower().startswith(('http://','https://')):
        continue
    # try to parse artifact_json
    cand = None
    try:
        a = json.loads(r['artifact_json'] or '{}')
    except Exception:
        a = {}

    # first, look for obvious URL fields inside the JSON
    for key in ('source_url','related_articles_urls','photo_urls','video_urls'):
        v = a.get(key)
        if isinstance(v, str) and v.lower().startswith(('http://','https://')):
            cand = v
            break
        if isinstance(v, list):
            for it in v:
                if isinstance(it, str) and it.lower().startswith(('http://','https://')):
                    cand = it
                    break
            if cand:
                break

    # fallback: regex search whole JSON string
    if not cand:
        s = json.dumps(a)
        m = url_re.search(s)
        if m:
            cand = m.group(0)

    # if still not found, try to locate matching artifact files
    artifact_path = None
    if not cand:
        matched, score = find_candidate_in_artifacts(a)
        if matched and score >= 3:
            matched_art, matched_path = matched
            artifact_path = matched_path
            cand_from_matched = matched_art.get('source_url')
            if isinstance(cand_from_matched, str) and cand_from_matched.lower().startswith(('http://','https://')):
                cand = cand_from_matched
            else:
                # no http source_url in matched artifact; we'll use matched path to derive domain
                cand = None

    # prepare update values
    new_source = None
    new_domain = None
    if cand:
        parsed = urlparse(cand)
        new_source = cand
        new_domain = parsed.netloc
    elif artifact_path:
        # derive domain from artifact path: artifacts/<domain>/<ts>/accident_info.json
        try:
            new_domain = artifact_path.parent.parent.name
        except Exception:
            new_domain = None

    if not new_source and not new_domain:
        # nothing to update
        continue

    # backup
    backup.append({'old_source_url': src, 'new_source_url': new_source or src, 'old_domain': r['domain'], 'new_domain': new_domain})
    # only update fields that changed
    try:
        if new_source and new_domain:
            cur.execute('UPDATE artifacts SET source_url = ?, domain = ? WHERE source_url = ?', (new_source, new_domain, src))
        elif new_domain and not new_source:
            cur.execute('UPDATE artifacts SET domain = ? WHERE source_url = ?', (new_domain, src))
        updates += 1
    except Exception as e:
        print('Failed to update', src, '->', cand, e)

conn.commit()
conn.close()

with open('scripts/normalize_db_urls.backup.json','w',encoding='utf-8') as f:
    json.dump({'updated': updates, 'changes': backup}, f, indent=2)

print('done, updated', updates)
