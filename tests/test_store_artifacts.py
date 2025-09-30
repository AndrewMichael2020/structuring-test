import tempfile
import shutil
from pathlib import Path
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))

import store_artifacts as sa


def test_upsert_and_query():
    tmpdir = tempfile.mkdtemp(prefix='test_store_')
    try:
        db_path = Path(tmpdir) / 'db.json'
        sa.init_db(str(db_path))
        doc = {
            'source_url': 'https://example.com/a',
            'extracted_at': '2025-09-30T12:00:00',
            'mountain_name': 'Mt Test',
            'num_fatalities': 1,
            'extraction_confidence_score': 0.8,
            'article_text': 'blah'
        }
        sa.upsert_artifact(doc)
        res = sa.query_artifacts({'source_url': 'https://example.com/a'})
        assert len(res) == 1
        assert res[0]['source_url'] == 'https://example.com/a'
    finally:
        sa.close_db()
        shutil.rmtree(tmpdir)
