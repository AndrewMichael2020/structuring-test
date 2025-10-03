#!/usr/bin/env python3
"""Check a deployed Accident Reports Cloud Run service for non-empty report list.

Usage:
  python scripts/check_cloud_run_reports.py --base https://your-service-xyz.run.app [--expect-min 1]

Exit codes:
 0 success
 1 error (network / HTTP / empty list below threshold)
"""
from __future__ import annotations
import argparse, json, sys, urllib.request, urllib.error

def fetch(url: str, timeout: int = 15):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.getcode(), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace') if e.fp else ''
    except Exception as e:
        return None, str(e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='Base URL of deployed service e.g. https://accident-reports-frontend-xyz.a.run.app')
    ap.add_argument('--expect-min', type=int, default=1, help='Minimum number of reports expected')
    ap.add_argument('--sample-index', type=int, default=0, help='Index of report to sample fetch')
    args = ap.parse_args()

    base = args.base.rstrip('/')
    list_url = f"{base}/api/reports/list"
    code, body = fetch(list_url)
    if code != 200:
        print(f"ERROR: list endpoint status={code} body-prefix={body[:200]!r}")
        sys.exit(1)

    try:
        data = json.loads(body)
    except Exception as e:
        print(f"ERROR: failed to parse JSON from list endpoint: {e} body-prefix={body[:120]!r}")
        sys.exit(1)

    # Accept both shapes
    if isinstance(data, list):
        reports = data
    elif isinstance(data, dict) and isinstance(data.get('reports'), list):
        reports = data['reports']
    else:
        print(f"ERROR: unexpected list shape: keys={list(data) if isinstance(data, dict) else type(data)}")
        sys.exit(1)

    n = len(reports)
    print(f"OK: fetched {n} reports from {list_url}")
    if n < args.expect_min:
        print(f"ERROR: report count {n} < expected minimum {args.expect_min}")
        sys.exit(1)

    if n and 0 <= args.sample_index < n:
        rid = reports[args.sample_index].get('id')
        if rid:
            rep_url = f"{base}/api/reports/{rid}"
            rcode, rbody = fetch(rep_url)
            if rcode != 200:
                print(f"ERROR: sample report {rid} status={rcode} body-prefix={rbody[:160]!r}")
                sys.exit(1)
            try:
                rep = json.loads(rbody)
                title = rep.get('meta', {}).get('title') or rep.get('content_markdown','')[:60]
                print(f"OK: sample report {rid} fetched (title/preview: {title!r})")
            except Exception as e:
                print(f"ERROR: parsing sample report JSON failed: {e}")
                sys.exit(1)

    print('SUCCESS: Cloud Run service appears healthy.')

if __name__ == '__main__':
    main()
