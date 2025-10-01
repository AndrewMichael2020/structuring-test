import csv
import json
from pathlib import Path
import shutil
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store_artifacts import force_rebuild_and_upload_artifacts_csv, CANONICAL_ARTIFACT_FIELDS


def _write_artifact(base: Path, domain: str, ts: str, doc: dict):
    p = base / domain / ts
    p.mkdir(parents=True, exist_ok=True)
    (p / 'accident_info.json').write_text(json.dumps(doc), encoding='utf-8')


def test_rebuild_scans_recursively_and_writes_counts(tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()

    # Create two artifacts for same source to test dedupe by newest ts
    doc_old = {
        'source_url': 'https://example.com/a1',
        'extracted_at': '2025-01-01T00:00:00Z',
        'article_text': 'A',
        'people': [{'name': 'x'}],
        'rescue_teams_involved': ['SAR'],
        'photo_urls': ['u1', 'u2'],
    }
    doc_new = dict(doc_old)
    doc_new['extracted_at'] = '2025-02-01T00:00:00Z'

    _write_artifact(artifacts_dir, 'example.com', '20250101_000000', doc_old)
    _write_artifact(artifacts_dir, 'example.com', '20250201_000000', doc_new)

    # Also create another domain
    doc_b = {
        'source_url': 'https://foo.com/b1',
        'extracted_at': '2025-03-03T00:00:00Z',
        'article_text': 'B',
        'people': [],
        'rescue_teams_involved': [],
        'video_urls': ['v1'],
    }
    _write_artifact(artifacts_dir, 'foo.com', '20250303_000000', doc_b)

    # Run rebuild with cwd set to tmp
    cwd = Path.cwd()
    try:
        import os
        os.chdir(tmp_path)
        force_rebuild_and_upload_artifacts_csv()
    finally:
        os.chdir(cwd)

    csvp = tmp_path / 'artifacts' / 'artifacts.csv'
    assert csvp.exists(), 'CSV not written after rebuild'
    rows = list(csv.DictReader(csvp.open('r', encoding='utf-8')))
    # Should contain two rows (dedup by source_url -> newest only for example.com, and one for foo.com)
    assert len(rows) == 2

    cols = rows[0].keys()
    # Canonical fields present
    for f in CANONICAL_ARTIFACT_FIELDS:
        assert f in cols
    # Count columns
    for k in ['people_count', 'rescue_teams_count', 'photo_urls_count', 'video_urls_count', 'related_articles_urls_count', 'fundraising_links_count', 'official_reports_links_count']:
        assert k in cols
