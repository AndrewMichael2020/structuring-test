"""Simple runtime configuration for the extractor.

This module supports a visible, file-based configuration with environment
overrides.

Files (repo root):
- config.json (committed): default settings
- config.local.json (optional, gitignored): developer/local overrides

Precedence (highest first):
1) Env vars (OCR_VISION_MODEL, ACCIDENT_INFO_MODEL, TIMEZONE,
   GAZETTEER_ENABLED)
2) config.local.json
3) config.json
4) Built-in defaults

Keys:
- TIMEZONE: IANA timezone, e.g., 'America/Vancouver'
- GAZETTEER_ENABLED: bool
- models.ocr_vision: string (OpenAI vision model)
- models.accident_info: string (OpenAI text model)
 - models.event_cluster: string (OpenAI clustering model for event IDs)
 - models.event_merge: string (OpenAI model for text+OCR merge per event)
 - models.event_fusion: string (OpenAI model for multi-source fusion per event)
 - models.report_planner: string (OpenAI model for report outline planning)
 - models.report_writer: string (OpenAI model for report writing)
 - models.report_verifier: string (OpenAI model for verification/redaction)
 - service_tier: one of ['standard','flex','batch','priority'] (controls service tier selection); default 'standard'
"""

import os
import json
from pathlib import Path

# Built-in defaults
_DEFAULTS = {
	"timezone": "America/Vancouver",
	"gazetteer_enabled": False,
	"service_tier": "standard",
	"models": {
		"ocr_vision": "gpt-5",
		"accident_info": "gpt-5",
		"event_cluster": "gpt-5-mini",
		"event_merge": "gpt-5-mini",
		"event_fusion": "gpt-5",
		"report_planner": "gpt-5-mini",
		"report_writer": "gpt-5",
		"report_verifier": "gpt-5-mini",
	},
}

def _load_json_safe(p: Path) -> dict:
	try:
		if p.exists():
			with p.open('r', encoding='utf-8') as f:
				return json.load(f)
	except Exception:
		pass
	return {}

_ROOT = Path(__file__).parent
_CFG = _DEFAULTS.copy()
try:
	base = _load_json_safe(_ROOT / 'config.json')
	# deep merge: only one level deep needed for 'models'
	_CFG.update({k: v for k, v in base.items() if k != 'models'})
	if 'models' in base:
		_CFG.setdefault('models', {}).update(base['models'])
	local = _load_json_safe(_ROOT / 'config.local.json')
	_CFG.update({k: v for k, v in local.items() if k != 'models'})
	if 'models' in local:
		_CFG.setdefault('models', {}).update(local['models'])
except Exception:
	pass

# Env overrides (highest precedence)
if os.getenv('TIMEZONE'):
	_CFG['timezone'] = os.getenv('TIMEZONE')
if os.getenv('GAZETTEER_ENABLED'):
	_CFG['gazetteer_enabled'] = (
		os.getenv('GAZETTEER_ENABLED', 'false').lower() in ('1', 'true', 'yes')
	)
if os.getenv('SERVICE_TIER'):
	_CFG['service_tier'] = os.getenv('SERVICE_TIER')
if os.getenv('OCR_VISION_MODEL'):
	_CFG.setdefault('models', {})['ocr_vision'] = os.getenv('OCR_VISION_MODEL')
if os.getenv('ACCIDENT_INFO_MODEL'):
	_CFG.setdefault('models', {})['accident_info'] = os.getenv('ACCIDENT_INFO_MODEL')
if os.getenv('EVENT_CLUSTER_MODEL'):
	_CFG.setdefault('models', {})['event_cluster'] = os.getenv('EVENT_CLUSTER_MODEL')
if os.getenv('EVENT_MERGE_MODEL'):
	_CFG.setdefault('models', {})['event_merge'] = os.getenv('EVENT_MERGE_MODEL')
if os.getenv('EVENT_FUSION_MODEL'):
	_CFG.setdefault('models', {})['event_fusion'] = os.getenv('EVENT_FUSION_MODEL')
if os.getenv('REPORT_PLANNER_MODEL'):
	_CFG.setdefault('models', {})['report_planner'] = os.getenv('REPORT_PLANNER_MODEL')
if os.getenv('REPORT_WRITER_MODEL'):
	_CFG.setdefault('models', {})['report_writer'] = os.getenv('REPORT_WRITER_MODEL')
if os.getenv('REPORT_VERIFIER_MODEL'):
	_CFG.setdefault('models', {})['report_verifier'] = os.getenv('REPORT_VERIFIER_MODEL')

# Exported constants
TIMEZONE = _CFG.get('timezone', _DEFAULTS['timezone'])
GAZETTEER_ENABLED = bool(_CFG.get('gazetteer_enabled', _DEFAULTS['gazetteer_enabled']))

def _norm_tier(val: str | None) -> str:
    if not val:
        return _DEFAULTS['service_tier']
    v = str(val).strip().lower()
    if v in ('standard','flex','batch','priority'):
        return v
    # allow some aliases
    aliases = {
        'std': 'standard', 'priority-fast': 'priority', 'pr': 'priority',
    }
    return aliases.get(v, _DEFAULTS['service_tier'])

SERVICE_TIER = _norm_tier(_CFG.get('service_tier'))
OCR_VISION_MODEL = _CFG.get('models', {}).get(
	'ocr_vision', _DEFAULTS['models']['ocr_vision']
)
ACCIDENT_INFO_MODEL = _CFG.get('models', {}).get(
	'accident_info', _DEFAULTS['models']['accident_info']
)
EVENT_CLUSTER_MODEL = _CFG.get('models', {}).get(
	'event_cluster', _DEFAULTS['models']['event_cluster']
)
EVENT_MERGE_MODEL = _CFG.get('models', {}).get(
	'event_merge', _DEFAULTS['models']['event_merge']
)
EVENT_FUSION_MODEL = _CFG.get('models', {}).get(
	'event_fusion', _DEFAULTS['models']['event_fusion']
)
REPORT_PLANNER_MODEL = _CFG.get('models', {}).get(
	'report_planner', _DEFAULTS['models']['report_planner']
)
REPORT_WRITER_MODEL = _CFG.get('models', {}).get(
	'report_writer', _DEFAULTS['models']['report_writer']
)
REPORT_VERIFIER_MODEL = _CFG.get('models', {}).get(
	'report_verifier', _DEFAULTS['models']['report_verifier']
)
