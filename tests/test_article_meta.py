import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from article_meta import extract_meta_from_html

HTML_META = '''
<html><head>
<meta name="author" content="Jane Doe" />
<meta property="article:published_time" content="2025-10-02T14:30:00Z" />
</head><body><article><p>Body text here.</p></article></body></html>
'''

HTML_TIME = '''
<html><body>
<time datetime="2025-09-28">September 28, 2025</time>
<p>Story body</p>
</body></html>
'''

HTML_JSONLD = '''
<html><head><script type="application/ld+json">{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "author": {"@type": "Person", "name": "Staff Writer"},
  "datePublished": "2025-09-30T11:12:00-05:00"
}</script></head>
<body><p>Some content</p></body></html>
'''


def test_extract_meta_from_html_meta_tags():
    a, d = extract_meta_from_html(HTML_META)
    assert a == 'Jane Doe'
    assert d in ('2025-10-02', None)


def test_extract_meta_from_html_time_tag():
    a, d = extract_meta_from_html(HTML_TIME)
    assert a is None
    assert d in ('2025-09-28', None)


def test_extract_meta_from_html_jsonld():
    a, d = extract_meta_from_html(HTML_JSONLD)
    assert a in ('Staff Writer', None)
    assert d in ('2025-09-30', None)
