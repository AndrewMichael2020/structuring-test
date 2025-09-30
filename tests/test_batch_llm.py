import json
import shutil
import tempfile
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))

import accident_info as ai


class FakeResp:
    def __init__(self, content):
        self.choices = [type('C', (), {'message': type('M', (), {'content': content})})]


def test_batch_llm_parsing(monkeypatch):
    tmp = tempfile.mkdtemp(prefix='test_batch_llm_')
    try:
        urls = [
            'https://example.com/articleA',
            'https://example.com/articleB',
        ]

        # fake extract text
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: (f'Full {u}', f'Focused {u}'))

        # fake can_make_call to allow
        monkeypatch.setattr(ai, 'can_make_call', lambda: True)

        # fake record_call to track calls
        calls = {'n': 0}

        def fake_record(n):
            calls['n'] += n

        monkeypatch.setattr(ai, 'record_call', fake_record)

        # fake client returning a JSON array string (one object per URL)
        fake_array = [
            {'mountain_name': 'Mount A', 'num_fatalities': 1, 'people': [{'name': 'Jane Doe', 'age': 34}]},
            {'mountain_name': 'Mount B', 'num_fatalities': 0, 'people': [{'name': 'John Roe', 'age': 28}]}
        ]
        resp_content = json.dumps(fake_array)

        fake_client = type('C', (), {'chat': type('X', (), {'completions': type('Y', (), {'create': lambda *a, **k: FakeResp(resp_content)})})})()
        monkeypatch.setattr(ai, '_client', fake_client)
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', True)

        written = ai.batch_extract_accident_info(urls, batch_size=2, base_output=tmp)
        # should write two artifacts
        assert len(written) == 2
        # record_call should have been incremented by 1 for the batch
        assert calls['n'] == 1

        for p in written:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
            assert 'mountain_name' in data or 'people' in data
            assert 'extraction_confidence_score' in data
    finally:
        shutil.rmtree(tmp)
