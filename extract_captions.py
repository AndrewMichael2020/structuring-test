#!/usr/bin/env python3
"""
extract_captions.py
Extracts image captions + downloads images, filters stray ones, and outputs structured JSON.
"""

import re
import os
import io
import json
import time
import hashlib
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from PIL import Image

# Optional OCR fallback (Playwright)
try:
    from playwright.sync_api import sync_playwright
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


# -------------------- Utilities --------------------
def slugify(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)

def clean_caption(text: str) -> str:
    text = re.sub(r'\|\s*Image:.*$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def hash_url(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()[:10]

def is_stray_url(img_url: str) -> bool:
    if img_url.startswith("data:image"):
        return True
    if any(bad in img_url for bad in ["gravatar.com", "avatar", "favicon", "logo"]):
        return True
    return False

def is_stray_file(filepath: str, min_size=100) -> bool:
    try:
        with Image.open(filepath) as img:
            w, h = img.size
            return (w < min_size or h < min_size)
    except Exception:
        return True


# -------------------- Image Download --------------------
def download_image(img_url: str, folder: str) -> str | None:
    try:
        if is_stray_url(img_url):
            return None

        h = hash_url(img_url)
        ext = os.path.splitext(urlparse(img_url).path)[-1]
        if not ext or len(ext) > 5:
            ext = ".jpg"
        filename = f"{h}{ext}"
        filepath = os.path.join(folder, filename)
        if os.path.exists(filepath):
            return filepath

        r = requests.get(img_url, timeout=15)
        r.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(r.content)

        if is_stray_file(filepath):
            os.remove(filepath)
            return None

        return filepath
    except Exception:
        return None


# -------------------- HTML Caption Extraction --------------------
def extract_html_captions(url: str):
    html = requests.get(url, timeout=20).text
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for img in soup.find_all("img"):
        img_url = urljoin(url, img.get("src"))
        if is_stray_url(img_url):
            continue

        caption = None
        fig = img.find_parent("figure")
        if fig and fig.find("figcaption"):
            caption = fig.find("figcaption").get_text(strip=True)
        else:
            sib = img.find_parent().find_next_sibling("p")
            if sib:
                caption = sib.get_text(strip=True)

        if caption:
            results.append({
                "image_url": img_url,
                "caption_raw": caption,
                "caption_clean": clean_caption(caption),
                "method": "html",
                "local_image_path": None
            })
    return results


# -------------------- OCR fallback --------------------
def extract_ocr_captions(url: str):
    if not OCR_AVAILABLE:
        return []
    from pytesseract import image_to_string
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=60000)
        time.sleep(2)
        elements = page.query_selector_all("figure, img")
        for el in elements:
            try:
                img_bytes = el.screenshot()
                text = image_to_string(Image.open(io.BytesIO(img_bytes))).strip()
                if text:
                    results.append({
                        "image_url": None,
                        "caption_raw": text,
                        "caption_clean": clean_caption(text),
                        "method": "ocr",
                        "local_image_path": None
                    })
            except Exception:
                continue
        browser.close()
    return results


# -------------------- Deduplication --------------------
def deduplicate(items):
    seen = set()
    uniq = []
    for r in items:
        key = (r.get("image_url"), r.get("caption_clean"))
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    return uniq


# -------------------- Main callable --------------------
def extract_and_save(url: str, base_output="artifacts") -> str:
    """Extracts captions + images for a URL and saves JSON. Returns JSON path."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_folder = os.path.join(base_output, slugify(domain), timestamp)
    img_folder = os.path.join(base_folder, "images")
    os.makedirs(img_folder, exist_ok=True)

    print(f"[INFO] Extracting HTML captions from {url}")
    results = extract_html_captions(url)

    if OCR_AVAILABLE:
        print(f"[INFO] Running OCR fallback for JS-rendered captions")
        results.extend(extract_ocr_captions(url))

    results = deduplicate(results)

    print(f"[INFO] Downloading {len(results)} images")
    for r in results:
        if r["image_url"]:
            r["local_image_path"] = download_image(r["image_url"], img_folder)

    json_path = os.path.join(base_folder, "captions.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[INFO] ✅ Exported {len(results)} unique entries to {json_path}")
    print(f"[INFO] 🖼  Images stored in: {img_folder}")
    return json_path
