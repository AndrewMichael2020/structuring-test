import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accident_utils import _iso_or_none, _ensure_outdir
from accident_preextract import pre_extract_fields


def test_iso_or_none_parses_various_formats():
    assert _iso_or_none('2025-10-01') == '2025-10-01'
    assert _iso_or_none('Oct 1, 2025') in ('2025-10-01', None)
    assert _iso_or_none('1 October 2025') in ('2025-10-01', None)
    assert _iso_or_none('n/a') is None


def test_ensure_outdir_and_preextract(tmp_path, monkeypatch):
    # ensure outdir creates expected tree
    url = 'https://news.example.com/path'
    base = tmp_path / 'artifacts'
    p = _ensure_outdir(url, str(base))
    assert p.exists()
    # Domain is slugified with underscores in outdir
    assert 'news_example_com' in str(p)

    text = 'Climber, 28, fell 100 feet. SAR responded.'
    pe = pre_extract_fields(text)
    # Expect some pre fields
    assert 'fall_height_feet_pre' in pe or 'people_pre' in pe
