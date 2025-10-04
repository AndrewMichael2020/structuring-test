import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from event_merge_service import run_merge_and_fusion


def test_fused_includes_source_urls(tmp_path, monkeypatch):
    # Create fake artifacts dir structure with two accident_info.json entries sharing event_id
    base = tmp_path / 'artifacts' / 'example_com'
    base.mkdir(parents=True, exist_ok=True)
    e1 = base / '20250101_010101'
    e1.mkdir(parents=True, exist_ok=True)
    e2 = base / '20250101_020202'
    e2.mkdir(parents=True, exist_ok=True)
    evt_id = 'evt123abc'
    doc1 = {
        'event_id': evt_id,
        'source_url': 'https://example.com/a',
        'article_text': 'Some text',
        'extracted_at': '2025-01-01T01:01:01-07:00'
    }
    doc2 = {
        'event_id': evt_id,
        'source_url': 'https://example.com/b',
        'article_text': 'Some other text',
        'extracted_at': '2025-01-01T02:02:02-07:00'
    }
    with open(e1 / 'accident_info.json', 'w', encoding='utf-8') as f:
        json.dump(doc1, f)
    with open(e2 / 'accident_info.json', 'w', encoding='utf-8') as f:
        json.dump(doc2, f)

    # Point services to tmp paths
    monkeypatch.setattr('event_merge_service.ARTIFACTS_DIR', tmp_path / 'artifacts')
    monkeypatch.setattr('event_merge_service.ENRICHED_DIR', tmp_path / 'events' / 'enriched')
    monkeypatch.setattr('event_merge_service.FUSED_DIR', tmp_path / 'events' / 'fused')
    monkeypatch.setattr('event_merge_service.ENRICH_CACHE', tmp_path / 'event_merge_cache.json')
    monkeypatch.setattr('event_merge_service.FUSE_CACHE', tmp_path / 'event_fusion_cache.json')

    # Run merge/fusion
    res = run_merge_and_fusion(dry_run=False, cache_clear=True)
    fused_path = tmp_path / 'events' / 'fused' / f'{evt_id}.json'
    assert fused_path.exists(), 'Fused file not created'
    with open(fused_path,'r',encoding='utf-8') as f:
        fused = json.load(f)
    urls = fused.get('source_urls')
    assert set(urls) == {'https://example.com/a', 'https://example.com/b'}
    # Primary source_url should be one of them (first seen may vary depending on ordering in iteration)
    assert fused.get('source_url') in {'https://example.com/a', 'https://example.com/b'}

