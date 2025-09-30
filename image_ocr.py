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
import re
import time
from PIL import Image
import openai as _openai
from openai import OpenAI
from openai_call_manager import can_make_call, record_call, remaining

# Initialize OpenAI client only if API key is present to avoid hard failure on import
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if _OPENAI_API_KEY:
    try:
        client = OpenAI()
        OPENAI_AVAILABLE = True
    except Exception:
        client = None
        OPENAI_AVAILABLE = False


        # Helper for OpenAI calls with retry/backoff
        def _chat_with_retries(payload_messages, model_name="gpt-4o-mini", max_retries=6):
            backoff = 0.5
            for attempt in range(max_retries):
                try:
                    return client.chat.completions.create(
                        model=model_name,
                        messages=payload_messages,
                        temperature=0
                    )
                except Exception as e:
                    # handle OpenAI rate limits gracefully
                    try:
                        if hasattr(_openai, 'RateLimitError') and isinstance(e, _openai.RateLimitError):
                            wait = backoff * (2 ** attempt)
                            time.sleep(wait)
                            continue
                    except Exception:
                        pass
                    # sometimes the library raises a generic Exception containing '429' or 'rate_limit'
                    msg = str(e).lower()
                    if 'rate limit' in msg or '429' in msg or 'tokens per min' in msg:
                        wait = backoff * (2 ** attempt)
                        time.sleep(wait)
                        continue
                    raise
else:
    client = None
    OPENAI_AVAILABLE = False


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
    # If OpenAI isn't available, return a minimal fallback structure using only OCR (no GPT analysis)
    data_url = _encode_image_as_data_url(image_path)
    if not OPENAI_AVAILABLE or client is None:
        # Basic fallback: return a minimal structure with low confidence using only image filename
        return {
            "summary": os.path.basename(image_path),
            "signals": {
                "avalanche_signs": {"crown_line": None, "debris": None, "slide_paths": None, "size_est": None, "slab_type": None},
                "snow_surface": {"full_coverage": None, "cornice": None, "wind_loading": None, "melt_freeze_crust": None},
                "terrain": {"slope_angle_class": None, "aspect": "unknown", "terrain_trap": [], "elevation_band": None},
                "glacier": {"crevasses": None, "seracs": None, "snow_bridge_likely": None},
                "weather": {"sky": None, "visibility": None, "precip": None, "wind": None},
                "human_activity": {"tracks": None, "people_present": None, "rope_or_harness": None, "helmet": None},
                "rescue": {"helicopter": None, "longline": None, "recco": None, "personnel_on_foot": None}
            },
            "confidence": 0.0
        }

    # Full OpenAI path. Respect per-run cap.
    if not can_make_call():
        print(f"[OCR] OpenAI call cap reached (remaining=0). Skipping GPT analysis for {image_path}")
        return {
            "summary": os.path.basename(image_path),
            "signals": {
                "avalanche_signs": {"crown_line": None, "debris": None, "slide_paths": None, "size_est": None, "slab_type": None},
                "snow_surface": {"full_coverage": None, "cornice": None, "wind_loading": None, "melt_freeze_crust": None},
                "terrain": {"slope_angle_class": None, "aspect": "unknown", "terrain_trap": [], "elevation_band": None},
                "glacier": {"crevasses": None, "seracs": None, "snow_bridge_likely": None},
                "weather": {"sky": None, "visibility": None, "precip": None, "wind": None},
                "human_activity": {"tracks": None, "people_present": None, "rope_or_harness": None, "helmet": None},
                "rescue": {"helicopter": None, "longline": None, "recco": None, "personnel_on_foot": None}
            },
            "confidence": 0.0
        }

    resp = _chat_with_retries([
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _SCHEMA_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}}
            ]
        }
    ])
    # Record that we made one OpenAI call
    try:
        record_call(1)
    except Exception:
        pass
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
        resp2 = _chat_with_retries([
            {"role": "user", "content": [
                {"type": "text", "text": fallback_prompt},
                {"type": "image_url", "image_url": {"url": data_url}}
            ]}
        ])
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
    # If OpenAI client isn't configured, use a simple heuristic fallback to avoid crashing.
    if not caption or not ocr_obj:
        return False

    signals_text = f"{ocr_obj.get('summary','')}. {_signals_to_text(ocr_obj.get('signals', {}))}"

    try:
        if OPENAI_AVAILABLE and client is not None:
            judge_prompt = (
                f"Caption: \"{caption}\"\n"
                f"Signals: \"{signals_text}\"\n\n"
                "Answer YES if the signals plausibly match or are consistent with the caption. "
                "Answer NO if they conflict or describe unrelated content. Respond with only YES or NO."
            )

            resp = _chat_with_retries([
                {"role": "user", "content": [{"type": "text", "text": judge_prompt}]}
            ])
            decision = resp.choices[0].message.content.strip().upper()
            return decision.startswith("Y")
    except Exception:
        # fall through to heuristic
        pass

    # Heuristic fallback: check for token overlap between caption and OCR signals text
    try:
        cap_words = set(re.findall(r"\w+", caption.lower()))
        sig_words = set(re.findall(r"\w+", signals_text.lower()))
        common = cap_words & sig_words
        # consider correlated if at least one non-trivial word overlaps (ignore short common words)
        common = {w for w in common if len(w) > 3}
        return len(common) >= 1
    except Exception:
        return False


