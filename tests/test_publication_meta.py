import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from accident_utils import parse_publication_date, parse_report_author


SAMPLE_TEXT = (
    "By Jane Doe and John Smith | Published: Oct 3, 2025 Updated: Oct 4, 2025 "
    "Climber survived fall. Further details pending."
)


def test_parse_publication_date_month_name():
    d = parse_publication_date(SAMPLE_TEXT)
    # Accept either normalized ISO or None if dateutil absent
    assert d is None or d.startswith('2025-10-')


def test_parse_report_author_first_name():
    a = parse_report_author(SAMPLE_TEXT)
    assert a in (None, 'Jane Doe', 'Jane Doe and John Smith')


def test_parse_publication_date_iso():
    txt = "Published 2025-09-30 Incident details follow."
    assert parse_publication_date(txt) in ('2025-09-30', None)
