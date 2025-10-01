from pathlib import Path
from typing import Optional, Dict, Any, Iterable
import json
import os
import sqlite3
import glob
import io
import csv

Query = None


class _InMemoryDB:
    def __init__(self, path: str | Path = None):
        self._data = []

    def insert(self, doc: dict):
        self._data.append(doc)

    def update(self, doc: dict, cond):
        # cond is a tuple ('source_url', value) expected; support simple equality
        if callable(cond):
            for i, d in enumerate(self._data):
                if cond(d):
                    self._data[i].update(doc)
        else:
            # best-effort: find matching source_url
            key = 'source_url'
            val = None
            try:
                val = cond
            except Exception:
                val = None
            if val is not None:
                for i, d in enumerate(self._data):
                    if d.get(key) == val:
                        self._data[i].update(doc)

    def search(self, predicate):
        # predicate may be a callable or a dict-like simple equality
        if predicate is None:
            return list(self._data)
        if callable(predicate):
            return [d for d in self._data if predicate(d)]
        # fallback: if predicate is dict, match every k==v
        if isinstance(predicate, dict):
            out = []
            for d in self._data:
                ok = True
                for k, v in predicate.items():
                    if d.get(k) != v:
                        ok = False
                        break
                if ok:
                    out.append(d)
            return out
        return []

    def all(self):
        return list(self._data)

    def close(self):
        self._data = []


_DB: Optional[object] = None
_DB_TYPE: Optional[str] = None  # 'sqlite' or 'memory'

# Drive sync globals (lazy)
_DRIVE_STORAGE = None
_DRIVE_FOLDER_ID = os.environ.get("DRIVE_FOLDER_ID")
_DRIVE_FILENAME = os.environ.get("DRIVE_ARTIFACTS_FILENAME", "artifacts.csv")
_LOCAL_CSV_PATH = os.environ.get("ARTIFACTS_CSV_LOCAL_PATH", "artifacts/artifacts.csv")

# Configurable expansion sizes (environment variables, defaults kept small to avoid huge spreadsheets)
try:
    ARTIFACTS_MAX_PEOPLE = max(1, int(os.getenv('ARTIFACTS_MAX_PEOPLE', '5')))
except Exception:
    ARTIFACTS_MAX_PEOPLE = 5
try:
    ARTIFACTS_MAX_TEAMS = max(1, int(os.getenv('ARTIFACTS_MAX_TEAMS', '5')))
except Exception:
    ARTIFACTS_MAX_TEAMS = 5
try:
    ARTIFACTS_MAX_URLS = max(1, int(os.getenv('ARTIFACTS_MAX_URLS', '5')))
except Exception:
    ARTIFACTS_MAX_URLS = 5

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


def _drive_configured() -> bool:
    # Consider Drive configured if either a service account key or an
    # OAuth client secret is present (or an existing token file is present).
    if os.environ.get("DRIVE_SERVICE_ACCOUNT_JSON"):
        return True
    if os.environ.get("DRIVE_OAUTH_CLIENT_SECRETS"):
        return True
    # Also check for an existing token file path in env
    token = os.environ.get("DRIVE_OAUTH_TOKEN_PATH", ".credentials/drive_token.json")
    if os.path.exists(token):
        return True
    return False


def _get_drive_storage():
    """Lazily build a DriveStorage instance from env var. Returns None if not configured."""
    global _DRIVE_STORAGE
    if not _drive_configured():
        return None
    if _DRIVE_STORAGE is not None:
        return _DRIVE_STORAGE
    try:
        # import here to avoid hard dependency unless feature used
        from drive_storage import DriveStorage

        # DriveStorage.from_env will read .env and token files as needed
        _DRIVE_STORAGE = DriveStorage.from_env()
        return _DRIVE_STORAGE
    except Exception:
        return None


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


