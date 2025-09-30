#!/usr/bin/env python3
"""
main.py
Orchestrates full pipeline:
1. Extract captions + download images → JSON
2. Run OCR condition analysis on images → enrich JSON
"""

import sys
import sys
import time
from extract_captions import extract_and_save
from image_ocr import enrich_json_with_conditions
from pathlib import Path
from accident_info import extract_accident_info
from urllib.parse import urlparse

def ts_print(*args, **kwargs):
    t = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}]", *args, **kwargs)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        ts_print(f"Usage: python {sys.argv[0]} <URL> [--mode=all|text-only|ocr-only]")
        sys.exit(1)

    url = sys.argv[1]

    # parse optional mode
    mode = None
    for a in sys.argv[2:]:
        if a.startswith('--mode='):
            mode = a.split('=', 1)[1]

    if mode not in ('all', 'text-only', 'ocr-only'):
        # interactive prompt
        ts_print("Select run mode:")
        ts_print("  1) all (extract images, OCR, and article text)")
        ts_print("  2) text-only (skip OCR & image downloads, only extract article text)")
        ts_print("  3) ocr-only (use existing captions.json if present; run OCR only)")
        choice = input("Enter choice [1/2/3]: ").strip()
        if choice == '2':
            mode = 'text-only'
        elif choice == '3':
            mode = 'ocr-only'
        else:
            mode = 'all'

    ts_print(f"[INFO] Running mode: {mode}")

    # Mode behavior:
    # - all: run extraction (with downloads) + OCR + article text
    # - text-only: skip image downloads and OCR; only extract article text and accident info
    # - ocr-only: skip extraction/downloads; assume captions.json already exists and run OCR only

    json_path = None
    run_dir = None

    if mode == 'ocr-only':
        # find most recent captions.json under artifacts/<domain>/
        base = Path('artifacts') / Path(urlparse(url).netloc.replace('www.', ''))
        if not base.exists():
            ts_print(f"No artifacts found for {url}; nothing to OCR")
            sys.exit(1)
        # pick latest folder
        runs = sorted([p for p in base.iterdir() if p.is_dir()])
        if not runs:
            ts_print(f"No runs found in {base}; nothing to OCR")
            sys.exit(1)
        latest = runs[-1]
        json_path = str(latest / 'captions.json')
        run_dir = str(latest)
        ts_print(f"Using existing captions.json: {json_path}")
        enrich_json_with_conditions(json_path)

    elif mode == 'text-only':
        # only extract article text and accident info (skip downloads and OCR)
        json_path = extract_and_save(url, run_ocr=False, download_images=False)
        run_dir = str(Path(json_path).parent)
        ts_print(f"[INFO] Extracting accident info for {url}")
        extract_accident_info(url, out_dir=run_dir)

    else:  # all
        json_path = extract_and_save(url, run_ocr=True, download_images=True)
        ts_print(f"[INFO] Extracting HTML captions from {url}")
        enrich_json_with_conditions(json_path)
        run_dir = str(Path(json_path).parent)
        ts_print(f"[INFO] Extracting accident info for {url}")
        extract_accident_info(url, out_dir=run_dir)
