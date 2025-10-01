import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import accident_llm as al


class _FakeChoice:
    def __init__(self, content):
        self.message = type('M', (), {'content': content})


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def test_llm_extract_parsing_and_repair(monkeypatch):
    # Enable client availability
    monkeypatch.setattr(al, '_OPENAI_AVAILABLE', True)

    # Track kwargs to assert no temperature for gpt-5
    calls = {'kwargs': []}

    def _fake_create(**kwargs):
        calls['kwargs'].append(kwargs)
        # First call returns malformed JSON, second returns valid JSON
        if len(calls['kwargs']) == 1:
            return _FakeResp('{"mountain_name": "A"')  # malformed
        else:
            return _FakeResp('{"mountain_name": "A", "num_fatalities": 0}')

    fake_client = type('C', (), {'chat': type('X', (), {'completions': type('Y', (), {'create': lambda *a, **k: _fake_create(**k)})})})()
    monkeypatch.setattr(al, '_client', fake_client)
    monkeypatch.setenv('MAX_OPENAI_CALLS', '0')  # unlimited for test

    # Force model to gpt-5 to test temperature omission
    monkeypatch.setattr(al, 'ACCIDENT_INFO_MODEL', 'gpt-5')

    out = al.llm_extract('some article text')
    assert out.get('mountain_name') == 'A'
    assert out.get('num_fatalities') == 0

    # Ensure temperature omitted for gpt-5
    assert any('temperature' not in kw for kw in calls['kwargs'])
