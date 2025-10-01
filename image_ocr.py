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
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except Exception:
    pytesseract = None
    TESSERACT_AVAILABLE = False

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

# Ensure a module-level _chat_with_retries exists (the code above attempted to
# define one but indentation could prevent it from being at module scope).
def _chat_with_retries(payload_messages, model_name="gpt-4o-mini", max_retries=6):
    """Call the OpenAI client with retry/backoff. Raises RuntimeError when no client is available."""
    if not OPENAI_AVAILABLE or client is None:
        raise RuntimeError("OpenAI client not available")
    backoff = 0.5
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(
                model=model_name,
                messages=payload_messages,
                temperature=0
            )
        except Exception as e:
            try:
                import openai as _openai_local
                if hasattr(_openai_local, 'RateLimitError') and isinstance(e, _openai_local.RateLimitError):
                    wait = backoff * (2 ** attempt)
                    time.sleep(wait)
                    continue
            except Exception:
                pass
            msg = str(e).lower()
            if 'rate limit' in msg or '429' in msg or 'tokens per min' in msg:
                wait = backoff * (2 ** attempt)
                time.sleep(wait)
                continue
            raise


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

    # Local OCR helper: use pytesseract if available to extract text from the image.
    def _do_local_ocr(path: str) -> str:
        if not TESSERACT_AVAILABLE:
            return ""
        try:
            with Image.open(path) as im:
                # convert to grayscale and increase size for better OCR
                im = im.convert("L")
                w, h = im.size
                if max(w, h) < 1600:
                    scale = min(3, int(1600 / max(w, h)))
                    im = im.resize((w * scale, h * scale))

                # Try multiple preprocessing passes and tesseract configs to maximize extraction
                tries = []

                try:
                    from PIL import ImageFilter, ImageEnhance, ImageOps
                    # sharpen + contrast
                    im1 = im.filter(ImageFilter.SHARPEN)
                    im1 = ImageEnhance.Contrast(im1).enhance(1.5)
                    tries.append(im1)
                    # adaptive threshold
                    im2 = im1.point(lambda p: 255 if p > 150 else 0)
                    tries.append(im2)
                    # invert (for white text on dark backgrounds)
                    tries.append(ImageOps.invert(im2))
                except Exception:
                    tries.append(im)

                out_txt = []
                for idx, im_try in enumerate(tries):
                    try:
                        # prefer a psm that works for sparse text blocks
                        config = '--psm 6'
                        txt = pytesseract.image_to_string(im_try, config=config)
                        if txt and len(txt.strip()) > 5:
                            out_txt.append(txt)
                    except Exception:
                        continue

                # fallback: try a more aggressive psm
                if not out_txt:
                    try:
                        txt = pytesseract.image_to_string(im, config='--psm 11')
                        if txt and len(txt.strip()) > 5:
                            out_txt.append(txt)
                    except Exception:
                        pass

                return "\n---\n".join([t.strip() for t in out_txt]) or ""
        except Exception:
            return ""

    ocr_text = _do_local_ocr(image_path)

    # parsed_context will hold any richer structures returned by model-based analysis
    parsed_context = {
        'mountaineering_extras': None,
        'image_meta': None,
    }

    # Heuristic parser for common labels: elevation, named points, snow/terrain tokens
    def _parse_ocr_for_signals(text: str) -> dict:
        signals = {
            "avalanche_signs": {"crown_line": None, "debris": None, "slide_paths": None, "size_est": None, "slab_type": None},
            "snow_surface": {"full_coverage": None, "cornice": None, "wind_loading": None, "melt_freeze_crust": None},
            "terrain": {"slope_angle_class": None, "aspect": "unknown", "terrain_trap": [], "elevation_band": None},
            "glacier": {"crevasses": None, "seracs": None, "snow_bridge_likely": None},
            "weather": {"sky": None, "visibility": None, "precip": None, "wind": None},
            "human_activity": {"tracks": None, "people_present": None, "rope_or_harness": None, "helmet": None},
            "rescue": {"helicopter": None, "longline": None, "recco": None, "personnel_on_foot": None},
        }
        t = text or ""
        low = t.lower()
        # elevation in feet
        m = re.search(r"(\d{1,3}(?:,\d{3})?)\s*(?:ft|feet)\b", t)
        if m:
            try:
                feet = int(m.group(1).replace(',', ''))
                # set a simple elevation_band heuristic
                if feet > 8000:
                    signals['terrain']['elevation_band'] = 'alpine'
                elif feet > 3000:
                    signals['terrain']['elevation_band'] = 'treeline'
                else:
                    signals['terrain']['elevation_band'] = 'below_treeline'
                # include numeric elevation as a helper under terrain_trap for visibility
                signals.setdefault('elevation_feet', feet)
            except Exception:
                pass
        # named features (Glacier, Point, Camp)
        names = re.findall(r"([A-Z][A-Za-z'\- ]{2,40}(?:Glacier|Point|Camp|Ridge|Peak|Creek|Pass))", t)
        if names:
            # put likely tokens into terrain.terrain_trap for consumers
            signals['terrain']['terrain_trap'] = list(dict.fromkeys([n.strip() for n in names]))
        # detect cornice/serac/crevasse
        if re.search(r"cornice", low):
            signals['snow_surface']['cornice'] = 'large'
        if re.search(r"serac", low):
            signals['glacier']['seracs'] = True
        if re.search(r"crevasse", low):
            signals['glacier']['crevasses'] = True
        # detect slope degrees or words like steep
        m2 = re.search(r"(\d{1,2})\s*(?:°|degrees)\b", t)
        if m2:
            try:
                deg = int(m2.group(1))
                if deg < 30:
                    signals['terrain']['slope_angle_class'] = '<30'
                elif deg < 35:
                    signals['terrain']['slope_angle_class'] = '30-35'
                elif deg < 40:
                    signals['terrain']['slope_angle_class'] = '35-40'
                else:
                    signals['terrain']['slope_angle_class'] = '>40'
            except Exception:
                pass
        elif re.search(r"steep|cliff|sheer", low):
            signals['terrain']['slope_angle_class'] = '>40'

        # snow keywords
        if re.search(r"wind ?loading|windloaded", low):
            signals['snow_surface']['wind_loading'] = 'moderate'
        if re.search(r"patchy|continuous|full ?coverage", low):
            # crude mapping
            if 'patchy' in low:
                signals['snow_surface']['full_coverage'] = 'patchy'
            else:
                signals['snow_surface']['full_coverage'] = 'continuous'

        return signals

    local_signals = _parse_ocr_for_signals(ocr_text)

    # Decide whether local OCR is good enough. If not, and OpenAI is available,
    # request a small vision model to transcribe visible labels and return a
    # compact JSON with detected names/elevations which we merge into signals.
    def _should_use_model(ocr_text: str, parsed_signals: dict) -> bool:
        if not ocr_text or len(ocr_text.strip()) < 20:
            return True
        # If no named terrain features detected, try model
        terr = parsed_signals.get('terrain', {})
        traps = terr.get('terrain_trap') or []
        if not traps:
            return True
        # otherwise local OCR is likely adequate
        return False

    ocr_model_used = None
    if _should_use_model(ocr_text, local_signals) and OPENAI_AVAILABLE and client is not None:
        try:
            if can_make_call():
                # Use a stronger model for better visual transcription (configurable)
                model_name = os.getenv('OPENAI_OCR_MODEL', 'gpt-5')

                # Request a rich JSON matching the user's schema. Keep the prompt explicit
                ocr_request_prompt = (
                    "You are an expert mountain imagery analyst. Analyze the provided image and RETURN A SINGLE JSON OBJECT (no surrounding text) using the schema below."
                    "\nTop-level keys: 'ocr' (ocr_text, summary, model, confidence, signals), 'mountaineering_extras' (geo_points, route_character, objective_hazards, technical_rating_est, incline_degrees, glacier_condition_est, approach_mode, retreat_options), and 'image_meta' (exif/gps if visible)."
                    "\nFor any field not visible, use null or empty containers. Ensure numeric estimates are numbers where possible."
                    "\nSchema (abridged): {\n  \"ocr\": {\"ocr_text\": \"...\", \"summary\": \"...\", \"signals\": { ... }, \"confidence\": 0.0},\n  \"mountaineering_extras\": { ... },\n  \"image_meta\": { ... }\n}"
                )

                user_content = [
                    {"type": "text", "text": ocr_request_prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]

                resp = _chat_with_retries([
                    {"role": "user", "content": user_content}
                ], model_name=model_name)
                try:
                    record_call(1)
                except Exception:
                    pass

                model_txt = resp.choices[0].message.content.strip()
                # try parse JSON
                parsed = None
                try:
                    parsed = json.loads(model_txt)
                except Exception:
                    # try to extract first JSON block
                    m = re.search(r"\{.*\}", model_txt, flags=re.S)
                    if m:
                        try:
                            parsed = json.loads(m.group(0))
                        except Exception:
                            parsed = None

                if isinstance(parsed, dict):
                    # merge high-quality OCR text if present
                    model_ocr = parsed.get('ocr') or {}
                    mt = model_ocr.get('ocr_text') or parsed.get('ocr_text') or parsed.get('text')
                    if mt and len(str(mt).strip()) > len(ocr_text.strip()):
                        ocr_text = str(mt)

                    # if model returned signals, merge them preferentially
                    try:
                        m_signals = model_ocr.get('signals') or {}
                        for k, v in m_signals.items():
                            if v is not None:
                                local_signals[k] = v if isinstance(v, dict) else local_signals.get(k, v)
                    except Exception:
                        pass

                    # mountaineering extras and image meta
                    parsed_mounts = parsed.get('mountaineering_extras') or parsed.get('mountaineering')
                    parsed_image_meta = parsed.get('image_meta')

                    # extract named points from mountaineering extras or model_ocr
                    npnts = []
                    try:
                        if model_ocr.get('named_points'):
                            npnts = model_ocr.get('named_points')
                        elif parsed_mounts and isinstance(parsed_mounts, dict):
                            gp = parsed_mounts.get('geo_points') or {}
                            for v in gp.values():
                                if isinstance(v, str) and v:
                                    npnts.append(v)
                    except Exception:
                        npnts = []
                    if npnts:
                        try:
                            npnts = [str(x).strip() for x in npnts if x]
                            local_signals['terrain']['terrain_trap'] = list(dict.fromkeys(npnts))
                        except Exception:
                            pass

                    # numeric elevation hints from parsed_mounts
                    try:
                        if parsed_mounts and isinstance(parsed_mounts, dict):
                            gp = parsed_mounts.get('geo_points') or {}
                            for v in gp.values():
                                if isinstance(v, str):
                                    m = re.search(r"(\d{1,3}(?:,\d{3})?)\s*ft", v)
                                    if m:
                                        fe = int(m.group(1).replace(',', ''))
                                        local_signals.setdefault('elevation_feet', fe)
                                        if fe > 8000:
                                            local_signals['terrain']['elevation_band'] = 'alpine'
                                        break
                    except Exception:
                        pass

                    # store parsed extras into local variables to attach later
                    parsed_context = {
                        'mountaineering_extras': parsed_mounts,
                        'image_meta': parsed_image_meta,
                    }

                    ocr_model_used = model_name
        except Exception:
            # best-effort: ignore model failures and continue with local_signals
            pass

    # Full OpenAI path. Respect per-run cap.
    if not can_make_call():
        print(f"[OCR] OpenAI call cap reached (remaining=0). Skipping GPT analysis for {image_path}")
        # Return heuristics enriched by local OCR when OpenAI calls are not possible
        return {
            "summary": (ocr_text.splitlines()[0].strip() if ocr_text else os.path.basename(image_path)),
            "signals": local_signals,
            "confidence": 0.0,
            "ocr_text": ocr_text,
            "model": None,
            "mountaineering_extras": parsed_context.get('mountaineering_extras'),
            "image_meta": parsed_context.get('image_meta')
        }

    # When OpenAI is available, include the local OCR text to help the vision model
    user_content = [{"type": "text", "text": _SCHEMA_PROMPT}]
    if ocr_text:
        # provide OCR output as additional context to the model
        user_content.insert(0, {"type": "text", "text": f"OCR_TEXT:\n{ocr_text}"})
    user_content.append({"type": "image_url", "image_url": {"url": data_url}})

    try:
        resp = _chat_with_retries([
            {
                "role": "user",
                "content": user_content
            }
        ])
        # Record that we made one OpenAI call
        try:
            record_call(1)
        except Exception:
            pass
        txt = resp.choices[0].message.content.strip()
    except Exception:
        # Fall back to local OCR heuristics when OpenAI is not available or call fails
        return {
            "summary": (ocr_text.splitlines()[0].strip() if ocr_text else os.path.basename(image_path)),
            "signals": local_signals,
            "confidence": 0.0,
            "ocr_text": ocr_text,
            "model": None,
            "mountaineering_extras": parsed_context.get('mountaineering_extras'),
            "image_meta": parsed_context.get('image_meta')
        }

    # Parse strict JSON; fallback to baseline if needed
    try:
        obj = json.loads(txt)
        # Minimal sanity checks
        if not isinstance(obj, dict):
            raise ValueError("Non-dict JSON")
        if "summary" not in obj or "signals" not in obj or "confidence" not in obj:
            raise ValueError("Missing required keys")
        # Merge any non-null local_signals into the returned object when the model omits them
        try:
            if isinstance(obj, dict):
                # prefer model signals, but fill missing pieces from local_signals
                if not obj.get('signals'):
                    obj['signals'] = local_signals
                else:
                    # merge nested keys conservatively
                    for top_k, top_v in local_signals.items():
                        if top_k not in obj['signals'] or not obj['signals'].get(top_k):
                            obj['signals'][top_k] = top_v
                # include OCR text for debugging/traceability
                obj['ocr_text'] = ocr_text
                # attach any parsed context the earlier model branch may have populated
                obj['mountaineering_extras'] = parsed_context.get('mountaineering_extras')
                obj['image_meta'] = parsed_context.get('image_meta')
                # record which model produced any model-based enrichments (if available)
                obj['model'] = ocr_model_used or os.getenv('OPENAI_OCR_MODEL', 'gpt-4o-mini') if OPENAI_AVAILABLE else None
        except Exception:
            pass
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
            ,
            "ocr_text": ocr_text,
            "model": os.getenv('OPENAI_OCR_MODEL', 'gpt-4o-mini') if OPENAI_AVAILABLE else None,
            "mountaineering_extras": parsed_context.get('mountaineering_extras'),
            "image_meta": parsed_context.get('image_meta')
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

    # If caption is a generic photo credit or short description, skip alerting.
    if caption:
        low = caption.strip().lower()
        generic_tokens = ['photo', 'image', 'national park service', 'source:', 'credit:', 'photo by']
        if any(tok in low for tok in generic_tokens) and len(low) < 200:
            return True

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
            "model": ocr_obj.get("model"),
            "summary": ocr_obj.get("summary"),
            "signals": ocr_obj.get("signals"),
            "confidence": ocr_obj.get("confidence"),
            "ocr_text": ocr_obj.get("ocr_text"),
            "mountaineering_extras": ocr_obj.get("mountaineering_extras"),
            "image_meta": ocr_obj.get("image_meta")
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

