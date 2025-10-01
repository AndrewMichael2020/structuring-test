#!/usr/bin/env python3
"""Inspect artifacts DB (SQLite) and print results.

Usage examples:
    python scripts/inspect_db.py --db artifacts.db --limit 20
    python scripts/inspect_db.py --db artifacts.db --filter domain=apnews.com
"""
import argparse
import json
from store_artifacts import init_db, query_artifacts
from pathlib import Path


def parse_filters(filter_list):
    out = {}
    if not filter_list:
        return out
    for f in filter_list:
        if '=' in f:
            k, v = f.split('=', 1)
            out[k] = v
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='artifacts.db', help='DB path (sqlite)')
    p.add_argument('--backend', choices=['sqlite', 'auto'], default='auto')
    p.add_argument('--limit', type=int, default=50)
    p.add_argument('--filter', '-f', action='append', help='filter expressions like domain=apnews.com')
    p.add_argument('--json', action='store_true', help='print JSON blobs only')
    args = p.parse_args()

    db_path = Path(args.db)
    # decide backend: if user asked auto, infer from extension
    if args.backend == 'auto':
        if db_path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
            backend = 'sqlite'
        else:
            backend = 'sqlite'
    else:
        backend = args.backend

    init_db(str(db_path), backend=backend)
    filters = parse_filters(args.filter)

    # For sqlite, query_artifacts expects filters or will try to call .all() on the connection.
    # Import internal DB state to handle sqlite safely.
    from store_artifacts import _DB_TYPE, _DB
    if _DB_TYPE == 'sqlite':
        cur = _DB.cursor()
        if filters:
            cols = []
            vals = []
            for k, v in filters.items():
                cols.append(f"{k} = ?")
                vals.append(v)
            where = ' AND '.join(cols)
            q = f"SELECT * FROM artifacts WHERE {where}"
            cur.execute(q, tuple(vals))
        else:
            cur.execute("SELECT * FROM artifacts ORDER BY ts DESC LIMIT ?", (args.limit,))
        rows = cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get('artifact_json'):
                try:
                    d['artifact'] = json.loads(d['artifact_json'])
                except Exception:
                    d['artifact'] = d.get('artifact_json')
            results.append(d)
    else:
        results = query_artifacts(filters if filters else None)

    if args.json:
        print(json.dumps(results[: args.limit], indent=2, ensure_ascii=False))
        return

    # pretty table-ish printing
    for r in results[: args.limit]:
        src = r.get('source_url') or r.get('source') or ''
        domain = r.get('domain', '')
        ts = r.get('ts', '')
        fatalities = r.get('num_fatalities', r.get('artifact', {}).get('num_fatalities'))
        conf = r.get('extraction_confidence_score', r.get('artifact', {}).get('extraction_confidence_score'))
        print(f"{ts:20} | {domain:20} | fatalities={str(fatalities):3} | conf={str(conf):4} | {src}")
    print(f"\nPrinted {min(len(results), args.limit)} of {len(results)} results")


if __name__ == '__main__':
    main()
