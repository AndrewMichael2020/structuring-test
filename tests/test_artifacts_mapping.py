import json
import sys
from pathlib import Path
import csv

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store_artifacts import sync_artifact_to_drive, CANONICAL_ARTIFACT_FIELDS


def _flatten_field_candidates(key: str):
    # For nested keys, return direct column name or flattened variants
    if key == 'people':
        return ['people', 'people_count']
    if key == 'rescue_teams_involved':
        return ['rescue_teams_involved', 'rescue_teams_count']
    if key in ('photo_urls', 'video_urls', 'related_articles_urls', 'fundraising_links', 'official_reports_links'):
        return [key, f'{key}_count']
    return [key]


def test_rebuild_and_map_fields():
    sample = Path('artifacts/tavily_test/accident_info.json')
    assert sample.exists(), 'sample artifact missing'
    doc = json.loads(sample.read_text(encoding='utf-8'))

    # Force a rebuild and Drive sync (will overwrite local CSV)
    sync_artifact_to_drive(doc)

    csvp = Path('artifacts/artifacts.csv')
    assert csvp.exists(), 'artifacts/artifacts.csv not written'

    with csvp.open('r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        assert cols, 'CSV header missing after rebuild'

        # canonical fields must exist in header
        for f in CANONICAL_ARTIFACT_FIELDS:
            assert f in cols, f'Canonical column {f} missing from CSV header'

        # For each key present in sample, ensure at least one mapping column exists
        for k, v in doc.items():
            if v is None:
                continue
            candidates = _flatten_field_candidates(k)
            matched = any(c in cols for c in candidates)
            assert matched, f'No CSV column found for artifact key {k} (candidates: {candidates})'
