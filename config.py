"""Simple runtime configuration for the extractor.

TIMEZONE: IANA name for the timezone to use when writing timestamps. Set to 'America/Vancouver' (BC PST/PDT).
GAZETTEER_ENABLED: when False, skip loading the local gazetteer (useful for testing or if you don't want to rely on it).
OCR_VISION_MODEL: OpenAI vision model to use for OCR/image analysis (default: 'gpt-5').
"""

import os

TIMEZONE = 'America/Vancouver'
GAZETTEER_ENABLED = False

# GPT vision model used for image OCR/scene understanding
OCR_VISION_MODEL = os.getenv('OCR_VISION_MODEL', 'gpt-5')
