import json
import tempfile
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))

import accident_info as ai


class FakeResp:
    def __init__(self, content):
        self.choices = [type('C', (), {'message': type('M', (), {'content': content})})]


def _setup_tmp():
    return tempfile.mkdtemp(prefix='test_batch_comp_')


def test_batch_client_none_writes_minimal(monkeypatch):
    tmp = _setup_tmp()
    try:
        urls = ['https://a.com/a', 'https://b.com/b']
        # deterministic extraction
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: (f'Full {u}', f'Focused {u}'))
        # client None triggers chat failure path
        monkeypatch.setattr(ai, '_client', None)
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', True)
        # allow can_make_call
        monkeypatch.setattr(ai, 'can_make_call', lambda: True)

        written = ai.batch_extract_accident_info(urls, batch_size=2, base_output=tmp)
        assert len(written) == 2
        for p in written:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
            # minimal payload fields exist
            assert 'article_text' in data and 'scraped_full_text' in data
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_batch_can_make_call_false(monkeypatch):
    tmp = _setup_tmp()
    try:
        urls = ['https://a.com/a', 'https://b.com/b']
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: (f'Full {u}', f'Focused {u}'))
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', True)
        # Force cap reached
        monkeypatch.setattr(ai, 'can_make_call', lambda: False)

        written = ai.batch_extract_accident_info(urls, batch_size=2, base_output=tmp)
        assert len(written) == 2
        for p in written:
            assert Path(p).exists()
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_batch_bracket_substring_parsing(monkeypatch):
    tmp = _setup_tmp()
    try:
        urls = ['https://a.com/a', 'https://b.com/b']
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: (f'Full {u}', f'Focused {u}'))
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', True)
        monkeypatch.setattr(ai, 'can_make_call', lambda: True)

        arr = [
            {'mountain_name': 'A'},
            {'num_fatalities': 1}
        ]
        resp_content = 'some preface text ' + json.dumps(arr) + ' trailing'

        fake_client = type('C', (), {'chat': type('X', (), {'completions': type('Y', (), {'create': lambda *a, **k: FakeResp(resp_content)})})})()
        monkeypatch.setattr(ai, '_client', fake_client)

        written = ai.batch_extract_accident_info(urls, batch_size=2, base_output=tmp)
        assert len(written) == 2
        for p in written:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
            assert 'extraction_confidence_score' in data
    finally:
        import shutil
        shutil.rmtree(tmp)


def test_batch_mismatched_length_fills_rest(monkeypatch):
    tmp = _setup_tmp()
    try:
        urls = ['https://a.com/a', 'https://b.com/b', 'https://c.com/c']
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: (f'Full {u}', f'Focused {u}'))
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', True)
        monkeypatch.setattr(ai, 'can_make_call', lambda: True)

        # Return array shorter than batch
        arr = [{'mountain_name': 'A'}]  # only one result
        resp_content = json.dumps(arr)
        fake_client = type('C', (), {'chat': type('X', (), {'completions': type('Y', (), {'create': lambda *a, **k: FakeResp(resp_content)})})})()
        monkeypatch.setattr(ai, '_client', fake_client)

        written = ai.batch_extract_accident_info(urls, batch_size=3, base_output=tmp)
        assert len(written) == 3
        # The last two should be minimal artifacts
        for p in written[1:]:
            data = json.loads(Path(p).read_text(encoding='utf-8'))
            assert 'pre_extracted' in data
    finally:
        import shutil
        shutil.rmtree(tmp)