# -------------------- JSON Enrichment --------------------
def enrich_json_with_conditions(json_path: str):
    """Attach OCR structured info and check caption–OCR correlation; log alerts."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # --- Handle edge case: no images extracted ---
    if not data or all(not e.get("local_image_path") for e in data):
        print(f"[INFO] 💤 No images found for OCR in {json_path}. Skipping OCR step.")
        return

    # helper: skip obvious irrelevant images before costly OpenAI calls
    # configurable list of tokens that indicate irrelevant images (filename or caption)
    IRRELEVANT_TOKENS_ENV = os.getenv('IRRELEVANT_TOKENS')
    if IRRELEVANT_TOKENS_ENV:
        IRRELEVANT_TOKENS = [t.strip().lower() for t in IRRELEVANT_TOKENS_ENV.split(',') if t.strip()]
    else:
        IRRELEVANT_TOKENS = [
            'logo', 'affiliate', 'promo', 'pixel', 'favicon', 'avatar', 'banner', 'icon',
            'sprite', 'ads', 'advert', 'tracking', 'thumb', 'thumbnail'
        ]

    MIN_OCR_BYTES = int(os.getenv('MIN_OCR_BYTES', '8192'))  # 8 KB
    MIN_OCR_WIDTH = int(os.getenv('MIN_OCR_WIDTH', '300'))
    MIN_OCR_HEIGHT = int(os.getenv('MIN_OCR_HEIGHT', '200'))
    # minimum pixel area (width * height). Defaults to 300*200
    MIN_OCR_AREA = int(os.getenv('MIN_OCR_AREA', str(MIN_OCR_WIDTH * MIN_OCR_HEIGHT)))

    def is_irrelevant_image(path: str, caption: str | None = None) -> bool:
        try:
            if not path or not os.path.exists(path):
                return True
            # filename tokens
            name = os.path.basename(path).lower()
            for t in IRRELEVANT_TOKENS:
                if t in name:
                    # small cosmetic token match in filename
                    print(f"[OCR] Skipping by filename token '{t}': {path}")
                    return True

            # caption tokens (if provided) - skip if caption clearly points to logo/thumbnail/affiliate
            if caption:
                cl = caption.lower()
                for t in IRRELEVANT_TOKENS:
                    if t in cl:
                        print(f"[OCR] Skipping by caption token '{t}': {path} (caption: {caption})")
                        return True
            # filesize
            try:
                if os.path.getsize(path) < MIN_OCR_BYTES:
                    print(f"[OCR] Skipping by filesize < {MIN_OCR_BYTES} bytes: {path}")
                    return True
            except Exception:
                pass
            # dimensions
            try:
                with Image.open(path) as im:
                    w, h = im.size
                    if w < MIN_OCR_WIDTH or h < MIN_OCR_HEIGHT:
                        print(f"[OCR] Skipping by dimension < {MIN_OCR_WIDTH}x{MIN_OCR_HEIGHT}: {w}x{h} {path}")
                        return True
                    if (w * h) < MIN_OCR_AREA:
                        print(f"[OCR] Skipping by area < {MIN_OCR_AREA}: {w}x{h} {path}")
                        return True
            except Exception:
                # if we can't open image, mark irrelevant to avoid crashes
                return True
            return False
        except Exception:
            return True

    for entry in data:
        lp = entry.get("local_image_path")
        caption = entry.get("caption_clean")
        if not lp or not os.path.exists(lp):
            continue
        print(f"[OCR] Considering: {lp}")

        if is_irrelevant_image(lp, caption=caption):
            print(f"[OCR] ⏩ Skipping irrelevant/small image: {lp}")
            entry["ocr"] = {
                "model": None,
                "summary": None,
                "signals": {},
                "confidence": 0.0,
                "skipped": True
            }
            continue

        print(f"[OCR] Analyzing: {lp}")
        ocr_obj = analyze_conditions(lp)
        entry["ocr"] = {
            "model": "gpt-4o-mini" if OPENAI_AVAILABLE else None,
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

