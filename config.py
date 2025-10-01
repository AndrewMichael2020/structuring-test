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
"""

import os
import json
from pathlib import Path

# Built-in defaults
_DEFAULTS = {
	"timezone": "America/Vancouver",
	"gazetteer_enabled": False,
	"models": {
		"ocr_vision": "gpt-5",
		"accident_info": "gpt-5",
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
if os.getenv('OCR_VISION_MODEL'):
	_CFG.setdefault('models', {})['ocr_vision'] = os.getenv('OCR_VISION_MODEL')
if os.getenv('ACCIDENT_INFO_MODEL'):
	_CFG.setdefault('models', {})['accident_info'] = os.getenv('ACCIDENT_INFO_MODEL')

# Exported constants
TIMEZONE = _CFG.get('timezone', _DEFAULTS['timezone'])
GAZETTEER_ENABLED = bool(_CFG.get('gazetteer_enabled', _DEFAULTS['gazetteer_enabled']))
OCR_VISION_MODEL = _CFG.get('models', {}).get(
	'ocr_vision', _DEFAULTS['models']['ocr_vision']
)
ACCIDENT_INFO_MODEL = _CFG.get('models', {}).get(
	'accident_info', _DEFAULTS['models']['accident_info']
)
