from pathlib import Path
from typing import Optional, Dict, Any, Iterable
import json
import os
import glob
import csv

# Local CSV path - this is now the primary output
_LOCAL_CSV_PATH = os.environ.get("ARTIFACTS_CSV_LOCAL_PATH", "artifacts/artifacts.csv")

# Canonical artifact fields we prefer to expose as top-level CSV columns.
# Order here will be used as the CSV header order (others appended afterwards).
CANONICAL_ARTIFACT_FIELDS = [
    "extracted_at",
    "source_url",
    "article_text",
    "scraped_full_text",

    "source_name",
    "article_title",
    "article_date_published",

    "region",
    "mountain_name",
    "route_name",
    "activity_type",
    "accident_type",
    "accident_date",
    "accident_time_approx",

    "num_people_involved",
    "num_fatalities",
    "num_injured",
    "num_rescued",

    "people",

    "rescue_teams_involved",
    "response_agencies",

    "rescue_method",
    "response_difficulties",
    "bodies_recovery_method",

    "accident_summary_text",
    "timeline_text",

    "quoted_dialogue",
    "notable_equipment_details",
    "local_expert_commentary",
    "family_statements",

    "photo_urls",
    "video_urls",
    "related_articles_urls",
    "fundraising_links",
    "official_reports_links",

    "fall_height_meters_estimate",
    "self_rescue_boolean",
    "anchor_failure_boolean",
    "extraction_confidence_score",
]


def _read_local_csv(path: str) -> Dict[str, Dict]:
    """Read existing CSV into dict keyed by source_url. Returns empty dict if missing."""
    out = {}
    p = Path(path)
    if not p.exists():
        return out
    try:
        with p.open("r", encoding="utf-8") as fh:
            import csv as _csv

            reader = _csv.DictReader(fh)
            for r in reader:
                key = r.get("source_url")
                if key:
                    out[key] = r
    except Exception:
        # best-effort: ignore read errors
        return {}
    return out


def _write_local_csv(path: str, rows: Iterable[Dict[str, object]], fieldnames: Iterable[str] | None = None):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # infer fieldnames
    rows = list(rows)
    if not rows:
        return
    if fieldnames is None:
        # combine canonical fields first, then any extra keys found in rows
        extras = sorted({k for r in rows for k in r.keys() if k not in CANONICAL_ARTIFACT_FIELDS})
        fieldnames = list(CANONICAL_ARTIFACT_FIELDS) + extras
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = __import__("csv").DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            out_row = {}
            for k in fieldnames:
                v = r.get(k)
                # serialize lists/dicts into compact JSON strings for CSV cells
                if isinstance(v, (list, dict)):
                    try:
                        out_row[k] = json.dumps(v, ensure_ascii=False)
                    except Exception:
                        out_row[k] = str(v)
                elif v is None:
                    out_row[k] = ""
                else:
                    # normalize long text fields to single-line to avoid breaking CSV rows
                    if isinstance(v, str) and k in ("article_text", "scraped_full_text"):
                        # remove newlines and collapse whitespace
                        out_row[k] = " ".join(v.split())
                    else:
                        out_row[k] = str(v)
            writer.writerow(out_row)


