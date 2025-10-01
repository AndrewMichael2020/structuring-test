Repository SQLite usage

This project uses a single SQLite file at the repository root named `artifacts.db` to persist extracted artifacts.

Schema

Table: artifacts
- source_url TEXT PRIMARY KEY
- domain TEXT
- ts TEXT (ISO 8601 extracted_at timestamp)
- mountain_name TEXT
- num_fatalities INTEGER
- extraction_confidence_score REAL
- artifact_json TEXT (full artifact JSON payload)

Quick queries

- List latest 50 artifacts (most recent by ts):
  SELECT * FROM artifacts ORDER BY ts DESC LIMIT 50;

- Find artifacts for domain example.com:
  SELECT * FROM artifacts WHERE domain = 'example.com';

- Find artifacts with confidence >= 0.8:
  SELECT * FROM artifacts WHERE extraction_confidence_score >= 0.8 ORDER BY ts DESC;

- Get full JSON payload for a specific URL:
  SELECT artifact_json FROM artifacts WHERE source_url = 'https://example.com/article/1';

Using provided scripts

- Initialize an empty DB (creates file and table):
  python scripts/init_db_sqlite.py artifacts.db

- Inspect DB contents (prints parsed artifact rows):
  python scripts/inspect_db.py --db-path artifacts.db --limit 50

- Import artifacts from artifacts/ tree into the DB:
  python scripts/import_artifacts_to_db.py --artifacts-dir ./artifacts --db-path artifacts.db

Notes

- The `artifact_json` column stores the full JSON object that the extractor produced. Use it when you need fields not present in the top-level columns.
- The code prefers SQLite; if it cannot create the file it will fall back to an in-memory store (not persisted). See `store_artifacts.init_db()`.
- `artifacts.db` is ignored by `.gitignore` to avoid committing local data.
