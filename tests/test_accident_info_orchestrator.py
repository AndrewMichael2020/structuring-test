import json
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import accident_info as ai


def test_extract_accident_info_writes_json(monkeypatch, tmp_path):
    url = 'https://example.com/story'

    # Provide deterministic text extraction
    monkeypatch.setattr(ai, '_extract_article_text', lambda u: ('Title\nParagraphs', 'Focused text', u))
    # Pretend OpenAI not available so llm_extract returns {}
    monkeypatch.setattr(ai, 'llm_extract', lambda text: {'mountain_name': 'Mt. Unit', 'num_fatalities': 0})
    monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', False)

    out_dir = tmp_path / 'artifacts' / 'example.com' / '20250101_000000'
    out_dir.mkdir(parents=True)
    p = ai.extract_accident_info(url, out_dir=str(out_dir))
    assert Path(p).exists()
    data = json.loads(Path(p).read_text(encoding='utf-8'))
    assert data.get('source_url') == url
    assert data.get('article_text') == 'Focused text'
    assert data.get('scraped_full_text').startswith('Title')
    assert 'extraction_confidence_score' in data
