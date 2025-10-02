from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List


def front_matter(meta: Dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if isinstance(v, (list, dict)):
            v = json.dumps(v, ensure_ascii=False)
        lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def json_ld(event: Dict[str, Any]) -> str:
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": f"{event.get('mountain_name','Unknown')} — {event.get('accident_type','Incident')} ({event.get('accident_date','')})",
        "datePublished": event.get('article_date_published') or event.get('accident_date'),
        "about": [event.get('activity_type'), event.get('region')],
        "identifier": event.get('event_id'),
    }
    return "<script type=\"application/ld+json\">" + json.dumps(data, ensure_ascii=False) + "</script>\n"


def as_markdown_timeline(events: List[Dict[str, Any]] | None) -> str:
    if not events:
        return ""
    lines = []
    for e in events:
        ts = e.get('ts_iso') or e.get('approx_time') or ''
        desc = e.get('description') or e.get('type') or ''
        lines.append(f"- {ts} — {desc}")
    return "\n".join(lines)


def as_table(rows: List[Dict[str, Any]] | None) -> str:
    if not rows:
        return ""
    # simple pipe table
    keys = sorted({k for r in rows for k in r.keys()})
    head = "| " + " | ".join(keys) + " |\n" + "|" + "---|" * len(keys) + "\n"
    body = "\n".join("| " + " | ".join(str(r.get(k, '')) for k in keys) + " |" for r in rows)
    return head + body


def as_bullets(items: List[str] | None) -> str:
    if not items:
        return ""
    return "\n".join(f"- {i}" for i in items)