def _maybe_sync_to_drive(rec: Dict[str, Any]):
    """If Drive is configured, update the local CSV and upload/replace on Drive.

    This function is best-effort and will not raise on errors.
    """
    # Always update the local CSV mirror first (best-effort). Then attempt
    # Drive upload only if the Drive client is available.
    try:
        # Instead of relying on the possibly-inconsistent local CSV, rebuild
        # the canonical CSV from all on-disk artifact JSON files so columns
        # reliably map to JSON fields.
        existing = {}
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
                existing[src] = rec_row
        except Exception:
            # fallback to reading the existing CSV if glob fails
            existing = _read_local_csv(_LOCAL_CSV_PATH)
        # Normalize record into CSV-friendly row by flattening the artifact payload
        artifact = rec.get("artifact") if isinstance(rec.get("artifact"), dict) else {}
        # Compose a canonical row where keys align with CANONICAL_ARTIFACT_FIELDS
        row = {}
        for k in CANONICAL_ARTIFACT_FIELDS:
            # prefer artifact-level values, fall back to top-level rec metadata
            if isinstance(artifact.get(k), (list, dict)):
                row[k] = artifact.get(k)
            elif k in artifact and artifact.get(k) is not None:
                row[k] = artifact.get(k)
            else:
                # some canonical columns come from rec metadata
                if k == 'extraction_confidence_score':
                    row[k] = rec.get('extraction_confidence_score') or artifact.get(k)
                elif k == 'mountain_name':
                    row[k] = rec.get('mountain_name') or artifact.get(k)
                else:
                    row[k] = artifact.get(k)

        # add some metadata columns not present in the canonical artifact list
        row['domain'] = rec.get('domain')
        row['source_url'] = rec.get('source_url')
        row['ts'] = rec.get('ts')

        # keep a raw artifact backup
        try:
            row['artifact_json'] = json.dumps(artifact, ensure_ascii=False)
        except Exception:
            row['artifact_json'] = ''

        # update/insert our incoming record
        existing[row.get('source_url')] = row
        rows = list(existing.values())
        # At this point `existing` contains rows keyed by source_url.
        # Build a stable set of fieldnames: canonical fields first, then any extras
        all_keys = set()
        for r in existing.values():
            all_keys.update(r.keys())
        # Exclude metadata keys from extras to avoid duplication later
        metadata_keys = {'domain', 'source_url', 'ts', 'artifact_json'}
        extras = [k for k in sorted(all_keys) if k not in CANONICAL_ARTIFACT_FIELDS and k not in metadata_keys]
        fieldnames = list(CANONICAL_ARTIFACT_FIELDS) + extras

        # Instead of expanding into many numbered columns, serialize nested lists/dicts
        # as JSON strings (the CSV writer will do this) and also provide simple count
        # columns (people_count, rescue_teams_count, and counts for URL lists).
        # Build CSV fieldnames here so the local CSV is written with metadata and
        # count columns even when Drive upload is not configured.
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
        _write_local_csv(_LOCAL_CSV_PATH, normalized_rows, fieldnames=csv_fieldnames)
    except Exception:
        # swallow errors writing local CSV to avoid breaking main flow
        pass

    # Now attempt to upload to Drive if available.
    try:
        ds = _get_drive_storage()
        if not ds:
            return

        # csv_fieldnames already constructed above (csv_fieldnames). If for some reason
        # it's missing, fall back to the previously computed 'fieldnames'.
        if 'csv_fieldnames' not in locals():
            csv_fieldnames = list(CANONICAL_ARTIFACT_FIELDS) + extras + ['domain', 'source_url', 'ts', 'artifact_json']
            csv_fieldnames += ['people_count', 'rescue_teams_count']
            for key in ('photo_urls', 'video_urls', 'related_articles_urls', 'fundraising_links', 'official_reports_links'):
                csv_fieldnames.append(f'{key}_count')

        try:
            # Build explicit rows that match csv_fieldnames and stringify nested values.
            # This guarantees Drive receives a CSV with the expected columns (not only artifact_json).
            drive_rows = []
            for r in normalized_rows:
                dr = {}
                for k in csv_fieldnames:
                    v = r.get(k)
                    # Normalize long text fields to single-line
                    if isinstance(v, str) and k in ("article_text", "scraped_full_text"):
                        dr[k] = " ".join(v.split())
                    elif isinstance(v, (list, dict)):
                        try:
                            dr[k] = json.dumps(v, ensure_ascii=False)
                        except Exception:
                            dr[k] = str(v)
                    elif v is None:
                        dr[k] = ""
                    else:
                        dr[k] = v
                drive_rows.append(dr)

            # upload the explicit drive_rows so flattened columns appear in Drive
            try:
                try:
                    res = ds.save_artifacts_csv(drive_rows, drive_filename=_DRIVE_FILENAME, fieldnames=csv_fieldnames)
                except TypeError:
                    # fallback for older versions of DriveStorage that don't accept fieldnames
                    res = ds.save_artifacts_csv(drive_rows, drive_filename=_DRIVE_FILENAME)
            except Exception:
                # ensure res is always present for downstream logging
                res = {}
        except Exception:
            # building or uploading drive_rows failed; ensure downstream code has res
            res = {}

        # Also ensure the local CSV file uses the same canonical columns
        try:
            _write_local_csv(_LOCAL_CSV_PATH, normalized_rows, fieldnames=csv_fieldnames)
        except Exception:
            pass

        # Try to surface useful feedback to the developer: file id and webViewLink when present
        try:
            fid = res.get('id') if isinstance(res, dict) else None
            link = res.get('webViewLink') if isinstance(res, dict) else None
            if fid or link:
                print(f"[drive] uploaded artifacts CSV -> id={fid} link={link}")
        except Exception:
            pass

        # Also upload full artifacts JSON (list of artifact objects) so consumers can get full payloads
        try:
            # prepare docs (we want the 'artifact' field from each row map where present)
            # Upload JSON that mirrors the CSV rows so each JSON field corresponds to a CSV column.
            docs = [r for r in rows]
            json_res = ds.save_artifacts_json(docs, drive_filename=os.environ.get('DRIVE_ARTIFACTS_JSON_FILENAME', 'artifacts.json'))
            try:
                jf = json_res.get('id') if isinstance(json_res, dict) else None
                jlink = json_res.get('webViewLink') if isinstance(json_res, dict) else None
                if jf or jlink:
                    print(f"[drive] uploaded artifacts JSON -> id={jf} link={jlink}")
            except Exception:
                pass
        except Exception:
            # non-fatal
            pass
    except Exception:
        # swallow Drive upload errors as well
        return


