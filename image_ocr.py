#!/usr/bin/env python3
"""
image_ocr.py
1) Uses OpenAI GPT-4o-mini vision on local images to extract structured, fine-grained
   climbing/rescue conditions in a STRICT JSON schema.
2) Compares extracted caption vs OCR signals and logs alerts if they don't correlate.

Output stored into entry["ocr"] as:
{
  "model": "gpt-4o-mini",
  "summary": "<short phrase>",
  "signals": { ...structured fields below... },
  "confidence": <0..1>
}
"""

import os
import json
import base64
from openai import OpenAI

client = OpenAI()


# -------------------- Image Encoding --------------------
def _encode_image_as_data_url(image_path: str) -> str:
    """Convert local image file to base64 data URL string."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    ext = os.path.splitext(image_path)[-1].lower().strip(".")
    if ext not in ["jpg", "jpeg", "png"]:
        ext = "jpeg"
    return f"data:image/{ext};base64,{b64}"


# -------------------- GPT Condition Extraction --------------------
_SCHEMA_PROMPT = (
    "You are analyzing a single mountain/rescue photo for climbing accident analysis. "
    "Extract ONLY what is VISIBLE. If uncertain or not visible, use null. Do not guess.\n\n"
    "Return STRICT JSON (no prose) with this exact schema and keys:\n"
    "{\n"
    '  "summary": "short factual phrase",\n'
    '  "signals": {\n'
    '    "avalanche_signs": {\n'
    '      "crown_line": true|false|null,\n'
    '      "debris": true|false|null,\n'
    '      "slide_paths": true|false|null,\n'
    '      "size_est": "D1"|"D2"|"D3"|null,\n'
    '      "slab_type": "wind"|"persistent"|"storm"|"wet_slab"|"dry_slab"|"loose_wet"|"loose_dry"|null\n'
    "    },\n"
    '    "snow_surface": {\n'
    '      "full_coverage": "none"|"patchy"|"continuous"|null,\n'
    '      "cornice": "none"|"small"|"large"|"overhanging"|null,\n'
    '      "wind_loading": "none"|"light"|"moderate"|"heavy"|null,\n'
    '      "melt_freeze_crust": true|false|null\n'
    "    },\n"
    '    "terrain": {\n'
    '      "slope_angle_class": "<30"|"30-35"|"35-40"|">40"|null,\n'
    '      "aspect": "N"|"NE"|"E"|"SE"|"S"|"SW"|"W"|"NW"|"unknown",\n'
    '      "terrain_trap": ["gully","cliff","creek","glacier","depression"]|[],\n'
    '      "elevation_band": "below_treeline"|"treeline"|"alpine"|null\n'
    "    },\n"
    '    "glacier": {\n'
    '      "crevasses": true|false|null,\n'
    '      "seracs": true|false|null,\n'
    '      "snow_bridge_likely": true|false|null\n'
    "    },\n"
    '    "weather": {\n'
    '      "sky": "clear"|"scattered"|"overcast"|null,\n'
    '      "visibility": "good"|"moderate"|"poor"|null,\n'
    '      "precip": "none"|"snow"|"rain"|null,\n'
    '      "wind": "calm"|"light"|"moderate"|"strong"|null\n'
    "    },\n"
    '    "human_activity": {\n'
    '      "tracks": "none"|"boot"|"skin"|"ski"|"sled"|"unknown"|null,\n'
    '      "people_present": true|false|null,\n'
    '      "rope_or_harness": true|false|null,\n'
    '      "helmet": true|false|null\n'
    "    },\n"
    '    "rescue": {\n'
    '      "helicopter": true|false|null,\n'
    '      "longline": true|false|null,\n'
    '      "recco": true|false|null,\n'
    '      "personnel_on_foot": true|false|null\n'
    "    }\n"
    "  },\n"
    '  "confidence": 0.0..1.0\n'
    "}\n\n"
    "Rules:\n"
    "- Never output keys not in the schema.\n"
    "- If a signal is not visible, set it to null (or [] for terrain_trap).\n"
    "- Keep summary very short (<= 12 words)."
)

def analyze_conditions(image_path: str) -> dict:
    """Run GPT-4o-mini vision, return parsed dict with strict schema. If parsing fails, fallback to minimal dict."""
    data_url = _encode_image_as_data_url(image_path)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _SCHEMA_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }
        ],
        temperature=0
    )
    txt = resp.choices[0].message.content.strip()

    # Parse strict JSON; fallback to baseline if needed
    try:
        obj = json.loads(txt)
        # Minimal sanity checks
        if not isinstance(obj, dict):
            raise ValueError("Non-dict JSON")
        if "summary" not in obj or "signals" not in obj or "confidence" not in obj:
            raise ValueError("Missing required keys")
        return obj
    except Exception:
        # Fallback: ask for plain short phrase only (rare)
        fallback_prompt = (
            "Return ONLY a very short phrase of visible conditions (<= 12 words)."
        )
        resp2 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": fallback_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]}
            ],
            temperature=0
        )
        return {
            "summary": resp2.choices[0].message.content.strip(),
            "signals": {
                "avalanche_signs": {"crown_line": None, "debris": None, "slide_paths": None, "size_est": None, "slab_type": None},
                "snow_surface": {"full_coverage": None, "cornice": None, "wind_loading": None, "melt_freeze_crust": None},
                "terrain": {"slope_angle_class": None, "aspect": "unknown", "terrain_trap": [], "elevation_band": None},
                "glacier": {"crevasses": None, "seracs": None, "snow_bridge_likely": None},
                "weather": {"sky": None, "visibility": None, "precip": None, "wind": None},
                "human_activity": {"tracks": None, "people_present": None, "rope_or_harness": None, "helmet": None},
                "rescue": {"helicopter": None, "longline": None, "recco": None, "personnel_on_foot": None}
            },
            "confidence": 0.3
        }


# -------------------- Caption vs OCR Judge --------------------
def _signals_to_text(signals: dict) -> str:
    """Compress key signals into a short text for correlation judgment."""
    try:
        a = signals.get("avalanche_signs", {})
        s = signals.get("snow_surface", {})
        t = signals.get("terrain", {})
        r = signals.get("rescue", {})
        parts = []
        if a.get("debris"): parts.append("avalanche debris")
        if a.get("crown_line"): parts.append("crown line")
        if s.get("cornice") in ("large", "overhanging"): parts.append(f"cornice:{s.get('cornice')}")
        if s.get("wind_loading") in ("moderate","heavy"): parts.append(f"wind:{s.get('wind_loading')}")
        if t.get("slope_angle_class"): parts.append(f"slope:{t.get('slope_angle_class')}")
        if t.get("aspect") and t.get("aspect") != "unknown": parts.append(f"aspect:{t.get('aspect')}")
        if r.get("helicopter"): parts.append("helicopter present")
        if r.get("longline"): parts.append("longline")
        if r.get("recco"): parts.append("RECCO")
        return ", ".join(parts) or "no salient signals"
    except Exception:
        return "no salient signals"

def judge_correlation(caption: str, ocr_obj: dict) -> bool:
    """
    Returns True if caption and OCR signals correlate semantically.
    Uses GPT-4o-mini for cheap semantic similarity judgment on caption vs signals text.
    """
    if not caption or not ocr_obj:
        return False
    signals_text = f"{ocr_obj.get('summary','')}. {_signals_to_text(ocr_obj.get('signals', {}))}"

    judge_prompt = (
        f"Caption: \"{caption}\"\n"
        f"Signals: \"{signals_text}\"\n\n"
        "Answer YES if the signals plausibly match or are consistent with the caption. "
        "Answer NO if they conflict or describe unrelated content. Respond with only YES or NO."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": [{"type": "text", "text": judge_prompt}]}],
        temperature=0
    )
    decision = resp.choices[0].message.content.strip().upper()
    return decision.startswith("Y")


# -------------------- JSON Enrichment --------------------
def enrich_json_with_conditions(json_path: str):
    """Attach OCR structured info and check caption–OCR correlation; log alerts."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for entry in data:
        lp = entry.get("local_image_path")
        caption = entry.get("caption_clean")
        if lp and os.path.exists(lp):
            print(f"[OCR] Analyzing: {lp}")
            ocr_obj = analyze_conditions(lp)
            entry["ocr"] = {
                "model": "gpt-4o-mini",
                "summary": ocr_obj.get("summary"),
                "signals": ocr_obj.get("signals"),
                "confidence": ocr_obj.get("confidence")
            }

            correlated = judge_correlation(caption, ocr_obj)
            if not correlated:
                print(
                    "⚠️ [ALERT] Caption/OCR mismatch:\n"
                    f"  Caption: {caption}\n"
                    f"  OCR.summary: {entry['ocr']['summary']}\n"
                    f"  OCR.signals: {json.dumps(entry['ocr']['signals'], ensure_ascii=False)}\n"
                    f"  Image: {lp}"
                )

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[INFO] ✅ Updated JSON with structured OCR signals & correlation checks: {json_path}")
