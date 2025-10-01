import builtins
import json
from pathlib import Path

import pytest

import store_artifacts as sa


def test_sync_artifact_to_drive_calls_maybe_sync(monkeypatch):
    called = {}

    def fake_maybe_sync(rec):
        called['rec'] = rec

    monkeypatch.setattr(sa, '_maybe_sync_to_drive', fake_maybe_sync)

    doc = {
        'source_url': 'https://example.com/foo',
        'extracted_at': '2025-10-01T00:00:00',
        'mountain_name': 'Mount Test',
        'num_fatalities': 1,
        'extraction_confidence_score': 0.5,
    }

    sa.sync_artifact_to_drive(doc)
    assert 'rec' in called
    rec = called['rec']
    assert rec['source_url'] == doc['source_url']
    assert rec['mountain_name'] == doc['mountain_name']
    assert rec['num_fatalities'] == doc['num_fatalities']
