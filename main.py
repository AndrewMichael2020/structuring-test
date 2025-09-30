#!/usr/bin/env python3
"""
main.py
Orchestrates full pipeline:
1. Extract captions + download images → JSON
2. Run OCR condition analysis on images → enrich JSON
"""

import sys
from extract_captions import extract_and_save
from image_ocr import enrich_json_with_conditions
from pathlib import Path
from accident_info import extract_accident_info

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <URL>")
        sys.exit(1)

    url = sys.argv[1]
    # Step 1: captions + images
    json_path = extract_and_save(url)

    # Step 2: structured OCR condition analysis
    enrich_json_with_conditions(json_path)

    # Step 3: article-level accident info
    run_dir = str(Path(json_path).parent)
    extract_accident_info(url, out_dir=run_dir)