def sync_artifact_to_drive(doc: Dict[str, Any]) -> None:
    """Public helper: sync a single artifact document to the local CSV mirror and Drive.

    This is a thin wrapper around the internal _maybe_sync_to_drive and intended for
    use by other modules that want Drive-only behavior without initializing the DB.
    """
    try:
        rec = {
            'source_url': doc.get('source_url'),
            'domain': doc.get('source_url', '').split('/')[2] if '/' in doc.get('source_url', '') else doc.get('source_url', ''),
            'ts': doc.get('extracted_at'),
            'mountain_name': doc.get('mountain_name'),
            'num_fatalities': doc.get('num_fatalities'),
            'extraction_confidence_score': doc.get('extraction_confidence_score'),
            'artifact': doc,
        }
        rec = {k: v for k, v in rec.items() if v is not None}
        _maybe_sync_to_drive(rec)
    except Exception:
        # best-effort only
        return


def init_db(path: str | Path = "artifacts.db", backend: str | None = None) -> None:
    """Initialize the DB backend.

    Backend selection: prefer sqlite; fall back to in-memory if sqlite can't be created.
    """
    global _DB, _DB_TYPE
    # Always prefer sqlite backend for persistence. Fall back to in-memory DB only if sqlite fails.
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(str(p))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL;")
        except Exception:
            pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS artifacts (
                source_url TEXT PRIMARY KEY,
                domain TEXT,
                ts TEXT,
                mountain_name TEXT,
                num_fatalities INTEGER,
                extraction_confidence_score REAL,
                artifact_json TEXT
            )
            """
        )
        conn.commit()
        _DB = conn
        _DB_TYPE = 'sqlite'
        return
    except Exception:
        # fallback to in-memory DB
        _DB = _InMemoryDB(path)
        _DB_TYPE = 'memory'


def close_db():
    global _DB
    global _DB_TYPE
    if _DB is not None:
        try:
            if _DB_TYPE == 'sqlite':
                _DB.close()
            else:
                _DB.close()
        except Exception:
            pass
        _DB = None
        _DB_TYPE = None


def upsert_artifact(doc: Dict[str, Any]) -> None:
    """Upsert an artifact document using source_url as the key.

    doc: the artifact payload (should contain 'source_url' and 'extracted_at')
    """
    global _DB
    if _DB is None:
        # lazy init default location
        init_db()
    src = doc.get('source_url')
    if not src:
        raise ValueError('artifact must contain source_url')
    # write full artifact under 'artifact' field for future-proofing
    rec = {
        'source_url': src,
        'domain': doc.get('source_url', '').split('/')[2] if '/' in doc.get('source_url', '') else doc.get('source_url', ''),
        'ts': doc.get('extracted_at'),
        'mountain_name': doc.get('mountain_name'),
        'num_fatalities': doc.get('num_fatalities'),
        'extraction_confidence_score': doc.get('extraction_confidence_score'),
        'artifact': doc,
    }
    # remove None values for cleanliness
    rec = {k: v for k, v in rec.items() if v is not None}
    # upsert by source_url
    try:
        if _DB_TYPE == 'sqlite':
            # insert or replace
            cur = _DB.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO artifacts
                (source_url, domain, ts, mountain_name, num_fatalities, extraction_confidence_score, artifact_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get('source_url'),
                    rec.get('domain'),
                    rec.get('ts'),
                    rec.get('mountain_name'),
                    rec.get('num_fatalities'),
                    rec.get('extraction_confidence_score'),
                    json.dumps(rec.get('artifact')),
                ),
            )
            _DB.commit()
            # try to sync to Drive asynchronously (best-effort)
            try:
                _maybe_sync_to_drive(rec)
            except Exception:
                pass
        else:
            # in-memory backend
            existing = _DB.search(lambda d: d.get('source_url') == src)
            if existing:
                _DB.update(rec, lambda d: d.get('source_url') == src)
            else:
                _DB.insert(rec)
            try:
                _maybe_sync_to_drive(rec)
            except Exception:
                pass
    except Exception:
        # best-effort insert
        try:
            _DB.insert(rec)
        except Exception:
            pass


def query_artifacts(filters: Dict[str, Any] | None = None):
    global _DB
    if _DB is None:
        init_db()
    if not filters:
        # No filters: return all rows for sqlite (or limited to protect memory)
        if _DB_TYPE == 'sqlite':
            cur = _DB.cursor()
            cur.execute("SELECT * FROM artifacts")
            rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if d.get('artifact_json'):
                    try:
                        d['artifact'] = json.loads(d['artifact_json'])
                    except Exception:
                        d['artifact'] = d.get('artifact_json')
                out.append(d)
            return out
        else:
            return _DB.all()
    # sqlite backend: build simple WHERE clause using equality checks
    if _DB_TYPE == 'sqlite':
        cols = []
        vals = []
        for k, v in filters.items():
            cols.append(f"{k} = ?")
            vals.append(v)
        where = ' AND '.join(cols)
        cur = _DB.cursor()
        q = f"SELECT * FROM artifacts WHERE {where}"
        cur.execute(q, tuple(vals))
        rows = cur.fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # parse artifact_json back to object if present
            if d.get('artifact_json'):
                try:
                    d['artifact'] = json.loads(d['artifact_json'])
                except Exception:
                    d['artifact'] = d.get('artifact_json')
            out.append(d)
        return out

    # in-memory filter: simple dict match
    def match(d):
        for k, v in filters.items():
            if d.get(k) != v:
                return False
        return True

    return _DB.search(match)


def force_rebuild_and_upload_artifacts_csv():
    """Force a deterministic rebuild of the artifacts CSV and upload to Drive (if configured)."""
    try:
        # This is equivalent to calling _maybe_sync_to_drive with a dummy rec, which triggers a full scan and upload
        _maybe_sync_to_drive({})
    except Exception:
        pass
