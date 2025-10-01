import tempfile
import shutil
from pathlib import Path
import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))

import store_artifacts as sa


def test_upsert_and_query_no_op():
    """Test that upsert_artifact and query_artifacts are no-ops in CSV-only mode."""
    tmpdir = tempfile.mkdtemp(prefix='test_store_')
    try:
        # These functions should not raise errors but are no-ops
        sa.init_db(str(Path(tmpdir) / 'db.json'))
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
        # In CSV-only mode, query returns empty list
        assert len(res) == 0
        assert isinstance(res, list)
    finally:
        sa.close_db()
        shutil.rmtree(tmpdir)
