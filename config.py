"""Simple runtime configuration for the extractor.

TIMEZONE: IANA name for the timezone to use when writing timestamps. Set to 'America/Vancouver' (BC PST/PDT).
GAZETTEER_ENABLED: when False, skip loading the local gazetteer (useful for testing or if you don't want to rely on it).
"""

TIMEZONE = 'America/Vancouver'
GAZETTEER_ENABLED = False
