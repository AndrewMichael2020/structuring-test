from pathlib import Path
from typing import Optional, Dict, Any
import json
import os
import sqlite3

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
        else:
            # in-memory backend
            existing = _DB.search(lambda d: d.get('source_url') == src)
            if existing:
                _DB.update(rec, lambda d: d.get('source_url') == src)
            else:
                _DB.insert(rec)
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
    # in-memory filter: simple dict match
    def match(d):
        for k, v in filters.items():
            if d.get(k) != v:
                return False
        return True

    return _DB.search(match)
