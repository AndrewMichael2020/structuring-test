import json
import sys
from pathlib import Path
# Ensure workspace root is on sys.path so tests can import store modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store_artifacts import CANONICAL_ARTIFACT_FIELDS


def test_csv_header_contains_canonical_fields():
    p = Path('artifacts/artifacts.csv')
    assert p.exists(), 'artifacts/artifacts.csv must exist for this test'
    import csv

    with p.open('r', encoding='utf-8') as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        assert cols, 'CSV header missing'

        # verify canonical fields appear in the header in the same relative order
        idx = 0
        for f in CANONICAL_ARTIFACT_FIELDS:
            assert f in cols, f'Canonical field {f} missing from CSV header'
            pos = cols.index(f)
            assert pos >= idx, f'Field {f} appears out of order in CSV header'
            idx = pos

        # artifact_json must exist and parse for last row
        assert 'artifact_json' in cols, 'artifact_json column missing from CSV header'
        rows = list(reader)
        assert rows, 'no rows in CSV after parsing'
        aj = rows[-1].get('artifact_json')
        assert aj is not None
        json.loads(aj)
