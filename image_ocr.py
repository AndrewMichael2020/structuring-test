#!/usr/bin/env python3
"""
image_ocr.py
1. Uses OpenAI GPT-4o-mini to extract brief condition/location info from images.
2. Compares extracted caption vs OCR text and logs alerts if they don't correlate.
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
def analyze_conditions(image_path: str) -> str:
    """Ask GPT-4o-mini to describe rescue/location conditions in the image."""
    prompt = (
        "Look at this image. Briefly describe any visible location or rescue CONDITIONS "
        "(e.g. avalanche debris, weather, visibility, rescue gear, terrain hazards). "
        "Return only a short factual phrase."
    )
    data_url = _encode_image_as_data_url(image_path)

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}}
                ]
            }
        ],
        temperature=0
    )
    return resp.choices[0].message.content.strip()


# -------------------- Caption vs OCR Judge --------------------
def judge_correlation(caption: str, ocr_text: str) -> bool:
    """
    Returns True if caption and OCR text correlate semantically.
    Uses GPT-4o-mini for cheap semantic similarity judgment.
    """
    if not caption or not ocr_text:
        return False

    judge_prompt = (
        f"Caption: \"{caption}\"\n"
        f"OCR Conditions: \"{ocr_text}\"\n\n"
        "Answer YES if the OCR text is meaningfully related to the caption, "
        "for example if they describe the same place, weather, or rescue scene. "
        "Answer NO if they are unrelated or describe different content. Respond with only YES or NO."
    )

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": [{"type": "text", "text": judge_prompt}]}
        ],
        temperature=0
    )
    decision = resp.choices[0].message.content.strip().upper()
    return decision.startswith("Y")


# -------------------- JSON Enrichment --------------------
def enrich_json_with_conditions(json_path: str):
    """Attach OCR condition info and check caption-OCR correlation."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for entry in data:
        lp = entry.get("local_image_path")
        caption = entry.get("caption_clean")
        if lp and os.path.exists(lp):
            print(f"[OCR] Analyzing: {lp}")
            ocr_text = analyze_conditions(lp)
            entry["ocr"] = {
                "conditions": ocr_text,
                "model": "gpt-4o-mini"
            }

            # Judge correlation
            correlated = judge_correlation(caption, ocr_text)
            if not correlated:
                print(f"⚠️ [ALERT] Caption/OCR mismatch:\n"
                      f"  Caption: {caption}\n"
                      f"  OCR: {ocr_text}\n"
                      f"  Image: {lp}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[INFO] ✅ Updated JSON with OCR conditions & correlation checks: {json_path}")
 