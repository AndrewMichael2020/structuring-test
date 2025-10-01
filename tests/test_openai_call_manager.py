import os
import tempfile
from pathlib import Path
import importlib


def test_call_cap_enforcement(tmp_path, monkeypatch):
    # Point state file into a temp location
    state = tmp_path / '.calls.json'
    monkeypatch.setenv('OPENAI_CALLS_PATH', str(state))
    monkeypatch.setenv('MAX_OPENAI_CALLS', '2')

    # Reload module to pick up env
    if 'openai_call_manager' in list(importlib.sys.modules.keys()):
        importlib.reload(importlib.import_module('openai_call_manager'))
    import openai_call_manager as cm

    assert cm.can_make_call() is True
    cm.record_call(1)
    assert cm.can_make_call() is True
    cm.record_call(1)
    # Now at cap
    assert cm.can_make_call() is False
    rem = cm.remaining()
    assert rem == 0

    # Lower cap to unlimited and confirm
    monkeypatch.setenv('MAX_OPENAI_CALLS', '0')
    importlib.reload(importlib.import_module('openai_call_manager'))
    import openai_call_manager as cm2
    assert cm2.can_make_call() is True
    assert cm2.remaining() is None
