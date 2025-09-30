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

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {sys.argv[0]} <URL>")
        sys.exit(1)

    url = sys.argv[1]
    json_path = extract_and_save(url)
    enrich_json_with_conditions(json_path)
