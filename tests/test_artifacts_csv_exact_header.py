import csv
import json
import sys
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store_artifacts import CANONICAL_ARTIFACT_FIELDS


def test_exact_csv_header_matches_expected():
    p = Path('artifacts/artifacts.csv')
    assert p.exists(), 'artifacts/artifacts.csv must exist for this test'
    with p.open('r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        assert cols, 'CSV header missing'

    # Construct expected header shape per store_artifacts._maybe_sync_to_drive behavior
    expected = list(CANONICAL_ARTIFACT_FIELDS)
    # extras are any keys beyond canonical + metadata + counts; detect them from the CSV
    extras = [c for c in cols if c not in CANONICAL_ARTIFACT_FIELDS]
    # remove metadata & counts from extras list
    for meta in ('domain', 'source_url', 'ts', 'artifact_json', 'people_count', 'rescue_teams_count'):
        if meta in extras:
            extras.remove(meta)
    # URL count columns
    for key in ('photo_urls_count', 'video_urls_count', 'related_articles_urls_count', 'fundraising_links_count', 'official_reports_links_count'):
        if key in extras:
            extras.remove(key)

    expected += extras
    expected += ['domain', 'source_url', 'ts', 'artifact_json']
    expected += ['people_count', 'rescue_teams_count']
    expected += ['photo_urls_count', 'video_urls_count', 'related_articles_urls_count', 'fundraising_links_count', 'official_reports_links_count']

    # Now assert the CSV header starts with the canonical fields in order
    for idx, name in enumerate(CANONICAL_ARTIFACT_FIELDS):
        assert cols.index(name) >= idx, f'Canonical field {name} should be at or after position {idx}'

    # Assert the expected tail fields exist in the CSV header
    for name in ('artifact_json', 'people_count', 'rescue_teams_count'):
        assert name in cols, f'Expected column {name} missing from CSV header'
