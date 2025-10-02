"""Deterministic pre-extraction from article text.

This reduces the LLM surface area and provides corroborating evidence.
"""

from __future__ import annotations

import re
from pathlib import Path

from config import GAZETTEER_ENABLED


def pre_extract_fields(text: str) -> dict:
    out: dict = {}
    if not text or not isinstance(text, str):
        return out

    # dates
    date_patterns = [
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)[\s\d,0-9]{2,20}"
    ]
    dates = []
    for p in date_patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            txt = m.group(0).strip(' ,.')
            dates.append(txt)
    if dates:
        out['pre_dates'] = dates[:3]

    # people patterns
    people = []
    for m in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}),\s*(\d{1,3})\b", text):
        name = m.group(1).strip()
        age = int(m.group(2))
        people.append({'name': name, 'age': age})
    if people:
        out['people_pre'] = people[:10]

    # unnamed people with ages
    unnamed = []
    for m in re.finditer(r"\b(\d{1,3})[- ]?year[- ]?old\b(?:\s+([A-Za-z\-]+))?", text, flags=re.IGNORECASE):
        try:
            age = int(m.group(1))
        except Exception:
            continue
        sex = None
        if m.group(2):
            s = m.group(2).lower()
            if s in ('man', 'male', 'boy'):
                sex = 'male'
            elif s in ('woman', 'female', 'girl'):
                sex = 'female'
        person = {'name': 'Unknown', 'age': age}
        if sex:
            person['sex'] = sex
        unnamed.append(person)
    if unnamed:
        if 'people_pre' in out:
            out['people_pre'].extend(unnamed)
        else:
            out['people_pre'] = unnamed

    # counts
    def find_int(patterns):
        vals = []
        for pat in patterns:
            for m in re.finditer(pat, text, flags=re.IGNORECASE):
                try:
                    v = int(m.group(1))
                    vals.append(v)
                except Exception:
                    continue
        return vals

    killed = find_int([r"\b(killed)\s+(\d+)\b", r"\b(\d+)\s+killed\b", r"\b(\d+)\s+dead\b"])
    injured = find_int([r"\b(\d+)\s+injured\b", r"(\d+)\s+hurt\b"])
    word_map = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}
    for w, n in word_map.items():
        if re.search(rf"\b{w}\b\s+(?:people\s+)?(?:died|dead|killed)\b", text, flags=re.IGNORECASE):
            killed.append(n)
    if killed:
        out['num_fatalities_pre'] = max(killed)
    if injured:
        out['num_injured_pre'] = max(injured)

    # rescue teams
    rescue_tokens = [
        r"Search and Rescue", r"SAR\b", r"RCMP\b", r"police\b",
        r"Fire Department", r"EMS\b"
    ]
    rescues = set()
    for t in rescue_tokens:
        for m in re.finditer(t, text, flags=re.IGNORECASE):
            rescues.add(m.group(0).strip())
    if rescues:
        out['rescue_teams_pre'] = list(rescues)

    # area / park heuristics
    area_m = re.search(
        r"\b(?:in|at)\s+([A-Z][\w\s'\-]{3,80}?(?:Area|Park|Recreation|Range|Provincial))",
        text,
    )
    if area_m:
        out['area_pre'] = area_m.group(1).strip()

    # gazetteer
    if GAZETTEER_ENABLED:
        try:
            gaz_path = Path(__file__).parent / 'data' / 'gazetteer_mountains.json'
            if gaz_path.exists():
                import json as _json
                with open(gaz_path, 'r', encoding='utf-8') as _g:
                    gaz = _json.load(_g)
                for name in gaz:
                    import re as _re
                    if _re.search(rf"\b{_re.escape(name)}\b", text, flags=_re.IGNORECASE):
                        out.setdefault('gazetteer_matches', []).append(name)
        except Exception:
            pass

    # summary sentences
    sents = re.split(r"(?<=[\.!\?])\s+", text.strip())
    if sents:
        out['lead_sentences'] = sents[:2]

    # route difficulty tokens
    diff_patterns = [
        r"\b5\.[0-9]{1,2}[a-z]?\b",
        r"\bclass\s+[1-5]\b",
        r"\bV\d+\b",
        r"\bGrade\s+[I|II|III|IV|V|VI]\b",
    ]
    diffs = []
    for p in diff_patterns:
        for m in re.finditer(p, text, flags=re.IGNORECASE):
            diffs.append(m.group(0))
    if diffs:
        out['route_difficulty_pre'] = list(dict.fromkeys(diffs))

    # route type keywords
    route_types = []
    for kw in [
        'rappel', 'rappelling', 'couloir', 'gully', 'ridge', 'spire', 'face',
        'wall', 'crag', 'route', 'descent', 'ascent'
    ]:
        if re.search(rf"\b{kw}\b", text, flags=re.IGNORECASE):
            route_types.append(kw)
    if route_types:
        out['route_types_pre'] = list(dict.fromkeys(route_types))

    # equipment tokens
    equipment = []
    for kw in [
        'piton', 'anchor', 'pitons', 'harness', 'leash', 'carabiner', 'bolt',
        'gps', 'rope', 'piton'
    ]:
        if re.search(rf"\b{kw}\b", text, flags=re.IGNORECASE):
            equipment.append(kw)
    if equipment:
        out['equipment_pre'] = list(dict.fromkeys(equipment))

    # fall height
    m = re.search(r"(\d{2,5})\s*(?:feet|ft|foot)\b", text, flags=re.IGNORECASE)
    if m:
        try:
            feet = int(m.group(1))
            meters = round(feet * 0.3048, 1)
            out['fall_height_feet_pre'] = feet
            out['fall_height_meters_pre'] = meters
        except Exception:
            pass

    # slope angle (degrees) and aspect tokens for snow/ski contexts
    slope_m = re.search(r"(\d{1,2})\s*(?:degrees?|°)\b", text, flags=re.IGNORECASE)
    if slope_m:
        try:
            out['slope_angle_deg_pre'] = float(slope_m.group(1))
        except Exception:
            pass
    aspect_m = re.search(r"\b(N|NE|E|SE|S|SW|W|NW)\b(?:[- ]?facing| aspect)?", text, flags=re.IGNORECASE)
    if aspect_m:
        out['aspect_cardinal_pre'] = aspect_m.group(1).upper()

    return out


__all__ = ["pre_extract_fields"]
