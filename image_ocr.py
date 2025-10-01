#!/usr/bin/env python3
"""
image_ocr.py (GPT-only replacement)

This module is a simplified, GPT-vision-only implementation that returns exactly the
requested JSON structure. It does not use local OCR or correlation heuristics.

Public functions:
 - analyze_conditions(image_path: str) -> dict
 - enrich_json_with_conditions(json_path: str) -> None
"""

from __future__ import annotations
import os
import json
import base64
import re
from pathlib import Path
from typing import Any, Dict

from openai import OpenAI
try:
    # Auto-load .env so OPENAI_API_KEY is picked up without manual export
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
try:
    # Auto-load .env if present so OPENAI_API_KEY is available without manual export
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from config import OCR_VISION_MODEL
from openai_call_manager import can_make_call, record_call


def _encode_image_as_data_url(image_path: str) -> str:
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    ext = os.path.splitext(image_path)[1].lower().lstrip('.') or 'jpeg'
    if ext not in ('jpg', 'jpeg', 'png', 'webp'):
        ext = 'jpeg'
    return f"data:image/{ext};base64,{b64}"


def _chat_vision_json(client: OpenAI, model: str, image_data_url: str) -> str:
    prompt = (
        "Return ONE JSON object only (no prose). Use exactly these keys and subkeys. If uncertain or not visible, use nulls. Units: include both ft/m where applicable.\n\n"
        "{\n"
        "  \"ocr\": {\n"
        "    \"model\": null,\n"
        "    \"summary\": \"short high-level description\",\n"
        "    \"signals\": {\n"
        "      \"avalanche_signs\": {\n"
        "        \"crown_line\": true|false|null,\n"
        "        \"debris\": true|false|null,\n"
        "        \"slide_paths\": string|null,\n"
        "        \"size_est\": \"D1\"|\"D2\"|\"D3\"|null,\n"
        "        \"slab_type\": \"wind\"|\"persistent\"|\"storm\"|\"wet_slab\"|\"dry_slab\"|\"loose_wet\"|\"loose_dry\"|null\n"
        "      },\n"
        "      \"snow_surface\": {\n"
        "        \"full_coverage\": true|false|null,\n"
        "        \"cornice\": string|null,\n"
        "        \"wind_loading\": string|null,\n"
        "        \"melt_freeze_crust\": string|boolean|null\n"
        "      },\n"
        "      \"terrain\": {\n"
        "        \"slope_angle_class\": string|null,\n"
        "        \"aspect\": string|null,\n"
        "        \"terrain_trap\": [string, ...]|null,\n"
        "        \"elevation_band\": string|null\n"
        "      },\n"
        "      \"glacier\": {\n"
        "        \"crevasses\": string|boolean|null,\n"
        "        \"seracs\": string|boolean|null,\n"
        "        \"snow_bridge_likely\": string|boolean|null\n"
        "      },\n"
        "      \"weather\": {\n"
        "        \"sky\": string|null,\n"
        "        \"visibility\": string|null,\n"
        "        \"precip\": string|null,\n"
        "        \"wind\": string|null\n"
        "      },\n"
        "      \"human_activity\": {\n"
        "        \"tracks\": string|boolean|null,\n"
        "        \"people_present\": boolean|null,\n"
        "        \"rope_or_harness\": boolean|null,\n"
        "        \"helmet\": boolean|null\n"
        "      },\n"
        "      \"rescue\": {\n"
        "        \"helicopter\": boolean|null,\n"
        "        \"longline\": boolean|null,\n"
        "        \"recco\": boolean|null,\n"
        "        \"personnel_on_foot\": boolean|null\n"
        "      }\n"
        "    },\n"
        "    \"confidence\": number\n"
        "  },\n"
        "  \"mountaineering_extras\": {\n"
        "    \"geo_points\": {\n"
        "      \"glacier_name\": string|null,\n"
        "      \"camp_location\": string|null,\n"
        "      \"summit_feature\": string|null\n"
        "    },\n"
        "    \"route_character\": string|null,\n"
        "    \"objective_hazards\": [string, ...]|null,\n"
        "    \"technical_rating_est\": string|null,\n"
        "    \"incline_degrees\": {\n"
        "      \"glacier_lower\": string|null,\n"
        "      \"approach_to_high_camp\": string|null,\n"
        "      \"ridge_section\": string|null\n"
        "    },\n"
        "    \"glacier_condition_est\": string|null,\n"
        "    \"approach_mode\": string|null,\n"
        "    \"retreat_options\": string|null\n"
        "  }\n"
        "}"
    )
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    }]
    resp = client.chat.completions.create(model=model, messages=messages)
    return resp.choices[0].message.content.strip()


def analyze_conditions(image_path: str) -> Dict[str, Any]:
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key or not can_make_call():
        # Conservative scaffold when model can't be called
        return {
            "ocr": {
                "model": None,
                "summary": None,
                "signals": {
                    "avalanche_signs": {"crown_line": None, "debris": None, "slide_paths": None, "size_est": None, "slab_type": None},
                    "snow_surface": {"full_coverage": None, "cornice": None, "wind_loading": None, "melt_freeze_crust": None},
                    "terrain": {"slope_angle_class": None, "aspect": None, "terrain_trap": None, "elevation_band": None},
                    "glacier": {"crevasses": None, "seracs": None, "snow_bridge_likely": None},
                    "weather": {"sky": None, "visibility": None, "precip": None, "wind": None},
                    "human_activity": {"tracks": None, "people_present": None, "rope_or_harness": None, "helmet": None},
                    "rescue": {"helicopter": None, "longline": None, "recco": None, "personnel_on_foot": None}
                },
                "confidence": 0.0
            },
            "mountaineering_extras": {
                "geo_points": {"glacier_name": None, "camp_location": None, "summit_feature": None},
                "route_character": None,
                "objective_hazards": None,
                "technical_rating_est": None,
                "incline_degrees": {"glacier_lower": None, 
                "approach_to_high_camp": None, 
                "ridge_section": None},
                "glacier_condition_est": None,
                "approach_mode": None,
                "retreat_options": None
            }
        }

    client = OpenAI()
    model = os.getenv('OCR_VISION_MODEL', OCR_VISION_MODEL)
    image_url = _encode_image_as_data_url(image_path)

    # Make the call
    content = _chat_vision_json(client, model, image_url)
    try:
        record_call(1)
    except Exception:
        pass

    # Parse and coerce into expected structure
    try:
        obj = json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, flags=re.S)
        obj = json.loads(m.group(0)) if m else {
            "ocr": {"model": model, "summary": None, "signals": {}, "confidence": 0.0},
            "mountaineering_extras": {}
        }

    # ensure mandatory keys
    obj.setdefault('ocr', {})
    obj.setdefault('mountaineering_extras', {})
    if isinstance(obj['ocr'], dict) and 'model' not in obj['ocr']:
        obj['ocr']['model'] = model
    return obj


def enrich_json_with_conditions(json_path: str) -> None:
    p = Path(json_path)
    data = json.loads(p.read_text(encoding='utf-8'))
    for entry in data:
        img = entry.get('local_image_path')
        if not img or not os.path.exists(img):
            continue
        result = analyze_conditions(img)
        entry['ocr'] = result.get('ocr')
        entry['mountaineering_extras'] = result.get('mountaineering_extras')
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"[INFO] ✅ Updated JSON with GPT-only OCR: {json_path}")


