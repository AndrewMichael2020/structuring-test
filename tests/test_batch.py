import shutil
import tempfile
from pathlib import Path

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
import accident_info as ai


def fake_extract(url):
    # return (full_text, focused_text)
    return ("Full text for " + url, "Focused text for " + url)


def test_batch_writes_minimal_artifacts(monkeypatch):
    tmp = tempfile.mkdtemp(prefix='test_batch_')
    try:
        urls = [
            'https://vancouversun.com/news/woman-dead-climbing-accident-squamish',
            'https://apnews.com/article/washington-rock-climber-fall-death-survivor-acad73387217d799119a34a3d9d42441',
        ]
        # monkeypatch to avoid real network
        monkeypatch.setattr(ai, '_extract_article_text', lambda u: fake_extract(u))
        # force OpenAI unavailable path
        monkeypatch.setattr(ai, '_OPENAI_AVAILABLE', False)
        monkeypatch.setattr(ai, '_client', None)
        written = ai.batch_extract_accident_info(urls, batch_size=2, base_output=tmp)
        # ensure two artifacts written
        assert len(written) == 2
        for p in written:
            assert Path(p).exists()
            data = Path(p).read_text(encoding='utf-8')
            assert 'pre_extracted' in data or 'Focused text' in data
    finally:
        shutil.rmtree(tmp)