def _rebuild_local_csv():
    """Rebuild the local CSV from on-disk artifact JSON files.

    This function is best-effort and will not raise on errors.
    """
    # Rebuild the canonical CSV from on-disk artifact JSON files so columns
    # reliably map to JSON fields.
    existing = {}
    
    # helper to choose newest by extracted_at/ts
    def _is_newer(ts_new: str | None, ts_old: str | None) -> bool:
        if not ts_old:
            return True
        if not ts_new:
            return False
        # Try ISO comparison; fall back to lexicographic which works for most ISO strings
        try:
            from datetime import datetime
            def _parse(t: str):
                # Normalize 'Z' to +00:00 for fromisoformat
                t = t.replace('Z', '+00:00')
                return datetime.fromisoformat(t)
            return _parse(ts_new) > _parse(ts_old)
        except Exception:
            try:
                return str(ts_new) > str(ts_old)
            except Exception:
                return False
    
    try:
        # look for all accident_info.json files under artifacts/*/*
        for path in glob.glob(os.path.join('artifacts', '*', '*', 'accident_info.json')):
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    a = json.load(fh)
            except Exception:
                continue
            src = a.get('source_url') or ''
            domain = ''
            try:
                domain = src.split('/')[2]
            except Exception:
                domain = ''
            rec_row = {}
            for k in CANONICAL_ARTIFACT_FIELDS:
                rec_row[k] = a.get(k)
            rec_row['domain'] = domain
            rec_row['source_url'] = src
            rec_row['ts'] = a.get('extracted_at')
            try:
                rec_row['artifact_json'] = json.dumps(a, ensure_ascii=False)
            except Exception:
                rec_row['artifact_json'] = ''
            # Keep the newest record per source_url
            prev = existing.get(src)
            if not prev or _is_newer(rec_row.get('ts'), prev.get('ts')):
                existing[src] = rec_row
    except Exception:
        # fallback to reading the existing CSV if glob fails
        existing = _read_local_csv(_LOCAL_CSV_PATH)

    if not existing:
        # No artifacts to write; skip CSV creation
        return

    # Build a stable set of fieldnames: canonical fields first, then any extras
    all_keys = set()
    for r in existing.values():
        all_keys.update(r.keys())
    # Exclude metadata keys from extras to avoid duplication later
    metadata_keys = {'domain', 'source_url', 'ts', 'artifact_json'}
    extras = [k for k in sorted(all_keys) if k not in CANONICAL_ARTIFACT_FIELDS and k not in metadata_keys]

    # Build CSV fieldnames with metadata and count columns
    csv_fieldnames = list(CANONICAL_ARTIFACT_FIELDS) + extras + ['domain', 'source_url', 'ts', 'artifact_json']
    csv_fieldnames += ['people_count', 'rescue_teams_count']
    for key in ('photo_urls', 'video_urls', 'related_articles_urls', 'fundraising_links', 'official_reports_links'):
        csv_fieldnames.append(f'{key}_count')

    normalized_rows = []
    for src, r in existing.items():
        # ensure artifact_json is present for consumers
        if not r.get('artifact_json'):
            try:
                r['artifact_json'] = json.dumps(r.get('artifact') or {}, ensure_ascii=False)
            except Exception:
                r['artifact_json'] = ''

        # compute counts for list fields
        def _count_field(val):
            if isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, list):
                        return len(parsed)
                    return 0
                except Exception:
                    return 0
            if isinstance(val, list):
                return len(val)
            return 0

        r['people_count'] = _count_field(r.get('people'))
        r['rescue_teams_count'] = _count_field(r.get('rescue_teams_involved'))
        for key in ('photo_urls', 'video_urls', 'related_articles_urls', 'fundraising_links', 'official_reports_links'):
            r[f'{key}_count'] = _count_field(r.get(key))

        normalized_rows.append(r)

    # write local CSV using the explicit csv_fieldnames (includes artifact_json and counts)
    try:
        _write_local_csv(_LOCAL_CSV_PATH, normalized_rows, fieldnames=csv_fieldnames)
    except Exception:
        # ensure we at least attempt to write an empty CSV header to avoid stale copies
        try:
            _write_local_csv(_LOCAL_CSV_PATH, [], fieldnames=csv_fieldnames)
        except Exception:
            pass


def init_db(path: str | Path = "artifacts.db", backend: str | None = None) -> None:
    """Initialize the DB backend (no-op for local CSV-only mode).
    
    This function is kept for backwards compatibility but does nothing
    in the local CSV-only mode.
    """
    # No-op: DB functionality has been removed
    pass


def close_db():
    """Close the DB (no-op for local CSV-only mode)."""
    # No-op: DB functionality has been removed
    pass


def upsert_artifact(doc: Dict[str, Any]) -> None:
    """Upsert an artifact document (no-op for local CSV-only mode).
    
    In local CSV mode, artifacts are written directly to disk as JSON files
    and the CSV is rebuilt from those files on demand.
    
    doc: the artifact payload (should contain 'source_url' and 'extracted_at')
    """
    # No-op: DB functionality has been removed
    # The CSV will be rebuilt from on-disk JSON artifacts when needed
    pass


def query_artifacts(filters: Dict[str, Any] | None = None):
    """Query artifacts (no-op for local CSV-only mode, returns empty list).
    
    In local CSV mode, you should read artifacts from the CSV file directly
    or from the on-disk JSON artifacts.
    """
    # No-op: DB functionality has been removed
    return []


def force_rebuild_artifacts_csv(local_csv_path: str = None) -> str:
    """Force a deterministic rebuild of the artifacts CSV from on-disk JSON artifacts.
    
    Args:
        local_csv_path: Optional path for the CSV file. Defaults to artifacts/artifacts.csv
        
    Returns:
        Path to the generated CSV file
    """
    global _LOCAL_CSV_PATH
    if local_csv_path:
        _LOCAL_CSV_PATH = local_csv_path
    
    try:
        _rebuild_local_csv()
    except Exception:
        pass
    
    return _LOCAL_CSV_PATH


# Backwards compatibility alias
def force_rebuild_and_upload_artifacts_csv():
    """Force a deterministic rebuild of the artifacts CSV (Drive upload removed)."""
    return force_rebuild_artifacts_csv()
