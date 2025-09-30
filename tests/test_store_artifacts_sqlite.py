import tempfile
import json
from pathlib import Path
import store_artifacts as sa


def test_sqlite_upsert_and_query(tmp_path):
    db_path = tmp_path / 'artifacts_db.sqlite'
    # initialize sqlite backend explicitly
    sa.init_db(str(db_path), backend='sqlite')
    try:
        artifact = {
            'source_url': 'https://example.com/test/1',
            'extracted_at': '2025-09-30T12:00:00Z',
            'mountain_name': 'Test Peak',
            'num_fatalities': 1,
            'extraction_confidence_score': 0.75,
        }
        sa.upsert_artifact(artifact)

        res = sa.query_artifacts({'source_url': artifact['source_url']})
        assert isinstance(res, list)
        assert len(res) == 1
        row = res[0]
        # artifact stored under 'artifact' key after query
        assert row.get('artifact') is not None
        a = row['artifact']
        assert a['source_url'] == artifact['source_url']
        assert a['mountain_name'] == artifact['mountain_name']
        assert a['num_fatalities'] == artifact['num_fatalities']
    finally:
        sa.close_db()
